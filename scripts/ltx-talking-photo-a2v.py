#!/usr/bin/env python3
"""Run one conservative LTX-2.5 MLX audio-to-video talking-photo job."""

from __future__ import annotations

import argparse
from pathlib import Path

from ltx_pipelines_mlx.a2vid_two_stage import A2VidPipelineTwoStage


DEFAULT_NEGATIVE_PROMPT = (
    "deformed mouth, warped lips, extra teeth, duplicated teeth, unstable teeth, "
    "distorted face, identity drift, exaggerated mouth opening, rubbery face, "
    "flicker, jitter, camera movement, zoom, scene change, extra people"
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--model", required=True)
    value.add_argument("--image", required=True)
    value.add_argument("--audio", required=True)
    value.add_argument("--output", required=True)
    value.add_argument("--prompt", required=True)
    value.add_argument("--width", required=True, type=int)
    value.add_argument("--height", required=True, type=int)
    value.add_argument("--frames", required=True, type=int)
    value.add_argument("--fps", default=24.0, type=float)
    value.add_argument("--seed", default=42, type=int)
    value.add_argument("--stage1-steps", default=15, type=int)
    value.add_argument("--stage2-steps", default=3, type=int)
    return value


def main() -> None:
    args = parser().parse_args()
    model = Path(args.model).expanduser().resolve()
    image = Path(args.image).expanduser().resolve()
    audio = Path(args.audio).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not model.is_dir():
        raise SystemExit(f"Model directory missing: {model}")
    if not image.is_file():
        raise SystemExit(f"Reference image missing: {image}")
    if not audio.is_file():
        raise SystemExit(f"Reference audio missing: {audio}")
    output.parent.mkdir(parents=True, exist_ok=True)

    pipe = A2VidPipelineTwoStage(
        model_dir=str(model),
        gemma_model_id=str(model),
        low_memory=True,
        low_ram_streaming=True,
    )
    pipe.verbose = False
    pipe.generate_and_save(
        prompt=args.prompt,
        negative_prompt=DEFAULT_NEGATIVE_PROMPT,
        output_path=str(output),
        audio_path=str(audio),
        image=str(image),
        width=args.width,
        height=args.height,
        num_frames=args.frames,
        frame_rate=args.fps,
        seed=args.seed,
        stage1_steps=args.stage1_steps,
        stage2_steps=args.stage2_steps,
        cfg_scale=3.0,
        stg_scale=1.0,
    )
    if not output.is_file():
        raise SystemExit("LTX A2V produced no output")


if __name__ == "__main__":
    main()
