"""DiffusionKit worker, executed only by the existing native image service."""
import json
import sys


def main():
    import mlx.core as mx
    from diffusionkit.mlx import FluxPipeline
    request = json.load(sys.stdin)
    params = request["params"]
    pipeline = FluxPipeline(w16=True, a16=True, model_version=request["repository"], low_memory_mode=True)
    image, _ = pipeline.generate_image(
        params["prompt"], cfg_weight=params["guidance"], num_steps=params["steps"],
        seed=params["seed"], latent_size=(params["height"] // 8, params["width"] // 8),
    )
    image.save(request["output"])
    del pipeline
    if hasattr(mx, "clear_cache"):
        mx.clear_cache()


if __name__ == "__main__":
    main()
