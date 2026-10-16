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


def configure_vae_memory_saving(pipeline, *, enabled=True):
    """Toggle only VAE tiling/slicing, never CPU-offloading or MPS limits.

    Disabled mode is a diagnostic comparison, not a faster or safer default.
    Fail instead of silently retaining optimization state if an older wrapper
    cannot disable an already-enabled VAE optimization.
    """
    vae = getattr(pipeline, "vae", None)
    methods = (
        ("enable_tiling", "enable_slicing")
        if enabled else ("disable_tiling", "disable_slicing")
    )
    for method_name in methods:
        method = getattr(vae, method_name, None)
        if callable(method):
            method()
        elif not enabled:
            attribute = ("use_tiling" if "tiling" in method_name else "use_slicing")
            if getattr(vae, attribute, False):
                raise RuntimeError(
                    f"VAE-Diagnosemodus: {method_name} fehlt; sicherer Vergleich nicht möglich"
                )


def main():
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

    if not torch.backends.mps.is_available():
        raise RuntimeError("SDXL requires an available PyTorch MPS device")

    pipeline = None
    loaded_model = None
    loaded_scheduler = None
    loaded_vae_mode = None
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
                # Keep pipeline components on CPU until needed. Copying all
                # SDXL weights to MPS at once can exceed the safe allocator
                # cap on 48 GiB unified-memory Macs even at 512x512.
                #
                # Diffusers/Accelerate loads one component at a time; do not
                # combine this with enable_attention_slicing() on MPS, which
                # can produce black SDXL images in some versions.
                try:
                    pipeline.enable_model_cpu_offload(device="mps")
                except (AttributeError, ImportError, RuntimeError) as exc:
                    raise RuntimeError(
                        "Sicherer SDXL-Modus erfordert Diffusers mit "
                        "Accelerate CPU-Offloading auf MPS; "
                        "kein unsicherer Fallback auf pipeline.to('mps')"
                    ) from exc
                loaded_model = model_key
                loaded_scheduler = None
                loaded_vae_mode = None

            scheduler_name, scheduler_kwargs = scheduler_settings(
                params.get("scheduler")
            )
            if loaded_scheduler != scheduler_name:
                pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
                    scheduler_base_config,
                    **scheduler_kwargs,
                )
                loaded_scheduler = scheduler_name

            # Prewarm loads the exact production pipeline and scheduler into
            # the persistent worker without spending any denoising/decoding
            # work or creating an artifact.
            if request.get("operation") == "prewarm":
                print(json.dumps({
                    "type": "complete",
                    "request_id": request_id,
                    "operation": "prewarm",
                    "scheduler": scheduler_name,
                }), flush=True)
                continue

            vae_mode = params.get("sdxl_vae_mode") or "optimized"
            if vae_mode not in ("optimized", "disabled"):
                raise ValueError("Invalid SDXL VAE diagnostic mode")
            if loaded_vae_mode != vae_mode:
                configure_vae_memory_saving(pipeline, enabled=(vae_mode == "optimized"))
                loaded_vae_mode = vae_mode

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
            # PyTorch's stock MPS OOM suggestion is to disable the hard
            # watermark. Never recommend doing so in a safety-focused UI.
            if "MPS backend out of memory" in message:
                message = (
                    "Sicheres MPS-Speicherlimit erreicht; Bildauftrag beendet. "
                    "Watermark nicht deaktivieren. " +
                    message.split("Use PYTORCH_MPS_HIGH_WATERMARK_RATIO")[0].strip()
                )
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
