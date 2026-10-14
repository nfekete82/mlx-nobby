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


def model_identifier(job) -> str:
    return str(job.get("model") or "unknown")[:100]


def time_series(values) -> dict:
    ordered = sorted(value for item in values if (value := safe_ms(item)) is not None)
    if not ordered:
        return {"count": 0, "median": None, "p95": None, "average": None}
    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        low, high = int(position), min(int(position) + 1, len(ordered) - 1)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 2)
    return {
        "count": len(ordered),
        "median": percentile(.5),
        "p95": percentile(.95),
        "average": round(statistics.mean(ordered), 2),
    }


def collect(origin: str, *, samples=3, model=None, getter=fetch_json) -> dict:
    observatory = getter(origin + "/api/performance/observatory?limit=100")
    recent = ((observatory.get("media") or {}).get("recent_jobs") or [])
    completed = [
        job for job in recent if isinstance(job, dict)
        and job.get("kind") == "image"
        and job.get("status") == "completed"
        and isinstance(job.get("id"), str) and JOB_ID.fullmatch(job["id"])
    ]
    groups = {}
    for job in completed:
        groups.setdefault(model_identifier(job), []).append(job)
    by_model = [
        {
            "model": name,
            "count": len(items),
            "total_ms": time_series(item.get("total_ms") for item in items),
            "generation_ms": time_series(item.get("generation_ms") for item in items),
            "queue_wait_ms": time_series(item.get("queue_wait_ms") for item in items),
        }
        for name, items in groups.items()
    ]
    by_model.sort(key=lambda group: (-group["count"], group["model"]))
    # The detailed telemetry reads only the chosen model, avoiding invalid
    # cross-model startup comparisons and unnecessary API requests.
    candidates = [
        job for job in completed
        if model is None or model_identifier(job) == model
    ][:samples]
    results = []
    for index, candidate in enumerate(candidates, 1):
        # Observatory already owns queue job identifiers; do not send them to
        # native image-service endpoints (these use different identifiers).
        # Read only the Observatory's whitelisted content-free telemetry.
        provider = candidate.get("provider_timing") or {}
        provider = provider if isinstance(provider, dict) else {}
        native = candidate.get("performance_timings") or {}
        native = native if isinstance(native, dict) else {}
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
        "schema": 2,
        "requested_samples": samples,
        "selected_model": model,
        "received_samples": len(results),
        "completed_image_jobs": len(completed),
        "by_model": by_model,
        "samples": results,
        "median_ms": {
            key: round(statistics.median(values), 2) if (
                values := [row[key] for row in results if row[key] is not None]
            ) else None for key in metrics
        },
        "notes": [
            "Per-model summaries may still mix image dimensions, steps and settings; they are observational, not matched benchmarks.",
            "Detailed samples are restricted to --model when supplied; without it, samples may still span multiple models.",
            "Use three sequential identical image edits for a controlled comparison; this tool does not verify prompts or dimensions.",
            "Missing measurements are null, not zero. Jobs must run with the new instrumentation to include startup timings.",
            "First output is log activity, not model loading or first GPU step.",
            "Read-only: a single Observatory GET; does not start, cancel, delete or modify any jobs.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=loopback_origin, default="http://127.0.0.1:8010")
    parser.add_argument("--samples", type=int, choices=(1, 2, 3, 4, 5), default=3)
    parser.add_argument("--model", help="Exact image model ID for the detailed samples; group summaries still show all models")
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/performance/image-edit-job-baseline.json"))
    args = parser.parse_args(argv)
    result = collect(args.url, samples=args.samples, model=args.model)
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
