#!/usr/bin/env python3
"""Opt-in, offline MLX-Gen Qwen Image Edit baseline; no model switches or downloads.

Run only while other Nobby media jobs are idle. This script deliberately does
not start/stop services or change MLX memory budgets. Outputs are local.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

MODEL = "AbstractFramework/qwen-image-edit-2511-4bit"
DEFAULT_RUNNER = Path.home() / ".local/share/mlx-gen-venv/bin/mlxgen"
PROMPT = "Change the main object color to bright orange. Keep everything else unchanged."


def positive_samples(raw):
    value = int(raw)
    if not 1 <= value <= 5:
        raise argparse.ArgumentTypeError("Samples must be between 1 and 5")
    return value


def read_rss_bytes(pid):
    """macOS/Linux best-effort process RSS, not total unified memory."""
    try:
        completed = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            text=True, capture_output=True, timeout=2, check=False)
        return int(completed.stdout.strip()) * 1024
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None


def parse_progress(log_text):
    """Read tqdm N/N steps; no confidential prompts or traces stored."""
    matches = re.findall(r"(\d+)\s*/\s*(\d+)\s*\[", log_text)
    return {"last_step": int(matches[-1][0]), "steps": int(matches[-1][1])} if matches else None


def run_once(runner, source, directory, index, *, steps, width, height, timeout, low_ram):
    output = directory / f"edit-{index:02d}.png"
    cmd = [
        str(runner), "generate", "--model", MODEL, "--image", str(source),
        "--prompt", PROMPT, "--width", str(width), "--height", str(height),
        "--steps", str(steps), "--output", str(output),
    ]
    if low_ram:
        cmd.append("--low-ram")
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1")
    # Keep raw diagnostics local only; never put them in summary JSON.
    log_path = directory / f"edit-{index:02d}.log"
    start = time.monotonic()
    peak = None
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=env, start_new_session=True)
        try:
            while process.poll() is None:
                if time.monotonic() - start >= timeout:
                    raise TimeoutError("Timed out; terminated only the benchmark process")
                rss = read_rss_bytes(process.pid)
                if rss is not None:
                    peak = max(peak or 0, rss)
                time.sleep(.5)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        status = process.wait()
    elapsed = round(time.monotonic() - start, 3)
    progress = parse_progress(log_path.read_text(encoding="utf-8", errors="replace"))
    ok = status == 0 and output.is_file() and output.stat().st_size > 0
    return {
        "sample": index, "wall_seconds": elapsed, "exit_code": status,
        "output_created": ok, "peak_runner_rss_gib": (
            round(peak / (1024 ** 3), 3) if peak is not None else None),
        "last_progress": progress, "low_ram": low_ram,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="Existing local PNG/JPEG (do not use a private photo for shared results)")
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/performance/image-edit"))
    parser.add_argument("--samples", type=positive_samples, default=2)
    parser.add_argument("--steps", type=int, choices=range(1, 21), metavar="1-20", default=4)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--low-ram", action="store_true", help="Use the existing MLX-Gen low-RAM mode; no cap bypass")
    args = parser.parse_args(argv)
    source = args.image.expanduser().resolve(strict=True)
    runner = args.runner.expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        parser.error("--image must be a local PNG/JPEG file")
    if not runner.is_file() or not os.access(runner, os.X_OK):
        parser.error("--runner must be an executable file")
    if args.width < 64 or args.height < 64 or args.width > 1024 or args.height > 1024 or args.width % 16 or args.height % 16:
        parser.error("Dimensions must be multiples of 16 between 64 and 1024")
    if args.timeout < 30 or args.timeout > 1800:
        parser.error("--timeout must be 30 to 1800 seconds")
    directory = args.output_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for index in range(1, args.samples + 1):
        result = run_once(runner, source, directory, index, steps=args.steps,
                          width=args.width, height=args.height,
                          timeout=args.timeout, low_ram=args.low_ram)
        results.append(result)
        print(f"Run {index}: {result['wall_seconds']}s, exit={result['exit_code']}", flush=True)
        if not result["output_created"]:
            break
    summary = {
        "schema": 1, "model": MODEL, "runner": "mlx-gen", "samples": results,
        "first_not_guaranteed_cold": True,
        "memory_metric": "RSS of MLX-Gen parent process only; excludes children, GPU allocations and swap",
        "notes": [
            "Sequential runs; later requests are not proof of persistent model residency.",
            "No model load/generation phase timings are inferred from wall time.",
            "Never compare low-ram modes unless all other settings and source are identical.",
            "No source image, prompt, or private paths are serialized to JSON.",
        ],
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if all(x["output_created"] for x in results) and len(results) == args.samples else 1


if __name__ == "__main__":
    sys.exit(main())
