#!/usr/bin/env python3
"""Benchmark Nobby's stable MPS and experimental native-MLX LTX backends."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


DEFAULT_MODELS = ["ltx-2.5-22b-distilled", "ltx-2.5-mlx-q4"]
TERMINAL = {"completed", "failed", "cancelled"}


def request_json(method, url, payload=None, timeout=30):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def gb(value):
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) / (1024 ** 3), 2)


def run_job(base_url, model, args, repeat):
    created_at = time.monotonic()
    payload = {
        "operation": "t2v",
        "chat_id": "ltx-benchmark",
        "run_id": f"benchmark-{model}-{repeat}-{int(time.time())}",
        "chat_revision": 0,
        "payload": {
            "prompt": args.prompt,
            "model": model,
            "quality": args.quality,
            "duration": args.duration,
            "fps": args.fps,
            "seed": args.seed,
            "aspect_ratio": args.aspect_ratio,
        },
    }
    job = request_json("POST", base_url + "/jobs", payload, timeout=30)
    job_id = job["id"]
    print(f"  job {job_id}: gestartet", flush=True)

    last_phase = None
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        job = request_json("GET", base_url + f"/jobs/{job_id}", timeout=15)
        phase = job.get("phase")
        if phase and phase != last_phase:
            progress = job.get("progress")
            suffix = f" ({progress * 100:.0f} %)" if isinstance(progress, (int, float)) else ""
            print(f"    {phase}{suffix}", flush=True)
            last_phase = phase
        if job.get("status") in TERMINAL:
            break
        time.sleep(args.poll)
    else:
        try:
            request_json("POST", base_url + f"/jobs/{job_id}/cancel", {}, timeout=30)
        except Exception:
            pass
        raise RuntimeError(f"Timeout nach {args.timeout:.0f} s")

    wall = round(time.monotonic() - created_at, 3)
    if job.get("status") != "completed":
        raise RuntimeError(job.get("error") or f"Job endete mit {job.get('status')}")

    result = job.get("result") or {}
    peak = result.get("memory_peak") or job.get("memory_peak") or {}
    before = result.get("memory_before") or job.get("memory_before") or {}
    after = result.get("memory_after") or job.get("memory_after") or {}
    return {
        "model": model,
        "provider": result.get("provider"),
        "backend": result.get("backend") or result.get("provider"),
        "quantization": result.get("quantization"),
        "quality": result.get("quality"),
        "resolution": result.get("resolution"),
        "width": result.get("width"),
        "height": result.get("height"),
        "duration": result.get("duration"),
        "fps": result.get("fps"),
        "frames": result.get("frames"),
        "runtime_start": "warm" if result.get("runtime_reused") is True else (
            "cold" if result.get("runtime_reused") is False else "unknown"
        ),
        "wall_seconds": wall,
        "provider_seconds": result.get("provider_elapsed_seconds"),
        "ram_before_gb": gb(before.get("ram_used_bytes")),
        "ram_peak_gb": gb(peak.get("ram_used_bytes")),
        "ram_after_gb": gb(after.get("ram_used_bytes")),
        "swap_peak_gb": gb(peak.get("swap_used_bytes")),
        "path": result.get("path"),
    }


def print_table(results):
    print("\nErgebnisse")
    print("=" * 118)
    header = (
        f"{'Model':28} {'Backend':15} {'Start':6} {'Size':13} "
        f"{'Wall':>9} {'Provider':>9} {'RAM peak':>10} {'Swap':>8}"
    )
    print(header)
    print("-" * 118)
    for item in results:
        size = f"{item.get('width') or '?'}x{item.get('height') or '?'}"
        provider = item.get("provider_seconds")
        provider_text = f"{provider:.1f}s" if isinstance(provider, (int, float)) else "—"
        ram = item.get("ram_peak_gb")
        swap = item.get("swap_peak_gb")
        print(
            f"{item['model'][:28]:28} {str(item.get('backend') or '—')[:15]:15} "
            f"{item['runtime_start'][:6]:6} {size:13} "
            f"{item['wall_seconds']:8.1f}s {provider_text:>9} "
            f"{(f'{ram:.1f} GB' if ram is not None else '—'):>10} "
            f"{(f'{swap:.1f} GB' if swap is not None else '—'):>8}"
        )
    print("=" * 118)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8060")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--quality", choices=("preview", "fast", "standard", "quality"), default="standard")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--fps", type=int, choices=(8, 24), default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--prompt", default="Cinematic tracking shot of a red sports car driving through rain at night, realistic reflections, smooth motion")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    models = request_json("GET", base_url + "/models", timeout=15)
    available = {item["id"]: item for item in models.get("models", [])}
    missing = [model for model in args.models if model not in available]
    if missing:
        raise RuntimeError("Unbekannte Video-Modelle: " + ", ".join(missing))

    unavailable = [
        model for model in args.models
        if not available[model].get("available")
    ]
    if unavailable:
        for model in unavailable:
            print(f"{model}: {available[model].get('availability_note')}", file=sys.stderr)
        raise RuntimeError("Nicht alle Benchmark-Backends sind verfügbar")

    results = []
    for repeat in range(1, max(1, args.repeats) + 1):
        for model in args.models:
            print(f"\n[{repeat}/{max(1, args.repeats)}] {model}", flush=True)
            results.append(run_job(base_url, model, args, repeat))

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_table(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
