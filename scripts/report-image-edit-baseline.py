#!/usr/bin/env python3
"""Read-only Nobby image-edit baseline from completed local media jobs.

Does not generate, reload, cancel or delete any media. The JSON report excludes
user prompts, image data, file paths and chat IDs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import statistics
from urllib.parse import urlsplit
from urllib.request import urlopen

JOB_ID = re.compile(r"^[0-9a-f]{24}$")


def loopback_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1"} or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise argparse.ArgumentTypeError("Only a plain HTTP loopback origin is allowed")
    return value.rstrip("/")


def safe_ms(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return round(float(value), 2) if math.isfinite(value) and value >= 0 else None


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=8) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def collect(origin: str, *, samples=3, getter=fetch_json) -> dict:
    observatory = getter(origin + "/api/performance/observatory?limit=100")
    recent = ((observatory.get("media") or {}).get("recent_jobs") or [])
    candidates = [
        job for job in recent if isinstance(job, dict)
        and job.get("kind") == "image"
        and job.get("status") == "completed"
        and isinstance(job.get("id"), str) and JOB_ID.fullmatch(job["id"])
    ][:samples]
    results = []
    for index, candidate in enumerate(candidates, 1):
        details = getter(origin + "/api/mlx/image-jobs/" + candidate["id"])
        job = (details.get("data") or {}).get("job") or details.get("job") or {}
        if job.get("id") != candidate["id"] or job.get("kind") not in (None, "image"):
            raise ValueError("Job identity changed while reading performance data")
        provider = job.get("provider_timing") or {}
        native = job.get("performance_timings") or {}
        results.append({
            "sample": index,
            "model": str(candidate.get("model") or "")[:100],
            "total_ms": safe_ms(candidate.get("total_ms")),
            "queue_wait_ms": safe_ms(candidate.get("queue_wait_ms")),
            "generation_ms": safe_ms(candidate.get("generation_ms")),
            "process_wall_ms": safe_ms(provider.get("process_wall_ms")),
            "process_spawn_ms": safe_ms(provider.get("process_spawn_ms")),
            "first_output_ms": safe_ms(provider.get("first_output_ms")),
            "resource_wait_ms": safe_ms(native.get("resource_wait_ms")),
            "execution_ms": safe_ms(native.get("execution_ms")),
            "fresh_process": provider.get("fresh_process")
                             if type(provider.get("fresh_process")) is bool else None,
        })
    metrics = ("total_ms", "queue_wait_ms", "generation_ms", "process_wall_ms",
               "process_spawn_ms", "first_output_ms", "resource_wait_ms", "execution_ms")
    return {
        "schema": 1,
        "requested_samples": samples,
        "received_samples": len(results),
        "samples": results,
        "median_ms": {
            key: round(statistics.median(values), 2) if (
                values := [row[key] for row in results if row[key] is not None]
            ) else None for key in metrics
        },
        "notes": [
            "Use three sequential identical image edits; this tool does not verify prompts or dimensions.",
            "Missing measurements are null, not zero. Jobs must run with the new instrumentation to include startup timings.",
            "First output is log activity, not model loading or first GPU step.",
            "Read-only: does not start, cancel, delete or modify any jobs.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=loopback_origin, default="http://127.0.0.1:8010")
    parser.add_argument("--samples", type=int, choices=(1, 2, 3, 4, 5), default=3)
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/performance/image-edit-job-baseline.json"))
    args = parser.parse_args(argv)
    result = collect(args.url, samples=args.samples)
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
