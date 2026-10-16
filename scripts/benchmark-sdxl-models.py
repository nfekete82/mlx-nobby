#!/usr/bin/env python3
"""Compare two local SDXL checkpoints with identical generation settings.

Example:
    python scripts/benchmark-sdxl-models.py --seed 42 --repeats 2

The image service is unloaded by default before benchmark workers start.
No model download, no registry mutation, no automatic NSFW prompt injection.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "benchmark-juggernaut.py"
MODEL_DIRS = {
    "juggernaut-xl": Path.home() / "Models/JuggernautXL",
    "lustify-endgame-sdxl": Path.home() / "Models/LustifyEndgame",
}
SCHEDULERS = ("dpmpp-2m-karras", "dpmpp-2m-sde-karras")
DEFAULT_PROMPT = (
    "Photorealistic editorial portrait of an adult, natural skin texture, "
    "soft window light, detailed eyes, 85mm portrait lens, neutral background"
)


def load_worker_tools():
    spec = importlib.util.spec_from_file_location("benchmark_juggernaut", BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=tuple(MODEL_DIRS),
                        default=list(MODEL_DIRS), help="SDXL models to compare")
    parser.add_argument("--juggernaut-dir", type=Path, default=MODEL_DIRS["juggernaut-xl"])
    parser.add_argument("--lustify-dir", type=Path, default=MODEL_DIRS["lustify-endgame-sdxl"])
    parser.add_argument("--output-dir", type=Path,
                        default=Path.home() / ".config/mlx-web/benchmarks/sdxl-ab")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--cfg", type=float, default=3.5)
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    parser.add_argument("--scheduler", choices=SCHEDULERS, default="dpmpp-2m-sde-karras")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--image-url", default="http://127.0.0.1:8030")
    parser.add_argument("--skip-service-unload", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print a comparable run plan without requiring weights or GPU")
    args = parser.parse_args(argv)
    if not (0 <= args.seed <= 2**32 - 1):
        parser.error("--seed must be a uint32")
    if not (1 <= args.steps <= 50):
        parser.error("--steps must be between 1 and 50")
    if not (0 <= args.cfg <= 10):
        parser.error("--cfg must be between 0 and 10")
    if not (256 <= args.width <= 1216 and 256 <= args.height <= 1216):
        parser.error("SDXL benchmark dimensions must be 256..1216")
    if args.width % 16 or args.height % 16:
        parser.error("SDXL benchmark dimensions must be divisible by 16")
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not args.prompt.strip():
        parser.error("--prompt must not be blank")
    return args


def plan(args):
    dirs = {
        "juggernaut-xl": args.juggernaut_dir,
        "lustify-endgame-sdxl": args.lustify_dir,
    }
    return [
        {
            "model": model,
            "directory": str(dirs[model].expanduser()),
            "run": run,
            "filename": f"{model}-{args.scheduler}-seed{args.seed}-r{run}.png",
            "seed": args.seed,
            "steps": args.steps,
            "cfg": args.cfg,
            "width": args.width,
            "height": args.height,
            "scheduler": args.scheduler,
        }
        for run in range(1, args.repeats + 1)
        for model in dict.fromkeys(args.models)
    ]


def main(argv=None):
    args = parse_args(argv)
    jobs = plan(args)
    if args.dry_run:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return 0

    tools = load_worker_tools()
    # Resolve everything up-front so no benchmark begins with missing weights.
    sources = {}
    for item in jobs:
        model = item["model"]
        if model not in sources:
            sources[model] = tools.resolve_model_files(item["directory"])
    image_python = tools.resolve_image_python()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_service_unload:
        tools.request_json("POST", args.image_url.rstrip("/") + "/unload", timeout=60)

    results = []
    # Group sequentially by model, so a 48 GB Mac does not hold both SDXL
    # checkpoints resident simultaneously. Both runs still share the same settings.
    for model in dict.fromkeys(item["model"] for item in jobs):
        checkpoint, config = sources[model]
        worker = tools.Worker(image_python, checkpoint, config)
        warmup = output_dir / f".{model}-warmup.png"
        try:
            worker.run({
                "prompt": args.prompt, "negative_prompt": args.negative_prompt or None,
                "width": 512, "height": 512, "steps": 1,
                "guidance": args.cfg, "seed": args.seed,
                "scheduler": args.scheduler,
            }, warmup, args.timeout, show_progress=False)
            for item in jobs:
                if item["model"] != model:
                    continue
                output = output_dir / item["filename"]
                duration, event = worker.run({
                    "prompt": args.prompt, "negative_prompt": args.negative_prompt or None,
                    "width": args.width, "height": args.height,
                    "steps": args.steps, "guidance": args.cfg,
                    "seed": args.seed, "scheduler": args.scheduler,
                }, output, args.timeout)
                results.append({
                    **item,
                    "path": str(output),
                    "wall_seconds": round(duration, 3),
                    "sha256_png": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "reported_scheduler": event.get("scheduler"),
                })
                print(f"{model} r{item['run']}: {duration:.1f}s -> {output}", flush=True)
        finally:
            warmup.unlink(missing_ok=True)
            worker.close()

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "results": results,
        "note": "Same prompt/seed/settings for A/B; PNG hashes may differ across Apple GPU/runtime versions.",
    }
    manifest_path = output_dir / f"ab-{args.scheduler}-seed{args.seed}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"SDXL benchmark failed: {error}", file=sys.stderr)
        raise SystemExit(1)
