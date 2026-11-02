#!/usr/bin/env python3
"""Opt-in comparison of two local OpenAI-compatible inference servers.

Read-only with respect to configuration: requests can still trigger lazy model
loading. Run only when both runtimes have enough free memory and are idle.
No prompts, completions, tokens, secrets, or endpoint credentials are stored.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import httpx

BENCH = Path(__file__).with_name("benchmark-chat-latency.py")
spec = importlib.util.spec_from_file_location("mlx_latency_probe", BENCH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlx-url", type=probe.validate_loopback, default="http://127.0.0.1:8000")
    parser.add_argument("--mlx-model", required=True)
    parser.add_argument("--strata-url", type=probe.validate_loopback, default="http://127.0.0.1:8080")
    parser.add_argument("--strata-model", required=True)
    parser.add_argument("--samples", type=lambda x: probe.bounded_int(x, 2, 20), default=5)
    parser.add_argument("--profile", choices=tuple(probe.PROFILES), default="short")
    parser.add_argument("--timeout", type=lambda x: probe.bounded_int(x, 1, 600), default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mlx_url == args.strata_url:
        parser.error("Use different local server origins to avoid comparing a server with itself.")
    prompt, max_tokens = probe.PROFILES[args.profile]
    endpoints = {
        "mlx": {"url": args.mlx_url, "model": args.mlx_model},
        "strata": {"url": args.strata_url, "model": args.strata_model},
    }
    samples = {name: [] for name in endpoints}
    # Alternate order to limit simple warmup/time drift bias.
    # Each server gets an unreported warmup request.
    try:
        if True:
            for name, endpoint in endpoints.items():
                # Independent client per origin, never pass a key to either server.
                with httpx.Client(base_url=endpoint["url"], trust_env=False) as local:
                    probe.sample(local, endpoint["model"], args.timeout, prompt, max_tokens)
            for i in range(args.samples):
                for name in (("mlx", "strata") if i % 2 == 0 else ("strata", "mlx")):
                    endpoint = endpoints[name]
                    with httpx.Client(base_url=endpoint["url"], trust_env=False) as local:
                        samples[name].append(probe.sample(local, endpoint["model"], args.timeout, prompt, max_tokens))
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1

    fields = ("wall_ms", "prompt_ms", "generation_ms", "generation_tps", "completion_tokens")
    results = {
        name: {
            "model": endpoints[name]["model"],
            "sample_count": len(rows),
            "summary": {
                field: probe.summarize(
                    [r[field] for r in rows],
                    unit={"generation_tps": "tokens/s", "completion_tokens": "tokens"}.get(field, "ms"))
                for field in fields
            },
            "completion_token_min": min(r["completion_tokens"] for r in rows),
            "completion_token_max": max(r["completion_tokens"] for r in rows),
            "finish_reasons": sorted(set(str(r["finish_reason"]) for r in rows)),
        }
        for name, rows in samples.items()
    }
    ml = results["mlx"]["summary"]["wall_ms"]["p50_ms"]
    st = results["strata"]["summary"]["wall_ms"]["p50_ms"]
    report = {
        "schema": 1,
        "profile": args.profile,
        "output_cap_tokens": max_tokens,
        "results": results,
        "median_wall_ratio_strata_over_mlx": round(st / ml, 3) if ml and st else None,
        "notes": [
            "Different architectures/models and tokenizers are not quality- or speed-equivalent.",
            "Compare completion token counts and finish reasons before interpreting wall times.",
            "Warmup calls can lazily load a model. This tool does not start, stop, or reconfigure services.",
            "No RAM/swap, energy, image quality or long-context measurement is included.",
            "Tokens/s is available only if each server provides compatible timing metrics.",
        ],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
