#!/usr/bin/env python3
"""Opt-in long-form hybrid correctness + memory regression smoke.

The test replays the same synthetic two-turn dialog with DFlash2 and Hybrid,
validates three canary markers recalled from turn 1, checks long-form technical
content, and reports aggregate in-memory text similarity and memory snapshots.

No real chats, prompts or generated text are printed or persisted. The initial
profile is restored in a finally block, including Ctrl-C/SIGTERM.
This is a smoke test, not a formal equivalence proof.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
from pathlib import Path
import re
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_script(alias: str, name: str):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "scripts" / name)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Required Nobby script missing: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile = load_script("longform_chat_profiles", "chat-performance-profile.py")
bench = load_script("longform_chat_benchmark", "benchmark-chat-experience.py")
MARKERS = ("AURORAFADEN", "SILBERBRUECKE", "WALDFENSTER")
SYSTEM = (
    "Du bearbeitest einen isolierten, rein synthetischen Testdialog. "
    "Beantworte die letzte Nutzernachricht präzise und auf Deutsch. "
    "Gib keine internen Gedankengänge aus."
)


def make_messages(context_tokens: int):
    context = bench.synthetic_context(context_tokens, "hybrid-quality-2026", "neutral")
    note = (
        "\nPrüfnotiz (rein fiktiv, keine Benutzerdaten): "
        f"Kennwort 1 ist {MARKERS[0]}; Kennwort 2 ist {MARKERS[1]}; "
        f"Kennwort 3 ist {MARKERS[2]}.\n"
        "Bestätige diese Nachricht NUR mit START. Keine weiteren Zeichen."
    )
    first = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": context + note},
    ]
    followup = {
        "role": "user",
        "content": (
            "Erinnere dich an die drei Kennwörter aus der Prüfnotiz "
            "der ersten Nachricht. "
            "Die erste Ausgabezeile MUSS genau dieses Schema haben: "
            "Kennwort 1: <Wert 1>; Kennwort 2: <Wert 2>; Kennwort 3: <Wert 3>. "
            "Ersetze die Platzhalter durch die tatsächlichen Wörter "
            "aus der Prüfnotiz, ohne zusätzliche Wörter in dieser Zeile. "
            "Erkläre danach in mehreren ausführlichen deutschen Absätzen, "
            "wie Prefill, KV-Cache, Decoding und Streaming bei einem lokalen "
            "Sprachmodell zusammenspielen, einschließlich eines Beispiels "
            "für eine zweite Frage in demselben Gespräch. "
            "Schreibe mindestens 500 Zeichen und höchstens 350 Wörter. "
            "Gib keine internen Gedankengänge aus."
        ),
    }
    return first, followup


def canonical_text(text: str) -> str:
    """Normalize ASCII/umlauts and ignore separators for diagnostics only."""
    upper = text.upper()
    for letter, replacement in (
        ("Ä", "AE"), ("Ö", "OE"), ("Ü", "UE"), ("ẞ", "SS"), ("ß", "SS")
    ):
        upper = upper.replace(letter, replacement)
    return re.sub(r"[^A-Z0-9]", "", upper)


def marker_diagnostics(answer: str) -> dict:
    """Emit ONLY synthetic marker booleans, never model output text."""
    upper = answer.upper()
    canonical = canonical_text(answer)
    first_line = next((line for line in answer.splitlines() if line.strip()), "")
    return {
        "exact": {marker: marker in upper for marker in MARKERS},
        "normalized": {
            marker: canonical_text(marker) in canonical for marker in MARKERS
        },
        "first_line_exact": {
            marker: marker in first_line.upper() for marker in MARKERS
        },
        "first_nonempty_line_characters": len(first_line),
    }


def verify_long_answer(answer: str, reported_characters: int,
                       min_characters: int) -> dict:
    # bench.agent_stream retains at most the first 2048 visible characters.
    diagnostics = marker_diagnostics(answer)
    return {
        "canaries_recalled": all(diagnostics["exact"].values()),
        "technical_terms_present": all(
            term in answer.upper() for term in ("PREFILL", "DECODING", "STREAMING")
        ),
        "long_enough": reported_characters >= min_characters,
        "captured_text_not_empty": bool(answer.strip()),
    }


def check_memory(snapshot: dict, *, minimum_headroom_gb: float) -> None:
    if snapshot.get("pressure") != "normal":
        raise RuntimeError("System memory pressure is not normal")
    headroom = snapshot.get("headroom_gb")
    if type(headroom) not in (int, float) or headroom < minimum_headroom_gb:
        raise RuntimeError("Insufficient unified-memory headroom")


def memory_summary(snapshot: dict) -> dict:
    return {
        "free_percent": snapshot.get("free_percent"),
        "headroom_gb": snapshot.get("headroom_gb"),
        "swap_used_gb": snapshot.get("swap_used_gb"),
        "pressure": snapshot.get("pressure"),
    }


def check_swap_delta(before: dict, after: dict, *, max_delta_gb: float) -> float:
    a, b = before.get("swap_used_gb"), after.get("swap_used_gb")
    if type(a) not in (int, float) or type(b) not in (int, float):
        raise RuntimeError("Swap telemetry unavailable")
    delta = round(float(b) - float(a), 3)
    if delta > max_delta_gb:
        raise RuntimeError("Swap growth exceeded safety threshold")
    return delta


def run_mode(mode: str, context_tokens: int, min_characters: int,
             timeout: int) -> tuple[dict, str]:
    profile.ensure_idle()
    mem_before = profile.memory_snapshot()
    check_memory(mem_before, minimum_headroom_gb=6)
    apc_before = profile.cache_snapshot()
    first, followup = make_messages(context_tokens)

    prime_timing, prime_text = bench.agent_stream(
        profile.AGENT, first, 32, timeout
    )
    if re.sub(r'^[\s"“”*]+|[\s"“”*.,!?]+$', "", prime_text).upper() != "START":
        raise RuntimeError("Initial synthetic conversation did not prime correctly")
    profile.ensure_idle()
    conversation = first + [
        {"role": "assistant", "content": prime_text},
        followup,
    ]
    follow_timing, follow_text = bench.agent_stream(
        profile.AGENT, conversation, 384, timeout
    )
    apc_after = profile.cache_snapshot()
    mem_after = profile.memory_snapshot()
    check_memory(mem_after, minimum_headroom_gb=5)
    swap_delta = check_swap_delta(mem_before, mem_after, max_delta_gb=1.0)

    checks = verify_long_answer(
        follow_text, follow_timing["output_characters"], min_characters
    )
    if mode == "hybrid":
        before_hits, after_hits = (
            apc_before.get("exact_hits"), apc_after.get("exact_hits")
        )
        checks["exact_cache_hit"] = (
            type(before_hits) is int
            and type(after_hits) is int
            and after_hits > before_hits
        )

    report = {
        "profile": mode,
        "passed": all(checks.values()),
        "checks": checks,
        "synthetic_marker_diagnostics": marker_diagnostics(follow_text),
        "captured_output_characters": len(follow_text),
        "prime_first_content_ms": prime_timing["first_content_ms"],
        "followup_first_content_ms": follow_timing["first_content_ms"],
        "followup_total_ms": follow_timing["total_ms"],
        "followup_output_characters": follow_timing["output_characters"],
        "exact_hits_before": apc_before.get("exact_hits"),
        "exact_hits_after": apc_after.get("exact_hits"),
        "memory_before": memory_summary(mem_before),
        "memory_after": memory_summary(mem_after),
        "swap_delta_gb": swap_delta,
    }
    return report, follow_text


def compare_longform(context_tokens: int, min_characters: int, timeout: int):
    original = profile.configured_profile(profile.CONFIG.read_text(encoding="utf-8"))
    profile.ensure_idle()
    profile.preflight("dflash")
    handlers = {}

    def interrupted(signum, frame):
        raise KeyboardInterrupt()

    for signum in (signal.SIGINT, signal.SIGTERM):
        handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupted)

    reports = []
    texts = []
    try:
        for mode in ("dflash", "hybrid"):
            print(f"Long-form quality: {mode}...", file=sys.stderr, flush=True)
            profile.switch_profile(mode)
            report, text = run_mode(mode, context_tokens, min_characters, timeout)
            reports.append(report)
            texts.append(text)
    finally:
        try:
            if profile.configured_profile(
                profile.CONFIG.read_text(encoding="utf-8")
            ) != original:
                profile.switch_profile(original)
        finally:
            for signum, original_handler in handlers.items():
                signal.signal(signum, original_handler)

    # Content comparison uses strings in RAM only; never print/save them.
    normalized = [re.sub(r"\s+", " ", s).strip().lower() for s in texts]
    ratio = round(
        difflib.SequenceMatcher(None, normalized[0], normalized[1]).ratio(), 3
    )
    return {
        "schema": 1,
        "kind": "hybrid_longform_quality_memory_smoke",
        "starting_profile_restored": original,
        "context_tokens_nominal": context_tokens,
        "minimum_output_characters": min_characters,
        "passed": len(reports) == 2 and all(r["passed"] for r in reports),
        "results": reports,
        "comparison": {
            "captured_text_similarity_ratio": ratio,
            "near_identical": ratio >= 0.9,
            "similarity_is_advisory": True,
        },
        "notes": [
            "Synthetic context and deterministic zero-temperature agent requests.",
            "First 2048 visible characters retained in memory for verification.",
            "Content similarity is descriptive, not a hard quality verdict.",
            "Per-marker booleans distinguish missing values from formatting; strict exact recall still gates.",
            "The follow-up now requests a concrete first-line format; no marker values appear in it.",
            "Memory before/after is not an instantaneous or continuous peak measurement.",
            "No private user content, model text or prompts are persisted.",
            "A pass is not proof of numerical equivalence or overall answer quality.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-size", type=int, choices=(4000, 8000),
                        default=4000)
    parser.add_argument("--min-characters", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if not 200 <= args.min_characters <= 1400:
        parser.error("--min-characters must be in 200..1400")
    if not 30 <= args.timeout <= 600:
        parser.error("--timeout must be in 30..600")
    try:
        report = compare_longform(
            args.context_size, args.min_characters, args.timeout
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["passed"] else 2
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError,
            KeyboardInterrupt) as exc:
        print(f"Long-form quality check stopped: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
