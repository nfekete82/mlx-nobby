import argparse
import json
from pathlib import Path

import torch
import ltx2_server
from services.ltx_pipeline_common import (
    encode_video_output,
    video_chunks_number,
)


DEFAULT_WIDTH = 384
DEFAULT_HEIGHT = 256
DEFAULT_FRAMES = 17
DEFAULT_FPS = 8


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    handler = ltx2_server.handler
    settings = handler.state.app_settings

    settings.use_local_text_encoder = True
    settings.user_prefers_ltx_api_video_generations = False
    settings.prompt_enhancer_enabled_t2v = False
    settings.prompt_enhancer_enabled_i2v = False
    settings.active_ltx_model_id = "ltx-2.5-22b-distilled"
    settings.use_conv_vae = True

    state = handler.pipelines.load_gpu_pipeline("fast")
    core = state.pipeline.pipeline

    handler.text.prepare_text_encoding(
        args.prompt,
        enhance_prompt=False,
    )

    stage_1_sigmas = torch.tensor(
        [1.0, 0.0],
        dtype=torch.float32,
    )

    stage_2_sigmas = torch.tensor(
        [0.909375, 0.0],
        dtype=torch.float32,
    )

    core.audio_decoder = lambda latent: None

    with torch.inference_mode():
        result = core(
            prompt=args.prompt,
            seed=args.seed,
            height=args.height,
            width=args.width,
            num_frames=args.frames,
            frame_rate=args.fps,
            images=[],
            stage_1_sigmas=stage_1_sigmas,
            stage_2_sigmas=stage_2_sigmas,
        )

    video, _audio, resolved_frames, resolved_tiling = result

    with torch.inference_mode():
        encode_video_output(
            video=video,
            audio=None,
            fps=args.fps,
            output_path=str(output),
            video_chunks_number_value=video_chunks_number(
                resolved_frames,
                resolved_tiling,
            ),
        )

    if not output.is_file():
        raise RuntimeError("Preview-Ausgabe wurde nicht erzeugt")

    print(json.dumps({
        "ok": True,
        "width": args.width,
        "height": args.height,
        "frames": args.frames,
        "fps": args.fps,
        "audio": False,
        "stage_1_steps": 1,
        "stage_2_steps": 1,
        "output": str(output),
    }))


if __name__ == "__main__":
    main()
