"""GPU child entrypoint. No MLX import until explicit approval and admission pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from fractions import Fraction
from pathlib import Path

from .compatibility import inspect_runtime, validate_environment
from .config import PROFILES, inside_lab
from .instrumentation import Instrumentation
from .quality import media_evidence, sha256
from .telemetry import MemorySampler, Recorder, preflight, write_json


def input_fingerprint(request):
    inputs = {name: request[name] for name in ("prompt", "seed", "width", "height", "frames", "fps",
                                               "stage1_steps", "stage2_steps", "pipeline")}
    for name in ("image", "audio"):
        inputs[name] = sha256(request[name]) if request.get(name) else None
    model = Path(request["model"])
    inputs["model_config"] = {name: sha256(model / name) for name in
                              ("embedded_config.json", "quantize_config.json")}
    if request["pipeline"] == "a2v-classic":
        inputs.update(negative_prompt=request["negative_prompt"], cfg_scale=3.0, stg_scale=1.0)
    # Revision identity without reading tens of GB: file sizes + mtimes, not a content proof.
    inputs["model_manifest"] = {path.name: {"bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
                                for path in sorted(model.glob("*.safetensors"))}
    return {"parameters": inputs,
            "sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()}


def validate_model(model):
    model = Path(model).expanduser().resolve()
    required = ("embedded_config.json", "quantize_config.json", "text_encoder_config.json",
                "text_encoder.safetensors", "connector.safetensors", "transformer-distilled.safetensors",
                "vae_decoder_conv.safetensors", "vae_encoder_conv.safetensors", "audio_vae.safetensors",
                "vocoder.safetensors", "spatial_upscaler_x2_v1_0.safetensors")
    missing = [name for name in required if not (model / name).is_file()]
    if missing:
        raise ValueError(f"Local model pack incomplete; downloads prohibited: {missing}")
    return model


def run(request):
    runtime = inside_lab(request["runtime"])
    output = inside_lab(request["output"])
    version, profile = request["version"], request["profile"]
    compatibility = inspect_runtime(runtime, version)
    if not compatibility["compatible"] or not compatibility["profiles"][profile]:
        raise ValueError("Runtime API/profile unsupported")
    environment = validate_environment(runtime, version)
    if Path(sys.prefix).resolve() != runtime / ".venv":
        raise ValueError("Child is not running in the isolated venv")
    wanted = PROFILES[profile]
    if os.environ.get("LTX2_COMPUTE_DTYPE") != wanted["dtype"] or os.environ.get("LTX2_SOL_TAU") != (
            "1.0,1.25,1.5" if wanted["sparse"] else "off"):
        raise ValueError("Child environment does not match recorded profile")
    model = validate_model(request["model"])
    if request["pipeline"] == "a2v-classic":
        for name in ("transformer-dev.safetensors", "ltx-2.5-22b-distilled-lora-450-bf16.safetensors"):
            if not (model / name).is_file():
                raise ValueError(f"Classic A2V model missing: {name}")
    fingerprint = input_fingerprint(request)
    admission = preflight(request["min_available_gib"])
    if not admission["allowed"]:
        raise RuntimeError(f"Resource admission refused: {admission['reasons']}")
    output.mkdir(parents=True, exist_ok=False)
    startup = time.perf_counter()
    import mlx.core as mx
    from ltx_pipelines_mlx.distilled import DistilledPipeline
    from ltx_pipelines_mlx.a2vid_distilled import A2VidDistilledPipeline
    from ltx_pipelines_mlx.a2vid_two_stage import A2VidPipelineTwoStage
    for module_name in ("ltx_pipelines_mlx.distilled", "ltx_pipelines_mlx.a2vid_distilled",
                        "ltx_pipelines_mlx.a2vid_two_stage"):
        if not Path(sys.modules[module_name].__file__).resolve().is_relative_to(runtime / "packages"):
            raise RuntimeError(f"Imported pipeline escaped isolated runtime: {module_name}")
    imports_seconds = time.perf_counter() - startup
    pipeline_type = {"t2v": DistilledPipeline, "i2v": DistilledPipeline,
                     "a2v-classic": A2VidPipelineTwoStage, "a2v-distilled": A2VidDistilledPipeline}[request["pipeline"]]
    construct_started = time.perf_counter()
    pipe = pipeline_type(model_dir=str(model), gemma_model_id=str(model),
                         low_memory=True, low_ram_streaming=True)
    pipe.verbose = False  # Prevent upstream VAE peak reset; recorder owns reset scope.
    pipe.video_decoder_block.verbose = False
    pipe.generate_audio = True
    pipeline_init_seconds = time.perf_counter() - construct_started
    results = []
    for index in range(request["runs"]):
        # Recheck before each warm job too; retain production services untouched.
        admission = preflight(request["min_available_gib"])
        if not admission["allowed"]:
            raise RuntimeError(f"Resource admission refused before run {index}: {admission['reasons']}")
        directory = output / f"run-{index:02d}"
        directory.mkdir()
        report = {"schema_version": 1, "status": "running", "version": version,
                  "profile": profile, "parameters": request, "input_fingerprint": fingerprint,
                  "environment": environment, "compatibility": {k: v for k, v in compatibility.items()
                                                                if k != "source_hashes"},
                  "admission": admission, "start": "cold_process" if index == 0 else "warm_process",
                  "weights_resident_between_runs": False, "import_seconds": imports_seconds if index == 0 else 0,
                  "pipeline_init_seconds": pipeline_init_seconds if index == 0 else 0,
                  "role": request.get("first_run_role", "measurement") if index == 0 else "measurement",
                  "measurement": "instrumented; extra synchronization; compare only like-for-like"}
        rec = Recorder(mx)
        mx.synchronize()
        mx.reset_peak_memory()
        began = time.perf_counter()
        try:
            with MemorySampler() as memory:
                rec.guard = memory.check
                with Instrumentation(rec) as instrumentation:
                    instrumentation.install(pipe)
                    args = dict(prompt=request["prompt"], output_path=str(directory / "video.mp4"),
                                width=request["width"], height=request["height"], num_frames=request["frames"],
                                frame_rate=request["fps"], seed=request["seed"],
                                stage1_steps=request["stage1_steps"], stage2_steps=request["stage2_steps"],
                                image=request.get("image"))
                    if request["pipeline"].startswith("a2v"):
                        args["audio_path"] = request["audio"]
                    if request["pipeline"] == "a2v-classic":
                        args.update(cfg_scale=3.0, stg_scale=1.0, negative_prompt=request["negative_prompt"])
                    with rec.span("generation"):
                        pipe.generate_and_save(**args)
                mx.synchronize()
            report["generation_wall_seconds"] = time.perf_counter() - began
            report["memory"] = memory.summary()
            report["memory_samples"] = memory.samples
            report["telemetry"] = rec.report(memory.samples)
            memory.check()
            report["artifacts"] = media_evidence(directory / "video.mp4", directory)
            video = next(s for s in report["artifacts"]["probe"]["streams"] if s["codec_type"] == "video")
            if (int(video["width"]), int(video["height"]), int(video["nb_read_frames"])) != (
                    request["width"], request["height"], request["frames"]):
                raise RuntimeError("Generated video geometry/frame count differs from requested input")
            if abs(float(Fraction(video["avg_frame_rate"])) - request["fps"]) > 1e-6:
                raise RuntimeError("Generated video FPS differs from request")
            required_phases = ("model_loading", "text_encoding", "denoising_stage_1", "denoising_stage_2",
                               "vae_decoding", "audio_processing", "mux_session")
            missing = set(required_phases) - report["telemetry"]["phases"].keys()
            if missing:
                raise RuntimeError(f"Missing phase measurements: {sorted(missing)}")
            if wanted["sparse"] and not rec.effective["sparse_attention_calls"]:
                raise RuntimeError("Sparse profile fell back to dense attention; not a valid sparse measurement")
            for effective in rec.effective["dit_compute"]:
                if wanted["dtype"] != "float32" and wanted["dtype"] not in effective["dtype"]:
                    raise RuntimeError("Compute dtype fallback detected; profile measurement invalid")
            expected_steps = {1: request["stage1_steps"], 2: request["stage2_steps"]}
            for stage, expected in expected_steps.items():
                if len([s for s in rec.steps if s["stage"] == stage]) != expected:
                    raise RuntimeError(f"Missing completed step measurements for stage {stage}")
            report["status"] = "completed"
        except BaseException as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}", telemetry=rec.report())
            if "memory" in locals() and memory.samples:
                report["memory"] = memory.summary()
                report["memory_samples"] = memory.samples
            raise
        finally:
            write_json(directory / "result.json", report)
            results.append(str(directory / "result.json"))
            write_json(output / "results.json", {"runs": results})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--approve-gpu", action="store_true")
    args = parser.parse_args()
    if not args.approve_gpu:
        parser.error("Explicit --approve-gpu required; no MLX import performed")
    request_file = inside_lab(args.request_file)
    run(json.loads(request_file.read_text()))


if __name__ == "__main__":
    main()
