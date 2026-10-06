import importlib.util
from pathlib import Path

import pytest

import image_registry
import quality_profiles
import sdxl_worker


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "scripts" / "benchmark-juggernaut.py"


def load_benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "benchmark_juggernaut",
        BENCHMARK,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sdxl_scheduler_default_is_existing_dpmpp_2m_karras():
    name, settings = sdxl_worker.scheduler_settings(None)

    assert name == "dpmpp-2m-karras"
    assert settings == {
        "algorithm_type": "dpmsolver++",
        "solver_order": 2,
        "use_karras_sigmas": True,
    }


def test_juggernaut_xi_production_defaults_match_validated_baseline():
    model = next(
        item
        for item in image_registry.builtin_models()
        if item["id"] == image_registry.JUGGERNAUT_XL_ID
    )
    standard = quality_profiles.resolve_image_profile(model, "standard")

    assert sdxl_worker.DEFAULT_SCHEDULER == "dpmpp-2m-karras"
    assert model["default_steps"] == 30
    assert model["default_guidance"] == 5.0
    assert standard["steps"] == 30
    assert standard["guidance"] == 5.0


def test_sdxl_scheduler_sde_preset_uses_sde_dpmsolver_plus_plus():
    name, settings = sdxl_worker.scheduler_settings(
        "dpmpp-2m-sde-karras"
    )

    assert name == "dpmpp-2m-sde-karras"
    assert settings == {
        "algorithm_type": "sde-dpmsolver++",
        "solver_order": 2,
        "use_karras_sigmas": True,
    }


def test_sdxl_scheduler_aliases_are_canonicalized():
    assert sdxl_worker.scheduler_settings("dpmpp_2m_karras")[0] == (
        "dpmpp-2m-karras"
    )
    assert sdxl_worker.scheduler_settings("dpmpp_2m_sde_karras")[0] == (
        "dpmpp-2m-sde-karras"
    )


def test_sdxl_scheduler_rejects_unknown_values():
    with pytest.raises(ValueError, match="Unsupported SDXL scheduler"):
        sdxl_worker.scheduler_settings("euler-a")


def test_juggernaut_benchmark_defaults_compare_only_scheduler():
    module = load_benchmark_module()

    assert module.DEFAULT_SCHEDULERS == (
        "dpmpp-2m-karras",
        "dpmpp-2m-sde-karras",
    )
    assert module.DEFAULT_MODEL_DIR == Path.home() / "Models/JuggernautXL"


def test_juggernaut_benchmark_resolves_single_checkpoint_and_config(tmp_path):
    module = load_benchmark_module()
    model_dir = tmp_path / "JuggernautXL"
    config = model_dir / "config"
    config.mkdir(parents=True)
    checkpoint = model_dir / "Juggernaut-XI-byRunDiffusion.safetensors"
    checkpoint.write_bytes(b"test")
    (config / "model_index.json").write_text("{}", encoding="utf-8")

    resolved_checkpoint, resolved_config = module.resolve_model_files(model_dir)

    assert resolved_checkpoint == checkpoint.resolve()
    assert resolved_config == config.resolve()


def test_juggernaut_benchmark_rejects_ambiguous_checkpoints(tmp_path):
    module = load_benchmark_module()
    model_dir = tmp_path / "JuggernautXL"
    config = model_dir / "config"
    config.mkdir(parents=True)
    (config / "model_index.json").write_text("{}", encoding="utf-8")
    (model_dir / "a.safetensors").write_bytes(b"a")
    (model_dir / "b.safetensors").write_bytes(b"b")

    with pytest.raises(RuntimeError, match="genau einen Juggernaut-Checkpoint"):
        module.resolve_model_files(model_dir)
