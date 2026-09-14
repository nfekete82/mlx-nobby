"""Offline SDXL worker, executed only by the existing native image service."""
import json
import sys


def main():
    import torch
    from diffusers import StableDiffusionXLPipeline

    if not torch.backends.mps.is_available():
        raise RuntimeError("SDXL requires an available PyTorch MPS device")

    request = json.load(sys.stdin)
    params = request["params"]
    pipeline = StableDiffusionXLPipeline.from_single_file(
        request["checkpoint"],
        config=request["config"],
        dtype=torch.float16,
        local_files_only=True,
        use_safetensors=True,
    ).to("mps")
    generator = torch.Generator(device="cpu").manual_seed(params["seed"])

    def report_step(_pipeline, step, _timestep, callback_kwargs):
        print(json.dumps({
            "type": "runtime",
            "phase": "generate",
            "step": step + 1,
            "total_steps": params["steps"],
        }), flush=True)
        return callback_kwargs

    result = pipeline(
        prompt=params["prompt"],
        negative_prompt=params.get("negative_prompt") or None,
        width=params["width"],
        height=params["height"],
        num_inference_steps=params["steps"],
        guidance_scale=params["guidance"],
        generator=generator,
        callback_on_step_end=report_step,
        callback_on_step_end_tensor_inputs=[],
    )
    result.images[0].save(request["output"], format="PNG")


if __name__ == "__main__":
    main()
