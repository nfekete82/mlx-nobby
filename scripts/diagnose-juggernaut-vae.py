#!/usr/bin/env python3
"""Safe reproducible Juggernaut VAE A/B through MLX-Nobby's guarded image API.

The only changed variable is VAE tiling/slicing. CPU offloading, MPS allocator
cap, active unified-memory watchdog and chat lease always stay active.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PROMPT = (
    "Photorealistic full-body editorial photograph of an adult athletic woman "
    "standing naturally on a sunlit city sidewalk, fully visible head to toe, "
    "wearing a tailored linen jacket, jeans and sneakers, relaxed asymmetric "
    "posture, both hands visible with anatomically correct fingers, realistic "
    "legs and body proportions, unretouched textured skin, natural facial "
    "features, realistic light and shadows, 50mm photograph, high detail"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default="distorted anatomy, extra limbs, extra fingers, malformed hands, blurry")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--cfg", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=24680)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.prompt.strip():
        parser.error("Prompt darf nicht leer sein")
    if (args.width % 16 or args.height % 16 or
        min(args.width, args.height) < 256 or max(args.width, args.height) > 1216):
        parser.error("SDXL width/height must be multiples of 16 in range 256..1216")
    if not 1 <= args.steps <= 50 or not 0 <= args.cfg <= 10:
        parser.error("Invalid steps or guidance")
    if not 0 <= args.seed <= 2**32-1:
        parser.error("Seed outside uint32")
    return args


def get_json(method, path, data=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(
        "http://127.0.0.1:8030" + path,
        data=body,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urlopen(request, timeout=1200 if method == "POST" else 8) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read(1400).decode('utf-8', 'replace')}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Bilddienst nicht erreichbar: {exc}") from exc


def assert_idle():
    health = get_json("GET", "/health")
    if not health.get("ok") or health.get("active_generation") or health.get("active_job_id"):
        raise RuntimeError("Bilddienst ist beschäftigt: erst laufende Bildaufträge abschließen")
    if "juggernaut-xl" not in (health.get("models") or []):
        raise RuntimeError("Juggernaut XL ist nicht aktiviert")
    return health


def save_image(image_path, destination):
    # The service returns its own local path; only read under managed images.
    root = (Path.home() / ".config/mlx-web/images").resolve()
    image = Path(image_path).expanduser().resolve()
    if image.suffix.lower() != ".png" or not image.is_relative_to(root) or not image.is_file():
        raise RuntimeError("Bilddienst meldete keinen sicheren lokalen PNG-Pfad")
    shutil.copyfile(image, destination)
    from PIL import Image
    with Image.open(destination) as opened:
        opened.verify()


def make_sheet(root):
    from PIL import Image, ImageDraw, ImageOps
    tile_width, tile_height = 768, 1024
    sheet = Image.new("RGB", (tile_width * 2 + 60, tile_height + 80), "#f4f4f4")
    draw = ImageDraw.Draw(sheet)
    for i, (filename, label) in enumerate((
        ("A-vae-optimiert.png", "A: current VAE optimizations"),
        ("B-vae-ohne-optimierungen.png", "B: tiling/slicing disabled"),
    )):
        left = 20 + i * (tile_width + 20)
        draw.text((left, 20), label, fill="#171717")
        with Image.open(root / filename) as handle:
            img = ImageOps.contain(handle.convert("RGB"), (tile_width, tile_height))
        sheet.paste(img, (left + (tile_width - img.width)//2, 54))
    output = root / "VAE-vergleich.jpg"
    sheet.save(output, quality=92)
    return output


def main(argv=None):
    args = parse_args(argv)
    payload = {
        "model": "juggernaut-xl",
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "width": args.width, "height": args.height,
        "auto_size": False, "steps": args.steps,
        "guidance": args.cfg, "seed": args.seed,
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    try:
        assert_idle()
        root = (args.output_dir or
                Path.home() / ".config/mlx-web/benchmarks/juggernaut-vae").expanduser() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        root.mkdir(parents=True, exist_ok=False)
        outputs = []
        for mode, filename in (
            ("optimized", "A-vae-optimiert.png"),
            ("disabled", "B-vae-ohne-optimierungen.png"),
        ):
            assert_idle()
            print(f"Generiere {mode}: {args.width}x{args.height}, {args.steps} Steps, CFG {args.cfg}, Seed {args.seed}", flush=True)
            response = get_json("POST", "/generate", {**payload, "sdxl_vae_mode": mode})
            save_image(response["path"], root / filename)
            outputs.append({"mode": mode, "filename": filename, "image_id": response.get("id")})
            print(f"  Gespeichert: {root / filename}", flush=True)
        (root / "settings.json").write_text(
            json.dumps({"payload": payload, "outputs": outputs}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        sheet = make_sheet(root)
        print(f"Vergleich fertig: {sheet}", flush=True)
        return 0
    except (RuntimeError, KeyError, ValueError, OSError) as exc:
        print(f"Abgebrochen: {exc}", file=sys.stderr)
        print("VAE-Optimierungen bleiben für normale Bildaufträge aktiviert.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
