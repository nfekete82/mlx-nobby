"""Inspect upstream contracts with AST, without importing MLX or loading weights."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from .config import COMMITS, PROFILES, inside_lab


def git(runtime, *args):
    return subprocess.check_output(["git", "-C", str(runtime), *args], text=True).strip()


def inspect_runtime(runtime, version):
    runtime = Path(runtime).resolve()
    core = runtime / "packages/ltx-core-mlx/src/ltx_core_mlx"
    pipelines = runtime / "packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx"
    classes, functions, sources = {}, {}, {}
    for path in [*core.rglob("*.py"), *pipelines.rglob("*.py")]:
        source = path.read_text()
        sources[str(path.relative_to(runtime))] = source
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault(node.name, []).append(node)

    def method(class_name, name, seen=()):
        if class_name in seen or class_name not in classes:
            return None
        node = classes[class_name]
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == name:
                return child
        for base in node.bases:
            if isinstance(base, ast.Name):
                found = method(base.id, name, (*seen, class_name))
                if found:
                    return found
        return None

    def accepts(node, names):
        if node is None:
            return False
        args = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        return set(names) <= args

    constructor = ("model_dir", "gemma_model_id", "low_memory", "low_ram_streaming")
    generate = ("prompt", "output_path", "height", "width", "num_frames", "frame_rate",
                "seed", "stage1_steps", "stage2_steps", "image")
    checks = {}
    for name in ("DistilledPipeline", "A2VidDistilledPipeline", "A2VidPipelineTwoStage"):
        checks[f"{name}.constructor"] = accepts(method(name, "__init__"), constructor)
        extra = ("audio_path",) if name != "DistilledPipeline" else ()
        checks[f"{name}.generate"] = accepts(method(name, "generate_and_save"), (*generate, *extra))
        checks[f"{name}.progress"] = accepts(method(name, "_stepwise_hook"), ("stage",))
    checks["classic_guidance"] = accepts(method("A2VidPipelineTwoStage", "generate_and_save"),
                                         ("negative_prompt", "cfg_scale", "stg_scale"))
    for name, meth in (("PromptEncoder", "load"), ("PromptEncoder", "encode"),
                       ("AudioDecoder", "__call__"), ("VideoDecoder", "decode_and_stream")):
        checks[f"instrument.{name}.{meth}"] = method(name, meth) is not None
    for name in ("_step_timed", "euler_ancestral_denoising_loop", "guided_denoise_loop",
                 "denoise_loop", "_ffmpeg_sink", "stream_chunks_to_ffmpeg"):
        checks[f"instrument.{name}"] = name in functions
    model_source = (core / "model/transformer/model.py").read_text()
    sparse_source = (core / "model/transformer/sparse_attention.py").read_text()
    distilled_source = (pipelines / "distilled.py").read_text()
    vae_tree = ast.parse((core / "model/video_vae/video_vae.py").read_text())
    vae_classes = {node.name: node for node in vae_tree.body if isinstance(node, ast.ClassDef)}
    for cls, names in {"VideoDecoder": ("tiled_decode",), "VideoEncoder": ("encode",),
                       "_OrderedFrameWriter": ("submit", "finish", "shutdown")}.items():
        declared = {node.name for node in vae_classes[cls].body if isinstance(node, ast.FunctionDef)}
        for name in names:
            checks[f"instrument.core.{cls}.{name}"] = name in declared
    compute = "LTX2_COMPUTE_DTYPE" in model_source and all(
        f'"{dtype}"' in model_source for dtype in ("float16", "bfloat16", "float32"))
    sparse = "LTX2_SOL_TAU" in sparse_source and "_start_stage2_sparse_attention" in distilled_source
    actual = git(runtime, "rev-parse", "HEAD")
    checks["pinned_commit"] = actual == COMMITS[version]
    checks["clean_checkout"] = not git(runtime, "status", "--porcelain", "--untracked-files=no")
    return {
        "version": version, "commit": actual, "runtime": str(runtime),
        "checks": checks, "compatible": all(checks.values()),
        "features": {"compute_dtype": compute, "sparse_stage2": sparse,
                     "stage1_resume": "return_stage1" in distilled_source},
        "profiles": {name: compute and (not p["sparse"] or sparse) for name, p in PROFILES.items()},
        "profiles_by_pipeline": {
            pipeline: {name: compute and (not p["sparse"] or (sparse and pipeline != "a2v-classic"))
                       for name, p in PROFILES.items()}
            for pipeline in ("t2v", "i2v", "a2v-distilled", "a2v-classic")},
        "source_hashes": {name: hashlib.sha256(source.encode()).hexdigest()
                          for name, source in sources.items()},
        "validation_level": "static AST; no GPU import or inference; render parity still pending",
    }


def validate_environment(runtime, version):
    """Read installed metadata in the target interpreter, never import MLX."""
    runtime = inside_lab(runtime)
    code = """
import importlib.metadata as m, json, sys
names = ['ltx-core-mlx','ltx-pipelines-mlx','mlx','mlx-metal','mlx-lm',
         'mlx-arsenal','transformers','numpy','safetensors','huggingface-hub','pillow','tqdm']
out = {'python': sys.version, 'executable': sys.executable, 'prefix': sys.prefix,
       'packages': {n: m.version(n) for n in names}, 'editable': {}}
for name in names[:2]:
    out['editable'][name] = json.loads(m.distribution(name).read_text('direct_url.json') or '{}')
print(json.dumps(out))
"""
    result = json.loads(subprocess.check_output(
        [str(runtime / ".venv/bin/python"), "-B", "-I", "-c", code], text=True))
    if Path(result["prefix"]).resolve() != runtime / ".venv":
        raise ValueError("Unexpected virtual environment prefix")
    for name in ("ltx-core-mlx", "ltx-pipelines-mlx"):
        if result["packages"][name] != version:
            raise ValueError(f"Unexpected package version: {name}")
        url = result["editable"][name].get("url", "")
        if not url.startswith(runtime.as_uri() + "/packages/"):
            raise ValueError(f"Editable package points outside test runtime: {name}")
    return result
