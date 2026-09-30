#!/usr/bin/env python3
"""Benchmark Nobby's stable MPS and native-MLX LTX backends."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


DEFAULT_MODELS = ["ltx-2.5-22b-distilled", "ltx-2.5-mlx-q4"]
TERMINAL = {"completed", "failed", "cancelled"}
HEARTBEAT_SECONDS = 30.0


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


def reset_mlx_runtime(base_url):
    result = request_json(
        "POST",
        base_url.rstrip("/") + "/runtime/mlx/reset",
        {},
        timeout=30,
    )
    if not result.get("ok"):
        raise RuntimeError("MLX-Runtime konnte nicht zurückgesetzt werden")
    return result


def gb(value):
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) / (1024 ** 3), 2)


def elapsed_text(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def progress_text(job):
    phase = str(job.get("phase") or job.get("status") or "working")
    progress = job.get("progress")
    percentage = round(progress * 100) if isinstance(progress, (int, float)) else None
    step = job.get("current_step")
    total = job.get("total_steps")
    if isinstance(step, int) and isinstance(total, int) and step > 0 and total > 0:
        suffix = f" {step}/{total}"
        if percentage is not None:
            suffix += f" ({percentage} %)"
        return phase, percentage, step, total, phase + suffix
    if percentage is not None:
        return phase, percentage, None, total, f"{phase} ({percentage} %)"
    return phase, None, None, total, phase


def _print_fast_mlx_muxing_if_missed(model, phase, last_signature, total, elapsed):
    """Surface MLX's very short final mux phase when polling skips over it.

    The MLX provider emits an explicit muxing=98% event before it completes, but
    on a fast local run that state can be shorter than the benchmark polling
    interval.  If the terminal poll jumps directly from denoising to completed,
    render the known finalization transition once instead of hiding it.
    """
    if model != "ltx-2.5-mlx-q4" or phase != "completed":
        return
    previous_phase = last_signature[0] if last_signature else None
    if previous_phase in {"muxing", "completed"}:
        return
    suffix = ""
    if isinstance(total, int) and total > 0:
        suffix = f" {total}/{total}"
    print(f"    muxing{suffix} (98 %) · {elapsed_text(elapsed)}", flush=True)


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

    last_signature = None
    last_output_at = created_at
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        job = request_json("GET", base_url + f"/jobs/{job_id}", timeout=15)
        now = time.monotonic()
        phase, percentage, step, total, label = progress_text(job)
        signature = (phase, percentage, step, total)
        # Once real step metadata exists, repeating exactly the same step every
        # 30 seconds adds noise rather than information. Keep heartbeats only
        # for opaque phases/backends that cannot expose a current step.
        heartbeat_due = step is None and now - last_output_at >= HEARTBEAT_SECONDS
        if signature != last_signature or heartbeat_due:
            if signature != last_signature:
                _print_fast_mlx_muxing_if_missed(
                    model, phase, last_signature, total, now - created_at,
                )
            print(f"    {label} · {elapsed_text(now - created_at)}", flush=True)
            last_signature = signature
            last_output_at = now
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
        "status": "completed",
        "error": None,
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


def failed_result(model, exc):
    return {
        "status": "failed",
        "error": str(exc),
        "model": model,
        "provider": None,
        "backend": None,
        "runtime_start": "—",
        "wall_seconds": None,
        "provider_seconds": None,
        "ram_peak_gb": None,
        "swap_peak_gb": None,
    }


def print_table(results):
    print("\nErgebnisse")
    print("=" * 132)
    header = (
        f"{'Model':28} {'Status':9} {'Backend':15} {'Start':6} {'Size':13} "
        f"{'Wall':>9} {'Provider':>9} {'RAM peak':>10} {'Swap':>8}"
    )
    print(header)
    print("-" * 132)
    for item in results:
        size = f"{item.get('width') or '?'}x{item.get('height') or '?'}"
        provider = item.get("provider_seconds")
        provider_text = f"{provider:.1f}s" if isinstance(provider, (int, float)) else "—"
        wall = item.get("wall_seconds")
        wall_text = f"{wall:.1f}s" if isinstance(wall, (int, float)) else "—"
        ram = item.get("ram_peak_gb")
        swap = item.get("swap_peak_gb")
        print(
            f"{item['model'][:28]:28} {item.get('status', '—')[:9]:9} "
            f"{str(item.get('backend') or '—')[:15]:15} {str(item.get('runtime_start') or '—')[:6]:6} "
            f"{size:13} {wall_text:>9} {provider_text:>9} "
            f"{(f'{ram:.1f} GB' if ram is not None else '—'):>10} "
            f"{(f'{swap:.1f} GB' if swap is not None else '—'):>8}"
        )
        if item.get("error"):
            print(f"  ↳ {str(item['error'])[:118]}")
    print("=" * 132)


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
    parser.add_argument(
        "--cold-warm-cold",
        action="store_true",
        help="run exactly cold -> warm -> forced-cold for one native-MLX model",
    )
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

    if args.cold_warm_cold:
        if len(args.models) != 1:
            raise RuntimeError("--cold-warm-cold benötigt genau ein Modell")
        model = args.models[0]
        if available[model].get("provider") != "ltx-mlx":
            raise RuntimeError("--cold-warm-cold ist nur für das native MLX-Backend verfügbar")
        reset = reset_mlx_runtime(base_url)
        print(
            "\nIsolation Cold → Warm → Cold: "
            f"MLX-Worker zurückgesetzt (vorher geladen: {'ja' if reset.get('was_loaded') else 'nein'}).",
            flush=True,
        )
        repeat_count = 3
    else:
        repeat_count = max(1, args.repeats)

    results = []
    for repeat in range(1, repeat_count + 1):
        for model in args.models:
            print(f"\n[{repeat}/{repeat_count}] {model}", flush=True)
            if not available[model].get("available"):
                reason = available[model].get("availability_note") or "Backend nicht verfügbar"
                print(f"  FAILED: {reason}", file=sys.stderr)
                results.append(failed_result(model, reason))
                continue
            try:
                results.append(run_job(base_url, model, args, repeat))
            except Exception as exc:
                print(f"  FAILED: {exc}", file=sys.stderr)
                results.append(failed_result(model, exc))

        if args.cold_warm_cold and repeat == 2:
            reset = reset_mlx_runtime(base_url)
            print(
                "\n  MLX-Worker nach Warm-Lauf gezielt zurückgesetzt "
                f"(vorher geladen: {'ja' if reset.get('was_loaded') else 'nein'}).",
                flush=True,
            )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_table(results)

    if not any(item.get("status") == "completed" for item in results):
        raise RuntimeError("Kein Benchmark-Backend konnte einen Lauf abschließen")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
