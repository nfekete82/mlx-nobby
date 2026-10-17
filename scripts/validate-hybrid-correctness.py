#!/usr/bin/env python3
"""Opt-in text-only correctness smoke for experimental APC+DFlash2.

Runs deterministic two-turn synthetic conversations via Nobby's protected
Agent SSE endpoint. The previous chat profile is restored on ordinary errors,
interrupts and failed quality checks. No prompt or response text is logged.

Passing only proves the few synthetic cases exercised here, not broad model
correctness, numerical cache equivalence, or complete memory safety.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]


def import_script(alias: str, filename: str):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile = import_script("nobby_quality_profile", "chat-performance-profile.py")
bench = import_script("nobby_quality_benchmark", "benchmark-chat-experience.py")

SYSTEM = (
    "Dies ist ein isolierter, rein synthetischer Qualitätstest. "
    "Halte dich exakt an die Anweisung in der letzten Nutzernachricht. "
    "Antworte mit nur einem einzigen Wort, ohne Satzzeichen und ohne Begründung."
)
TEST_MARKER = "MONDFALTER"
PRIME_EXPECTED = "START"
FOLLOW_EXPECTED = TEST_MARKER


def normalize(text: str) -> str:
    return re.sub(r'^[\s"“”*]+|[\s"“”*.,!?]+$', "", text).upper()


def synthetic_turns(context_size: int):
    synthetic = bench.synthetic_context(context_size, "quality-check-fixed", "fixed")
    prime_question = (
        f"{synthetic}\n\n"
        f"Testnotiz: Das CODEWORT ist {TEST_MARKER}. "
        f"Präge dir das CODEWORT für die nächste Frage ein.\n"
        f"Antworte jetzt AUSSCHLIESSLICH mit {PRIME_EXPECTED}."
    )
    first = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prime_question},
    ]
    second_question = "Welches CODEWORT stand in der Testnotiz? Nur das CODEWORT."
    return first, second_question


def safety_memory_check(memory: dict) -> None:
    if memory.get("pressure") != "normal":
        raise RuntimeError("Memory pressure not normal; refusing correctness test")
    headroom = memory.get("headroom_gb")
    if type(headroom) not in (int, float) or headroom < 6:
        raise RuntimeError("Insufficient free memory headroom for hybrid test")


def test_profile(mode: str, context_size: int, timeout: int) -> dict:
    profile.ensure_idle()
    safety_memory_check(profile.memory_snapshot())
    first, follow_question = synthetic_turns(context_size)
    bench.check_idle(bench.request_json(profile.AGENT, "/api/performance/observatory?limit=1"))
    previous = profile.cache_snapshot()
    first_metric, first_text = bench.agent_stream(profile.AGENT, first, 32, timeout)
    second = first + [
        {"role": "assistant", "content": first_text},
        {"role": "user", "content": follow_question},
    ]
    bench.check_idle(bench.request_json(profile.AGENT, "/api/performance/observatory?limit=1"))
    second_metric, second_text = bench.agent_stream(profile.AGENT, second, 32, timeout)
    after = profile.cache_snapshot()
    checks = {
        "first_answer_expected": normalize(first_text) == PRIME_EXPECTED,
        "followup_answer_expected": normalize(second_text) == FOLLOW_EXPECTED,
    }
    if mode == "hybrid":
        hits_before = previous.get("exact_hits")
        hits_after = after.get("exact_hits")
        checks["hybrid_exact_cache_hit"] = (
            type(hits_before) is int
            and type(hits_after) is int
            and hits_after > hits_before
        )
    return {
        "profile": mode,
        "checks": checks,
        "passed": all(checks.values()),
        "first_content_ms": first_metric["first_content_ms"],
        "followup_first_content_ms": second_metric["first_content_ms"],
        "followup_total_ms": second_metric["total_ms"],
        "exact_cache_hits_before": previous.get("exact_hits"),
        "exact_cache_hits_after": after.get("exact_hits"),
    }


def validate(context_size: int, timeout: int) -> dict:
    prior = profile.configured_profile(profile.CONFIG.read_text(encoding="utf-8"))
    profile.ensure_idle()
    profile.preflight("dflash")
    original_handlers = {}

    def interrupted(signum, frame):
        raise KeyboardInterrupt()

    for signum in (signal.SIGINT, signal.SIGTERM):
        original_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupted)
    results = []
    try:
        for mode in ("dflash", "hybrid"):
            print(f"Quality check: {mode}...", file=sys.stderr, flush=True)
            profile.switch_profile(mode)
            results.append(test_profile(mode, context_size, timeout))
    finally:
        try:
            if profile.configured_profile(profile.CONFIG.read_text(encoding="utf-8")) != prior:
                print(f"Restoring original chat profile: {prior}", file=sys.stderr)
                profile.switch_profile(prior)
        finally:
            for signum, original in original_handlers.items():
                signal.signal(signum, original)

    return {
        "schema": 1,
        "kind": "experimental_hybrid_synthetic_correctness_gate",
        "context_tokens_nominal": context_size,
        "starting_profile_restored": prior,
        "passed": len(results) == 2 and all(x["passed"] for x in results),
        "results": results,
        "notes": [
            "Synthetic German one-word memory checks; no user content.",
            "Temperature=0 through the protected Nobby Agent stream.",
            "Model responses are checked in memory; contents are never saved or printed.",
            "Passing does not prove broad generation quality, cache equivalence, or memory safety.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-size", type=int, default=4000, choices=(4000, 8000))
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    if not 20 <= args.timeout <= 600:
        parser.error("--timeout must be 20..600")
    try:
        report = validate(args.context_size, args.timeout)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["passed"] else 2
    except (RuntimeError, ValueError, OSError, KeyboardInterrupt) as exc:
        print(f"Quality check stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
