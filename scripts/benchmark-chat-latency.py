#!/usr/bin/env python3
"""Opt-in, content-free local MLX chat cold/warm latency probe.

Does not load, select, unload or restart models. Run only against an already
loaded model and an idle local service. No prompts or completions are saved.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit

import httpx

PROMPT = "Antworte ausschließlich mit OK."


def validate_loopback(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1"} or
            parsed.username or parsed.password or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError("Only a plain HTTP loopback origin is allowed")
    return url.rstrip("/")


def positive_int(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 20:
        raise argparse.ArgumentTypeError("Expected an integer from 1 to 20")
    return number


def finite_ms(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 3) if math.isfinite(value) and value >= 0 else None


def summarize(samples):
    numbers = sorted(x for x in samples if x is not None)
    if not numbers:
        return {"count": 0, "p50_ms": None, "p95_ms": None}
    def percentile(p):
        index = (len(numbers) - 1) * p
        lower = int(index)
        upper = min(lower + 1, len(numbers) - 1)
        return round(numbers[lower] + (numbers[upper] - numbers[lower]) * (index - lower), 3)
    return {"count": len(numbers), "p50_ms": percentile(.5), "p95_ms": percentile(.95)}


def sample(client, model, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0, "max_tokens": 16, "stream": False,
    }
    start = time.monotonic()
    response = client.post("/v1/chat/completions", json=payload, timeout=timeout)
    elapsed = round((time.monotonic() - start) * 1000, 3)
    response.raise_for_status()
    body = response.json()
    if not body.get("choices") or not isinstance(body.get("usage"), dict):
        raise ValueError("Missing chat completion or usage metrics")
    timing = body.get("timings") or {}
    return {
        "wall_ms": elapsed,
        "prompt_ms": finite_ms(timing.get("prompt_ms")),
        "generation_ms": finite_ms(timing.get("predicted_ms")),
        "prompt_tokens": body["usage"].get("prompt_tokens"),
        "completion_tokens": body["usage"].get("completion_tokens"),
        "server_timing_available": finite_ms(timing.get("prompt_ms")) is not None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=validate_loopback, default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True, help="Exact already loaded model ID; never switches models")
    parser.add_argument("--samples", type=positive_int, default=5)
    parser.add_argument("--timeout", type=positive_int, default=90, help="Seconds per request (1–20)")
    parser.add_argument("--output", type=Path, help="Optional local JSON path; no prompts/completions stored")
    args = parser.parse_args(argv)
    with httpx.Client(base_url=args.url, trust_env=False) as client:
        results = [sample(client, args.model, args.timeout) for _ in range(args.samples)]
    report = {
        "schema": 1, "model": args.model, "sample_count": len(results),
        "first_request_is_not_guaranteed_cold": True,
        "first": results[0], "subsequent": results[1:],
        "summary": {field: summarize([r[field] for r in results[1:]])
                    for field in ("wall_ms", "prompt_ms", "generation_ms")},
        "notes": [
            "Warm means subsequent request in the same run, not proof that weights stayed resident.",
            "The first request may already be warm; this tool cannot enforce a cold start.",
            "Server timings, if supplied, are separate from end-to-end wall time.",
            "No system RAM/swap attribution, model loading or image/video switching is performed.",
        ],
    }
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
