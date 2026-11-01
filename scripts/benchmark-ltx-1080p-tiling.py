#!/usr/bin/env python3
"""Isolated 1080p temporal/spatial tiling experiment for LTX 2.5 MLX.

Does not modify MLX-Nobby's API, model weights, services or runtime.
The high-resolution duration restriction remains unchanged in production.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


GIB = 1024 ** 3
ROOT = Path.home() / ".local/share/mlx-nobby"
CLI = ROOT / "ltx-2-mlx/.venv/bin/ltx-2-mlx"
MODEL = ROOT / "models/ltx-2.5-mlx-q4"
WIDTH, HEIGHT, FPS = 1920, 1088, 24
MIN_START_FREE_PERCENT = 30
MIN_RUNNING_FREE_PERCENT = 12
MAX_SWAP_GROWTH_GIB = 3.0


def command(cli: Path, model: Path, output: Path, *, duration: int,
            tile_frames: int, tile_spatial: int, tile_overlap: int,
            prompt: str, seed: int) -> list[str]:
    if duration not in (5, 6, 8, 10):
        raise ValueError("Duration must be 5, 6, 8 or 10 seconds")
    if tile_frames < 1 or tile_spatial < 1 or tile_overlap < 1:
        raise ValueError("Tile counts and overlap must be positive")
    return [
        str(cli), "generate", "--distilled", "--low-ram",
        "--model", str(model),
        "--prompt", prompt,
        "--output", str(output),
        "--width", str(WIDTH), "--height", str(HEIGHT),
        "--frames", str(duration * FPS + 1),
        "--frame-rate", str(FPS), "--seed", str(seed),
        "--stage1-steps", "8", "--stage2-steps", "3",
        "--tile-frames", str(tile_frames),
        "--tile-spatial", str(tile_spatial),
        "--tile-overlap", str(tile_overlap),
    ]


def command_text(argv: list[str]) -> str:
    import shlex
    return shlex.join(argv)


def parse_free_percent(value: str) -> int | None:
    """Support macOS memory_pressure -Q variants (with or without 'memory')."""
    match = re.search(
        r"System-wide(?: memory)? free percentage:\s*(\d+)%",
        value, re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def read_free_percent() -> int | None:
    try:
        completed = subprocess.run(
            ["/usr/bin/memory_pressure", "-Q"], capture_output=True,
            text=True, check=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_free_percent(completed.stdout)


def parse_swap_gib(value: str) -> float | None:
    match = re.search(r"\bused\s*=\s*([\d.]+)\s*([KMGT])(?:i?B)?\b",
                      value, re.IGNORECASE)
    if match is None:
        return None
    power = {"K": 1, "M": 2, "G": 3, "T": 4}[match.group(2).upper()]
    return float(match.group(1)) * (1024 ** power) / GIB


def read_swap_gib() -> float | None:
    try:
        completed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"], capture_output=True,
            text=True, check=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_swap_gib(completed.stdout)


def video_service_busy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8060/health",
                                    timeout=3) as response:
            result = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return result.get("status") == "busy" or bool(result.get("active_generation"))


def require_supported_cli(cli: Path) -> None:
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise RuntimeError(f"LTX-MLX CLI not found: {cli}")
    result = subprocess.run(
        [str(cli), "generate", "--help"], capture_output=True,
        text=True, timeout=40)
    help_text = result.stdout + result.stderr
    if result.returncode != 0 or any(
        flag not in help_text
        for flag in ("--tile-frames", "--tile-spatial", "--tile-overlap")
    ):
        raise RuntimeError("Installed CLI does not support the tiling switches")


def stop_own_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=12)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="Actually render; otherwise just display configuration")
    parser.add_argument("--duration", type=int, choices=(5, 6, 8, 10), default=6)
    parser.add_argument("--tile-frames", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--tile-spatial", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--tile-overlap", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prompt", default=(
        "A single adult person walking slowly in a sunlit garden, "
        "consistent appearance, fixed camera, full-body view, natural "
        "continuous movement, realistic lighting, no cuts or zooms"))
    parser.add_argument("--max-minutes", type=float, default=60)
    parser.add_argument("--max-swap-growth-gib", type=float,
                        default=MAX_SWAP_GROWTH_GIB)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cli", type=Path, default=CLI)
    parser.add_argument("--model", type=Path, default=MODEL)
    args = parser.parse_args()
    if args.max_minutes <= 0 or args.max_swap_growth_gib <= 0:
        parser.error("Watchdog thresholds must be positive")
    if args.tile_frames > 1 and args.tile_overlap >= args.duration * FPS // 8:
        parser.error("Tile overlap is too large for the requested duration")

    folder = args.output_dir or (
        ROOT / "tiling-experiments" /
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.duration}s")
    video = folder / "result.mp4"
    argv = command(args.cli.expanduser(), args.model.expanduser(), video,
                   duration=args.duration, tile_frames=args.tile_frames,
                   tile_spatial=args.tile_spatial, tile_overlap=args.tile_overlap,
                   prompt=args.prompt, seed=args.seed)
    print("1080p temporal tiling experiment (production settings unchanged)")
    print(command_text(argv), flush=True)
    if not args.run:
        print("\nDry run only. Add --run to start rendering.")
        return 0
    if sys.platform != "darwin":
        print("Real rendering is supported only on macOS.", file=sys.stderr)
        return 2
    if not args.model.expanduser().is_dir():
        print("Model folder not found.", file=sys.stderr)
        return 2
    if video_service_busy():
        print("Another MLX-Nobby video job is active; aborting.", file=sys.stderr)
        return 2
    try:
        require_supported_cli(args.cli.expanduser())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 2
    start_free = read_free_percent()
    initial_swap = read_swap_gib()
    if start_free is None or initial_swap is None:
        print(f"Cannot measure memory pressure and swap: "
              f"free_percent={start_free!r}, swap_gib={initial_swap!r}; "
              "aborting. Diagnostic commands: memory_pressure -Q; "
              "sysctl -n vm.swapusage", file=sys.stderr)
        return 2
    if start_free < MIN_START_FREE_PERCENT:
        print(f"Only {start_free}% memory free (needs {MIN_START_FREE_PERCENT}%); "
              "close active memory-heavy apps first.", file=sys.stderr)
        return 2

    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    started = time.monotonic()
    peak_swap = initial_swap
    min_free = start_free
    status = "failed"
    abort_reason = None
    exit_code = None
    log_path = folder / "runtime.log"
    process = None
    try:
        with log_path.open("w", encoding="utf-8") as logfile:
            process = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=logfile,
                stderr=subprocess.STDOUT, start_new_session=True)
            last_print = 0.0
            while process.poll() is None:
                time.sleep(2)
                free = read_free_percent()
                swap = read_swap_gib()
                if free is None or swap is None:
                    abort_reason = "Memory telemetry unavailable"
                else:
                    min_free = min(min_free, free)
                    peak_swap = max(peak_swap, swap)
                    if free < MIN_RUNNING_FREE_PERCENT:
                        abort_reason = f"Free memory below {MIN_RUNNING_FREE_PERCENT}%"
                    elif swap - initial_swap >= args.max_swap_growth_gib:
                        abort_reason = "Swap growth exceeded limit"
                elapsed = time.monotonic() - started
                if elapsed - last_print >= 20:
                    print(f"{elapsed:.0f}s | free={free}% | "
                          f"swap={swap} GiB | swap growth="
                          f"{(swap-initial_swap) if swap is not None else None} GiB",
                          flush=True)
                    last_print = elapsed
                if abort_reason is None and elapsed > args.max_minutes * 60:
                    abort_reason = "Benchmark timeout"
                if abort_reason:
                    stop_own_process_group(process)
                    break
            exit_code = process.wait(timeout=15)
            if abort_reason:
                status = "aborted"
            elif exit_code == 0 and video.is_file() and video.stat().st_size > 0:
                status = "completed"
            else:
                abort_reason = f"CLI failed (exit {exit_code}); inspect runtime.log"
    except KeyboardInterrupt:
        status = "aborted"
        abort_reason = "Interrupted by user"
        if process:
            stop_own_process_group(process)
    except Exception as error:
        status = "failed"
        abort_reason = f"{type(error).__name__}: {error}"
        if process:
            stop_own_process_group(process)
    finally:
        report = {
            "status": status,
            "reason": abort_reason,
            "duration_seconds": args.duration,
            "dimensions": [WIDTH, HEIGHT],
            "frames": args.duration * FPS + 1,
            "tile_frames": args.tile_frames,
            "tile_spatial": args.tile_spatial,
            "tile_overlap": args.tile_overlap,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "free_before_percent": start_free,
            "free_min_percent": min_free,
            "swap_before_gib": round(initial_swap, 3),
            "swap_peak_gib": round(peak_swap, 3),
            "swap_growth_gib": round(peak_swap - initial_swap, 3),
            "exit_code": exit_code,
            "video": str(video) if video.is_file() else None,
            "log": str(log_path),
        }
        report_path = folder / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n",
                               encoding="utf-8")
        report_path.chmod(0o600)
        print("\n" + json.dumps(report, indent=2), flush=True)
        print(f"Test files: {folder}", flush=True)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
