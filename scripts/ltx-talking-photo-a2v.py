#!/usr/bin/env python3
"""Run one conservative LTX-2.5 MLX audio-to-video talking-photo job."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from importlib import metadata
from pathlib import Path
import sys


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
    value.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    value.add_argument("--cfg-scale", default=3.0, type=float)
    value.add_argument("--stg-scale", default=1.0, type=float)
    value.add_argument("--diagnostics", help="Retain effective parameters and actual audio-loader metrics")
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent.talking_photo_audio import validate_wav
    import numpy as np
    import ltx_pipelines_mlx.a2vid_two_stage as pipeline_module
    from ltx_pipelines_mlx.a2vid_two_stage import A2VidPipelineTwoStage

    diagnostics = {
        "conditioning_audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "conditioning_audio_stats": validate_wav(audio.read_bytes()),
        "audio_loads": [],
        "pipeline_source_sha256": hashlib.sha256(Path(pipeline_module.__file__).read_bytes()).hexdigest(),
        "constructor": {"model_dir": str(model), "gemma_model_id": str(model),
                        "low_memory": True, "low_ram_streaming": True},
    }
    diagnostics["versions"] = {}
    for package in ("mlx", "ltx-core-mlx", "ltx-pipelines-mlx", "numpy"):
        try:
            diagnostics["versions"][package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            diagnostics["versions"][package] = None
    diagnostics["python"] = sys.version
    diagnostics["model_config_sha256"] = hashlib.sha256(
        (model / "embedded_config.json").read_bytes()).hexdigest()
    def save_diagnostics():
        if args.diagnostics:
            Path(args.diagnostics).write_text(
                json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )

    # Observe the pipeline's actual loader, including the waveform entering the
    # audio encoder. This does not alter, normalize or retime its return value.
    original_load_audio = pipeline_module.load_audio
    def audited_load_audio(*load_args, **load_kwargs):
        loaded = original_load_audio(*load_args, **load_kwargs)
        if loaded is not None:
            samples = np.asarray(loaded.waveform, dtype=np.float32)
            diagnostics["audio_loads"].append({
                "path": str(load_args[0]), "options": load_kwargs,
                "sample_rate": loaded.sample_rate, "shape": list(samples.shape),
                "peak": float(np.max(np.abs(samples))),
                "rms": float(np.sqrt(np.mean(samples * samples))),
            })
            save_diagnostics()
        return loaded
    pipeline_module.load_audio = audited_load_audio

    pipe = A2VidPipelineTwoStage(
        model_dir=str(model),
        gemma_model_id=str(model),
        low_memory=True,
        low_ram_streaming=True,
    )
    pipe.verbose = False
    parameters = dict(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
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
        cfg_scale=args.cfg_scale,
        stg_scale=args.stg_scale,
        audio_start_time=0.0,
        audio_max_duration=args.frames / args.fps,
    )
    bound = inspect.signature(pipe.generate_and_save).bind(**parameters)
    bound.apply_defaults()
    diagnostics["parameters"] = dict(bound.arguments)
    save_diagnostics()
    try:
        pipe.generate_and_save(**parameters)
    finally:
        pipeline_module.load_audio = original_load_audio
    if not output.is_file():
        raise SystemExit("LTX A2V produced no output")


if __name__ == "__main__":
    main()
