#!/usr/bin/env python3
"""Privacy-preserving hybrid APC diagnosis through the existing Agent stream.

No real conversation content is accessed. Synthetic responses stay in RAM.
This diagnoses cache reuse on the Agent API, not the browser's internal payload.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(alias, filename):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = load("hybrid_diag_bench", "benchmark-chat-experience.py")
profiles = load("hybrid_diag_profiles", "chat-performance-profile.py")
COUNTERS = ("exact_hits", "exact_stores", "matched_tokens", "lookups_hit",
            "lookups_miss", "rejects")


def delta(before, after):
    result = {}
    for key in COUNTERS:
        a, b = before.get(key), after.get(key)
        result[key] = b - a if type(a) is int and type(b) is int and b >= a else None
    return result


def interpret(change):
    if change["exact_hits"] is None:
        return "telemetry_unavailable"
    if change["exact_hits"] > 0:
        return "exact_prefix_reused"
    if change["exact_stores"] and change["exact_stores"] > 0:
        return "stored_without_exact_reuse"
    return "no_exact_cache_activity"


def inspect():
    # The active service must already be hybrid; never switch or restart it.
    mode = profiles.configured_profile(profiles.CONFIG.read_text(encoding="utf-8"))
    if mode != "hybrid":
        raise RuntimeError("Hybrid profile required; refusing to switch profiles")
    profiles.ensure_idle()
    health = profiles.json_get(profiles.SERVER + "/health")
    if health.get("apc_enabled") is not True or not health.get("loaded_model"):
        raise RuntimeError("APC-enabled model required")
    if "hybrid_apc_dflash_runtime.py" not in profiles.current_server_args():
        raise RuntimeError("Hybrid adapter not running")
    initial = profiles.cache_snapshot()
    if initial.get("enabled") is not True or type(initial.get("exact_hits")) is not int:
        raise RuntimeError("Exact cache telemetry unavailable")

    conversation = [
        {"role": "system", "content": "Synthetischer lokaler APC-Test. Antworte jeweils mit genau einem kurzen Satz."},
        {"role": "user", "content": bench.synthetic_context(4000, "hybrid-agent-diagnostic", "stable") + "\nBitte antworte mit: BEREIT."},
    ]
    rows = []
    current = initial
    for turn in range(3):
        profiles.ensure_idle()
        timing, answer = bench.agent_stream(profiles.AGENT, conversation, 64, 300)
        after = profiles.cache_snapshot()
        change = delta(current, after)
        rows.append({
            "turn": turn + 1,
            "first_content_ms": timing["first_content_ms"],
            "total_ms": timing["total_ms"],
            "output_characters": timing["output_characters"],
            "cache_delta": change,
            "reason": interpret(change),
        })
        current = after
        if turn < 2:
            # Existing helper only retains the first 2048 visible characters.
            # Strictly short output (< 2048) required to preserve actual history.
            if timing["output_characters"] > len(answer):
                raise RuntimeError("Truncated response; cannot construct accurate chat history")
            conversation.append({"role": "assistant", "content": answer})
            conversation.append({"role": "user", "content": (
                "Erinnere dich an den Anfang dieser Unterhaltung. "
                "Antworte mit einem einzigen kurzen Satz. Folgefrage " + str(turn + 2)
            )})
    return {
        "schema": 1,
        "kind": "hybrid_agent_cache_diagnosis",
        "profile": "hybrid",
        "turns": rows,
        "followup_exact_hits": sum(row["cache_delta"]["exact_hits"] or 0 for row in rows[1:]),
        "notes": [
            "Uses actual Agent streaming endpoint with synthetic messages, but not browser UI.",
            "No prompt content, raw output, token hashes, or real user data persisted.",
            "A zero-hit result is insufficient to identify frontend request transformation.",
            "No profile switch, model restart or configuration mutation.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect()
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            # Avoid overwrites and keep metrics private.
            import os
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(rendered + "\n")
        print(rendered)
        return 0 if report["followup_exact_hits"] > 0 else 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Hybrid diagnosis stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
