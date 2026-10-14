#!/usr/bin/env python3
"""Opt-in, sequential local Qwen 2.1 Edit step-cache A/B benchmark.

Default is dry-run. --run starts four native guarded image jobs (OFF/ON/ON/OFF)
and preserves each output for a manual visual-quality comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

MODEL = "mflux-osaurus-qwen-image-2.1-edit"
ROOTS = ("images", "uploads", "attachments", "batch/uploads")
TERMINAL = {"completed", "failed", "cancelled"}


def local_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1"} or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise argparse.ArgumentTypeError("Use only a plain local HTTP origin")
    return value.rstrip("/")


def source_info(value):
    """Exactly square >=1024 reference; service will use 1024px quality edge."""
    from PIL import Image

    path = Path(value).expanduser().resolve(strict=True)
    root = (Path.home() / ".config/mlx-web").resolve()
    if not path.is_file() or not any(
        path.is_relative_to((root / suffix).resolve()) for suffix in ROOTS
    ):
        raise ValueError("Source must be a file in the approved MLX Nobby image/upload folders")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Source must be PNG, JPEG or WEBP")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Source must be at most 20 MiB")
    with Image.open(path) as image:
        if image.width != image.height or image.width < 1024:
            raise ValueError("For an exact 1024x1024 comparison, use a square source >=1024px")
        if image.width * image.height > 25_000_000:
            raise ValueError("Source exceeds the image pixel budget")
        image.verify()
    return path


def source_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def sequence(cycles):
    if cycles not in (1, 2):
        raise ValueError("cycles must be 1 or 2")
    return (False, True, True, False) * cycles


def payload(source, prompt, seed, enabled, threshold):
    request = {
        "model": MODEL,
        "source_path": str(source),
        "prompt": prompt,
        "quality": "quality",
        "steps": 40,
        "guidance": 1.0,
        "seed": seed,
        "use_kv_cache": True,
        "use_step_cache": enabled,
    }
    if enabled:
        request["step_cache_threshold"] = threshold
    return request


def request_json(origin, path, *, body=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        origin + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Local image service returned HTTP {exc.code} on {path.split('?')[0]}") from exc
    except URLError as exc:
        raise RuntimeError("Local image service is unreachable") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Unexpected non-object response from image service")
    return value


def preflight(origin):
    health = request_json(origin, "/health")
    if health.get("status") != "ready" or health.get("active_job_id"):
        raise RuntimeError("Image service is busy; do not run this benchmark with active media jobs")
    if MODEL not in health.get("models", []):
        raise RuntimeError("Osaurus Qwen 2.1 Edit is not enabled on the local image service")
    detail = request_json(origin, "/models/" + quote(MODEL, safe=""))
    if detail.get("model_family") != "qwen-image21-edit" or detail.get("provider") != "mflux":
        raise RuntimeError("Image model does not match the expected MFLUX Qwen 2.1 Edit provider")


def await_terminal(origin, job_id, *, timeout=1000, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout
    while clock() < deadline:
        job = request_json(origin, "/jobs/" + quote(job_id, safe=""))
        status = job.get("status")
        if status in TERMINAL:
            return job
        sleep(2)
    raise RuntimeError(
        "Benchmark polling timed out. The native image job may still be running; "
        "inspect it in Nobby before starting another job."
    )


def comparable_jobs(results):
    """Only compute speedup when complete, same-workload, matched memory mode."""
    if len(results) < 4 or len(results) % 4:
        return False
    configs = []
    for row in results:
        timer = row.get("provider_timing") or {}
        if not isinstance(timer, dict):
            return False
        expected = row["step_cache"]
        if timer.get("use_step_cache") is not expected:
            return False
        signature = tuple(timer.get(k) for k in (
            "steps", "width", "height", "guidance", "reference_count",
            "use_kv_cache", "low_ram", "mflux_cache_limit_gb",
        ))
        if any(value is None for value in signature):
            return False
        if signature[:3] != (40, 1024, 1024) or signature[5] is not True:
            return False
        if not isinstance(row.get("total_ms"), (int, float)):
            return False
        if not math.isfinite(row["total_ms"]) or row["total_ms"] <= 0:
            return False
        configs.append(signature)
    return len(set(configs)) == 1


def summary(results):
    off = [row["total_ms"] for row in results if row["step_cache"] is False]
    on = [row["total_ms"] for row in results if row["step_cache"] is True]
    if not comparable_jobs(results) or len(off) != len(on):
        return {"comparable": False, "reason": "Unmatched settings, incomplete telemetry or missing jobs"}
    off_ms, on_ms = statistics.median(off), statistics.median(on)
    return {
        "comparable": True,
        "cache_off_median_ms": round(off_ms, 2),
        "cache_on_median_ms": round(on_ms, 2),
        "cache_on_change_pct": round((on_ms / off_ms - 1) * 100, 2),
        "note": "Negative change means faster; picture fidelity requires manual visual inspection.",
    }


def write_report(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".qwen-ab-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(origin, source, prompt, *, seed, cycles, threshold, output, requester=request_json,
        poller=await_terminal):
    preflight(origin)
    initial_digest = source_digest(source)
    results = []
    report = {
        "schema": 1,
        "model": MODEL,
        "steps": 40,
        "expected_resolution": [1024, 1024],
        "seed": seed,
        "cache_threshold": threshold,
        "order": ["on" if state else "off" for state in sequence(cycles)],
        "jobs": results,
        "summary": {"comparable": False},
        "notes": [
            "Raw prompt and source path are intentionally excluded; image output paths are local/private.",
            "No automatic image-quality verdict. Compare actual saved pictures.",
            "Native /jobs enforces existing runtime memory coordination and process safeguards.",
            "All jobs are sequential. A failure stops the sequence; never automatically cancels jobs.",
        ],
    }
    for index, enabled in enumerate(sequence(cycles), 1):
        if source_digest(source) != initial_digest:
            raise RuntimeError("Reference image changed during benchmark; refusing further jobs")
        health = requester(origin, "/health")
        if health.get("status") != "ready" or health.get("active_job_id"):
            raise RuntimeError("Image service became busy; refusing to start another benchmark job")
        plan = payload(source, prompt, seed, enabled, threshold)
        submitted = requester(origin, "/jobs", body={
            "operation": "edit", "payload": plan,
            "chat_id": "local-step-cache-benchmark-" + secrets.token_hex(8),
            "chat_revision": 0,
        })
        job_id = submitted.get("id")
        if not isinstance(job_id, str) or len(job_id) != 24:
            raise RuntimeError("Native image service did not return an expected job identifier")
        print(f"Job {index}/{len(sequence(cycles))}: step cache {'ON' if enabled else 'OFF'}", flush=True)
        job = poller(origin, job_id)
        if job.get("status") != "completed":
            raise RuntimeError(f"Job {index} ended with status {job.get('status')!r}; no further jobs started")
        image = job.get("result") or {}
        if image.get("model") != MODEL or image.get("steps") != 40 or (image.get("width"), image.get("height")) != (1024, 1024):
            raise RuntimeError(f"Job {index} used unexpected output settings; benchmark stopped")
        timer = job.get("provider_timing") or {}
        created, finished = job.get("created_at"), job.get("finished_at")
        elapsed = round((finished - created) * 1000, 2) if isinstance(created, (int, float)) and isinstance(finished, (int, float)) else None
        row = {
            "run": index, "step_cache": enabled,
            "total_ms": elapsed,
            "image_path": image.get("path"),  # Stored with 0600 permissions for visual comparison.
            "provider_timing": {
                key: timer.get(key) for key in (
                    "steps", "width", "height", "guidance", "reference_count",
                    "use_step_cache", "use_kv_cache", "low_ram",
                    "mflux_cache_limit_gb", "process_wall_ms", "tqdm_window_ms",
                )
            },
        }
        results.append(row)
        report["summary"] = summary(results)
        write_report(output, report)
        print(f"  completed: {elapsed / 1000:.2f}s; saved image {image.get('path')}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_origin, default="http://127.0.0.1:8030")
    parser.add_argument("--source", type=Path, required=True)
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--prompt-file", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cycles", type=int, choices=(1, 2), default=1)
    parser.add_argument("--threshold", type=float, default=0.12)
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/performance/qwen21-step-cache-ab.json"))
    parser.add_argument("--run", action="store_true",
                        help="Explicit consent to start 4 (or 8) sequential GPU jobs")
    args = parser.parse_args(argv)
    if args.seed < 0 or args.seed >= 2**32 or not math.isfinite(args.threshold) or not 0 < args.threshold <= 1:
        parser.error("Seed or threshold out of range")
    prompt = args.prompt if args.prompt is not None else args.prompt_file.expanduser().read_text(encoding="utf-8").strip()
    if not 3 <= len(prompt) <= 2000:
        parser.error("Prompt must contain 3..2000 characters")
    source = source_info(args.source)
    print(f"Planned {4 * args.cycles} jobs: OFF -> ON -> ON -> OFF"
          + (f" x{args.cycles}" if args.cycles > 1 else ""))
    print("Model: Osaurus Qwen 2.1 Edit | quality 1024x1024 | 40 steps | guidance 1 | identical seed")
    if not args.run:
        print("DRY RUN: no jobs started; add --run to execute.")
        return 0
    result = run(args.url, source, prompt, seed=args.seed, cycles=args.cycles,
                 threshold=args.threshold, output=args.output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Private local report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
