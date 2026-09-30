"""Persistent offline SDXL worker for the native image service."""
import gc
import json
import sys


DEFAULT_SCHEDULER = "dpmpp-2m-karras"
SCHEDULER_PRESETS = {
    "dpmpp-2m-karras": {
        "algorithm_type": "dpmsolver++",
        "solver_order": 2,
        "use_karras_sigmas": True,
    },
    "dpmpp-2m-sde-karras": {
        "algorithm_type": "sde-dpmsolver++",
        "solver_order": 2,
        "use_karras_sigmas": True,
    },
}
SCHEDULER_ALIASES = {
    "dpmpp_2m_karras": "dpmpp-2m-karras",
    "dpmpp-2m": "dpmpp-2m-karras",
    "dpmpp_2m_sde_karras": "dpmpp-2m-sde-karras",
    "dpmpp-2m-sde": "dpmpp-2m-sde-karras",
}


def scheduler_settings(value=None):
    """Return one canonical, explicitly supported SDXL scheduler preset."""
    scheduler = str(value or DEFAULT_SCHEDULER).strip().lower()
    scheduler = SCHEDULER_ALIASES.get(scheduler, scheduler)
    if scheduler not in SCHEDULER_PRESETS:
        supported = ", ".join(SCHEDULER_PRESETS)
        raise ValueError(
            f"Unsupported SDXL scheduler '{scheduler}'. Supported: {supported}"
        )
    return scheduler, dict(SCHEDULER_PRESETS[scheduler])


def main():
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

    if not torch.backends.mps.is_available():
        raise RuntimeError("SDXL requires an available PyTorch MPS device")

    pipeline = None
    loaded_model = None
    loaded_scheduler = None
    scheduler_base_config = None

    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["request_id"]
            params = request["params"]
            model_key = (request["checkpoint"], request["config"])
            if pipeline is None or loaded_model != model_key:
                if pipeline is not None:
                    del pipeline
                    pipeline = None
                    gc.collect()
                    torch.mps.empty_cache()
                pipeline = StableDiffusionXLPipeline.from_single_file(
                    request["checkpoint"],
                    config=request["config"],
                    dtype=torch.float16,
                    local_files_only=True,
                    use_safetensors=True,
                )
                scheduler_base_config = pipeline.scheduler.config
                pipeline = pipeline.to("mps")
                loaded_model = model_key
                loaded_scheduler = None

            scheduler_name, scheduler_kwargs = scheduler_settings(
                params.get("scheduler")
            )
            if loaded_scheduler != scheduler_name:
                pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
                    scheduler_base_config,
                    **scheduler_kwargs,
                )
                loaded_scheduler = scheduler_name

            generator = torch.Generator(device="cpu").manual_seed(params["seed"])

            def report_step(_pipeline, step, _timestep, callback_kwargs):
                print(json.dumps({
                    "type": "runtime",
                    "request_id": request_id,
                    "phase": "generate",
                    "step": step + 1,
                    "total_steps": params["steps"],
                    "scheduler": scheduler_name,
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
            del result
            print(json.dumps({
                "type": "complete",
                "request_id": request_id,
                "scheduler": scheduler_name,
            }), flush=True)
        except Exception as exc:
            message = str(exc).replace("\n", " ").replace("\r", " ").strip()
            if len(message) > 1500:
                message = message[:1500] + "..."

            print(json.dumps({
                "type": "error",
                "request_id": request_id,
                "error_type": type(exc).__name__,
                "message": message,
            }), flush=True)


if __name__ == "__main__":
    main()
