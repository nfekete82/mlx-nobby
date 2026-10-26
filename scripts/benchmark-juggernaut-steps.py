#!/usr/bin/env python3
"""Opt-in, same-seed Juggernaut XL quality/speed A/B test on localhost.

This script performs no GPU work unless --run is explicitly given. It never
stores prompts in its JSON report; image artifacts stay in the local service.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

STEPS = (30, 35, 40)
MODEL = "juggernaut-xl"
PROMPT = (
    "A realistic documentary photograph of a red fox resting in an autumn "
    "forest, soft natural morning light, fine fur, detailed leaves, "
    "believable textures, natural colors, 50mm lens"
)
JOB_ID = re.compile(r"^[a-f0-9]{24}$")


def origin_only(origin):
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username or parsed.password or parsed.query
        or parsed.fragment or parsed.path not in ("", "/")
    ):
        raise argparse.ArgumentTypeError("Only a plain HTTP loopback URL is allowed")
    return origin.rstrip("/")


def request_json(origin, method, path, data=None):
    request = Request(
        origin + path,
        method=method,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Image Service returned invalid JSON")
    return result


def image_request(prompt, seed, steps):
    if steps not in STEPS or not 0 <= seed < 2**32:
        raise ValueError("Unsupported steps or seed")
    return {
        "operation": "generate",
        "chat_id": "juggernaut-step-benchmark",
        "chat_revision": 0,
        "payload": {
            "prompt": prompt,
            "model": MODEL,
            "width": 512,
            "height": 512,
            "auto_size": True,
            "quality": "quality",
            "guidance": 4.0,
            "steps": steps,
            "seed": seed,
        },
    }


def run_compare(origin, prompt, seed, *, getter=request_json, sleep=time.sleep, clock=time.monotonic):
    health = getter(origin, "GET", "/health")
    if health.get("status") != "ready" or health.get("active_generation") is not False:
        raise RuntimeError("Image-Service must be ready and idle")
    if MODEL not in health.get("models", []):
        raise RuntimeError("Juggernaut XL is not available on this service")

    samples = []
    for steps in STEPS:
        # Every job independently uses existing RAM admission, safe SDXL unload,
        # and final chat restore. No model overlap or unsafe warm cache.
        job = getter(origin, "POST", "/jobs", image_request(prompt, seed, steps))
        job_id = job.get("id")
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise RuntimeError("Image-Service returned an invalid job ID")
        start = clock()
        try:
            while True:
                if clock() - start > 360:
                    raise TimeoutError("Image job exceeded 360s")
                response = getter(origin, "GET", "/jobs/" + job_id)
                status = response.get("status")
                if status in {"failed", "cancelled"}:
                    raise RuntimeError(f"Juggernaut {steps}-step job {status}; compare aborted")
                if status == "completed":
                    break
                if status not in {"queued", "loading", "running", "saving"}:
                    raise RuntimeError("Unexpected job state; compare aborted")
                sleep(0.5)
        except BaseException:
            # Cancellation is best-effort; never start the next job after failure.
            try:
                getter(origin, "POST", "/jobs/" + job_id + "/cancel")
            except Exception:
                pass
            raise
        result = response.get("result") or {}
        if (
            result.get("model") != MODEL
            or result.get("steps") != steps
            or result.get("seed") != seed
            or result.get("width") != 1216
            or result.get("height") != 1216
        ):
            raise RuntimeError("Different model, seed or dimensions; invalid A/B sample")
        timing = response.get("performance_timings") or {}
        samples.append({
            "steps": steps,
            "elapsed_s": round(clock() - start, 2),
            "execution_ms": timing.get("execution_ms"),
            "provider_and_setup_ms": timing.get("provider_and_setup_ms"),
            "runtime_return_ms": timing.get("runtime_return_ms"),
            "path": result.get("path"),
        })
    return samples


def contact_sheet(samples, output):
    try:
        from PIL import Image, ImageDraw
        images = []
        for item in samples:
            source = Path(item["path"])
            if not source.is_file():
                return None
            with Image.open(source) as img:
                tile = img.convert("RGB")
                tile.thumbnail((450, 450), Image.Resampling.LANCZOS)
                images.append(tile.copy())
        sheet = Image.new("RGB", (3 * 470, 520), "#191d25")
        draw = ImageDraw.Draw(sheet)
        for i, (item, tile) in enumerate(zip(samples, images)):
            offset = i * 470
            sheet.paste(tile, (offset + (470 - tile.width) // 2, 36))
            draw.text((offset + 15, 12),
                      f"{item['steps']} steps | {item['elapsed_s']:.1f} seconds",
                      fill="white")
        destination = output.with_suffix(".jpg")
        sheet.save(destination, format="JPEG", quality=92, optimize=True)
        return str(destination)
    except (ImportError, OSError, ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Actually generate 3 sequential images")
    parser.add_argument("--url", default="http://127.0.0.1:8030", type=origin_only)
    parser.add_argument("--seed", default=31337, type=int)
    parser.add_argument("--prompt-file", type=Path, help="Optional local UTF-8 prompt file")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not 0 <= args.seed < 2**32:
        parser.error("Seed must be a 32-bit unsigned integer")
    prompt = args.prompt_file.read_text(encoding="utf-8").strip() if args.prompt_file else PROMPT
    if not 3 <= len(prompt) <= 2000:
        parser.error("Prompt must contain 3–2000 characters")
    print("Juggernaut XL A/B: 30 / 35 / 40 steps · 1216 x 1216 · identical seed")
    if not args.run:
        print("Dry run only. Pass --run to start 3 sequential local image jobs.")
        return
    output = args.output or Path("artifacts/performance") / (
        "juggernaut-steps-" + time.strftime("%Y%m%d-%H%M%S") + ".json"
    )
    samples = run_compare(args.url, prompt, args.seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Paths and user prompts stay out of machine-readable reports.
    safe_samples = [{k: v for k, v in s.items() if k != "path"} for s in samples]
    report = {
        "model": MODEL, "dimensions": [1216, 1216],
        "seed": args.seed, "samples": safe_samples,
        "note": "Sequential cold jobs; total includes safe chat handoff. Compare image details manually.",
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    collage = contact_sheet(samples, output)
    for sample in safe_samples:
        print(f"{sample['steps']} steps: {sample['elapsed_s']:.2f} seconds")
    print("Timing report:", output)
    if collage:
        print("Side-by-side image:", collage)


if __name__ == "__main__":
    main()
