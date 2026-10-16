#!/usr/bin/env python3
"""Memory-safe, blinded Lustify vs Juggernaut comparison via image service.

Unlike benchmark-sdxl-models.py, this tool NEVER starts a standalone SDXL
worker. All jobs run through the guarded MLX Nobby /generate endpoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import random
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MODELS = ("juggernaut-xl", "lustify-endgame-sdxl")
DEFAULT_SCENES = (
    (
        "portrait",
        "Photorealistic editorial head-and-shoulders portrait of a 35-year-old "
        "adult woman, authentic natural skin texture and pores, realistic eyes, "
        "subtle asymmetry, natural hair, daylight through a window, 85mm lens, "
        "soft background, unretouched professional photography.",
    ),
    (
        "full-body",
        "Full-body natural-light fashion photograph of an adult man standing "
        "on a cobblestone street, head to toe in frame, hands clearly visible, "
        "realistic fingers, accurate anatomy and proportions, layered clothing "
        "with detailed fabric textures, candid pose, 50mm lens.",
    ),
    (
        "interior",
        "Photorealistic cozy contemporary living room in warm morning sunlight, "
        "oak furniture, linen sofa, plants, books, ceramic vases, physically "
        "plausible shadows and reflections, clean architectural composition, "
        "fine realistic material details, 35mm interior photograph.",
    ),
    (
        "action",
        "Photorealistic editorial sports photograph of an adult tennis player "
        "mid-stride reaching for a ball with one hand and holding a tennis "
        "racket with the other, dynamic but physically plausible anatomy, "
        "hands in focus, natural skin, motion frozen by fast shutter, "
        "real outdoor court and daylight.",
    ),
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=512,
                        help="Square SDXL image size; begin with 512 for safety")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=3.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prompt", action="append", default=[],
                        help="Use custom prompt(s) instead of the four default motifs")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--image-url", default="http://127.0.0.1:8030")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reveal", type=Path,
                        help="Display the secret model mapping for an earlier run")
    args = parser.parse_args(argv)
    if args.size not in (512, 640, 768, 896, 1024):
        parser.error("--size must be 512, 640, 768, 896 or 1024")
    if not 1 <= args.steps <= 50:
        parser.error("--steps must be 1..50")
    if not 0 <= args.cfg <= 10:
        parser.error("--cfg must be 0..10")
    if not 0 <= args.seed <= 2**32 - len(DEFAULT_SCENES):
        parser.error("--seed is outside the supported uint32 range")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if any(not prompt.strip() for prompt in args.prompt):
        parser.error("--prompt must not be blank")
    url = urlsplit(args.image_url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--image-url must be a local http image service")
    return args


def build_plan(args):
    scenes = (
        tuple((f"custom-{i}", prompt) for i, prompt in enumerate(args.prompt, 1))
        if args.prompt else DEFAULT_SCENES
    )
    jobs = []
    for index, (scene, prompt) in enumerate(scenes):
        order = list(MODELS)
        random.Random(args.seed + index).shuffle(order)
        for label, model in zip(("A", "B"), order):
            jobs.append({
                "scene": scene,
                "prompt": prompt,
                "seed": args.seed + index,
                "label": label,
                "model": model,
                "width": args.size,
                "height": args.size,
                "steps": args.steps,
                "guidance": args.cfg,
                "filename": f"{scene}-{label}.png",
            })
    return jobs


def request_image(base_url, payload, timeout):
    request = Request(
        base_url.rstrip("/") + "/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Image-Service HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Image-Service nicht erreichbar: {exc.reason}") from exc


def make_sheet(jobs, directory):
    # Pillow is a dependency of the existing image-venv.
    from PIL import Image, ImageDraw, ImageOps

    scenes = list(dict.fromkeys(item["scene"] for item in jobs))
    tile = 512
    padding = 20
    header = 60
    row_height = tile + 56
    width = 2 * tile + 3 * padding
    height = header + len(scenes) * row_height + padding
    sheet = Image.new("RGB", (width, height), (247, 247, 247))
    draw = ImageDraw.Draw(sheet)
    draw.text((padding, 16), "Blind comparison — rate A and B before revealing models",
              fill=(20, 20, 20))

    for i, scene in enumerate(scenes):
        top = header + i * row_height
        for column, label in enumerate(("A", "B")):
            item = next(x for x in jobs if x["scene"] == scene and x["label"] == label)
            left = padding + column * (tile + padding)
            draw.text((left, top), f"{scene} — {label}", fill=(10, 10, 10))
            with Image.open(directory / item["filename"]) as opened:
                img = ImageOps.contain(opened.convert("RGB"), (tile, tile))
            sheet.paste(img, (left + (tile - img.width) // 2, top + 28))
    output = directory / "blindvergleich.jpg"
    sheet.save(output, quality=92)
    return output


def main(argv=None):
    args = parse_args(argv)
    if args.reveal:
        data = json.loads((args.reveal.expanduser() / "aufloesung.json").read_text(encoding="utf-8"))
        for job in data["jobs"]:
            print(f"{job['scene']}: {job['label']} = {job['model']}")
        return 0

    jobs = build_plan(args)
    if args.dry_run:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        return 0

    root = (
        args.output_dir.expanduser()
        if args.output_dir
        else Path.home() / ".config/mlx-web/benchmarks/sdxl-blind"
    )
    directory = root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True, exist_ok=False)
    # Only the mapping file reveals model identity. Do not inspect it until
    # after visually comparing A and B.
    mapping = {
        "generated": datetime.now().isoformat(),
        "jobs": [
            {key: item[key] for key in ("scene", "label", "model", "seed")}
            for item in jobs
        ],
    }
    (directory / "aufloesung.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    timings = []
    print("Sicherer SDXL-API-Vergleich: keine separaten Modell-Worker.", flush=True)
    print(f"Ergebnisse: {directory}", flush=True)
    print(f"{len(jobs)} Jobs, sequenziell; Abbruch bei Speicherdruck erfolgt im Bilddienst.", flush=True)
    try:
        for index, job in enumerate(jobs, 1):
            print(f"[{index}/{len(jobs)}] {job['scene']} — {job['label']}", flush=True)
            payload = {
                "model": job["model"], "prompt": job["prompt"],
                "negative_prompt": args.negative_prompt or None,
                "width": job["width"], "height": job["height"],
                "steps": job["steps"], "guidance": job["guidance"],
                "seed": job["seed"], "auto_size": False,
            }
            started = time.monotonic()
            result = request_image(args.image_url, payload, args.timeout)
            image = Path(result["path"])
            if not image.is_file() or image.suffix.lower() != ".png":
                raise RuntimeError(f"Image-Service hat kein PNG erzeugt: {image}")
            shutil.copyfile(image, directory / job["filename"])
            timings.append({
                "scene": job["scene"], "label": job["label"],
                "seconds": round(time.monotonic() - started, 2),
            })
    except (KeyboardInterrupt, RuntimeError, KeyError, OSError, ValueError) as exc:
        print(f"Abbruch: {exc}. Bereits generierte Bilder liegen unter {directory}", file=sys.stderr)
        return 1

    (directory / "laufzeiten.json").write_text(
        json.dumps(timings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sheet = make_sheet(jobs, directory)
    print(f"Bildübersicht: {sheet}")
    print(f"Nach deiner Bewertung auflösen mit:\n  "
          f"{sys.executable} scripts/compare-sdxl-safe.py --reveal '{directory}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
