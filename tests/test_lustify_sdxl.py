"""Lustify Endgame SDXL registration, migration, routing and comparison contracts."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import image_providers as providers
import image_registry as registry
from quality_profiles import resolve_image_profile
import image_service as service


ROOT = Path(__file__).resolve().parents[1]


def test_lustify_is_a_separate_disabled_builtin_with_correct_defaults():
    builtins = {item["id"]: item for item in registry.builtin_models()}
    assert registry.LUSTIFY_ENDGAME_ID == "lustify-endgame-sdxl"
    assert registry.JUGGERNAUT_XL_ID == "juggernaut-xl"
    assert registry.LUSTIFY_ENDGAME_ID != registry.JUGGERNAUT_XL_ID
    lustify = builtins[registry.LUSTIFY_ENDGAME_ID]
    ragnarok = builtins[registry.JUGGERNAUT_XL_ID]
    assert lustify["name"] == "Lustify Endgame (SDXL)"
    assert lustify["provider"] == ragnarok["provider"] == "sdxl"
    assert lustify["local_path"] == str(registry.LUSTIFY_ENDGAME_DIRECTORY)
    assert lustify["quantization"] == "none"
    assert lustify["model_family"] == "sdxl"
    assert lustify["enabled"] is False
    assert lustify["default_steps"] == 30
    assert lustify["default_guidance"] == 3.5
    assert "text_to_image" in lustify["capabilities"]
    assert "image_edit" not in lustify["capabilities"]


def test_existing_registry_adds_lustify_without_touching_ragnarok(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "image-models.invalid.json")
    data = registry.initial_registry()
    data["builtin_defaults_revision"] = 8
    data["models"] = [
        item for item in data["models"] if item["id"] != registry.LUSTIFY_ENDGAME_ID
    ]
    juggernaut = next(item for item in data["models"] if item["id"] == registry.JUGGERNAUT_XL_ID)
    juggernaut["enabled"] = True
    juggernaut["default_guidance"] = 6.0
    data["default_model"] = registry.JUGGERNAUT_XL_ID
    registry.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")

    upgraded = registry.load_registry()
    models = {item["id"]: item for item in upgraded["models"]}
    assert upgraded["builtin_defaults_revision"] == registry.BUILTIN_DEFAULTS_REVISION
    assert upgraded["default_model"] == registry.JUGGERNAUT_XL_ID
    assert models[registry.JUGGERNAUT_XL_ID]["enabled"] is True
    assert models[registry.JUGGERNAUT_XL_ID]["default_guidance"] == 6.0
    assert models[registry.LUSTIFY_ENDGAME_ID]["enabled"] is False
    assert len([item for item in upgraded["models"] if item["id"] == registry.LUSTIFY_ENDGAME_ID]) == 1
    assert registry.load_registry() == upgraded


def test_lustify_uses_same_offline_sdxl_file_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODEL_ROOTS", (tmp_path,))
    model_dir = tmp_path / "LustifyEndgame"
    model_dir.mkdir()
    model = registry.ImageModel(**(
        next(item for item in registry.builtin_models() if item["id"] == registry.LUSTIFY_ENDGAME_ID)
        | {"local_path": str(model_dir)}
    )).model_dump()

    # Never accidentally pick a wrong checkpoint from a directory with several weights.
    try:
        providers.sdxl_files(model)
        assert False, "Missing checkpoint was accepted"
    except RuntimeError as exc:
        assert "genau einen" in str(exc)

    checkpoint = model_dir / registry.LUSTIFY_ENDGAME_CHECKPOINT
    checkpoint.write_bytes(b"test-only weights")
    config = model_dir / "config"
    config.mkdir()
    (config / "model_index.json").write_text("{}", encoding="utf-8")
    assert providers.sdxl_files(model) == (checkpoint, config)

    (model_dir / "dmd2.safetensors").write_bytes(b"other weights")
    try:
        providers.sdxl_files(model)
        assert False, "Ambiguous checkpoint was accepted"
    except RuntimeError as exc:
        assert "genau einen" in str(exc)


def test_lustify_provider_passes_same_seed_cfg_steps_and_canvas(monkeypatch, tmp_path):
    model = next(item for item in registry.builtin_models() if item["id"] == registry.LUSTIFY_ENDGAME_ID)
    output = tmp_path / "out.png"
    checkpoint = tmp_path / "lustify.safetensors"
    config = tmp_path / "config"
    worker = Mock()
    monkeypatch.setattr(providers, "availability", lambda item: (True, "ready"))
    monkeypatch.setattr(providers, "sdxl_files", lambda item: (checkpoint, config))
    monkeypatch.setattr(providers, "_sdxl_worker_manager", worker)
    monkeypatch.setattr(providers, "_validate_provider_output", lambda *args, **kwargs: None)
    monkeypatch.setattr(providers, "_maybe_quality_upscale", lambda *args, **kwargs: False)
    params = {
        "prompt": "Adult studio portrait", "negative_prompt": "blurry",
        "width": 832, "height": 1216, "steps": 30,
        "guidance": 3.5, "seed": 42,
    }
    providers.run_provider(model, params, output)
    call = worker.generate.call_args
    assert call.args[:4] == (checkpoint, config, params, output)
    assert call.args[2]["seed"] == 42
    assert call.args[2]["guidance"] == 3.5
    assert call.args[2]["steps"] == 30


def test_lustify_quality_profile_does_not_inherit_juggernaut_cfg():
    builtins = {item["id"]: item for item in registry.builtin_models()}
    lustify = builtins[registry.LUSTIFY_ENDGAME_ID]
    juggernaut = builtins[registry.JUGGERNAUT_XL_ID]
    assert resolve_image_profile(lustify, "standard") == {
        "steps": 30, "guidance": 3.5, "long_edge": 1024,
    }
    assert resolve_image_profile(lustify, "quality") == {
        "steps": 30, "guidance": 3.5, "long_edge": 1216,
    }
    assert resolve_image_profile(juggernaut, "quality")["guidance"] == 5.0


def test_benchmark_dry_run_has_identical_settings_and_distinct_names():
    command = [
        sys.executable, str(ROOT / "scripts/benchmark-sdxl-models.py"),
        "--dry-run", "--seed", "357", "--repeats", "2",
        "--width", "832", "--height", "1216", "--steps", "30", "--cfg", "3.5",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    jobs = json.loads(result.stdout)
    assert len(jobs) == 4
    assert len({job["filename"] for job in jobs}) == 4
    assert {job["model"] for job in jobs} == {"juggernaut-xl", "lustify-endgame-sdxl"}
    assert {job["seed"] for job in jobs} == {357}
    assert {job["steps"] for job in jobs} == {30}
    assert {job["cfg"] for job in jobs} == {3.5}
    assert {job["width"] for job in jobs} == {832}
    assert {job["height"] for job in jobs} == {1216}


def test_custom_lustify_directory_survives_registry_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "image-models.invalid.json")
    monkeypatch.setattr(registry, "MODEL_ROOTS", (tmp_path,))
    registry.load_registry()
    custom_dir = tmp_path / "custom-lustify-checkpoint"
    registry.update_model(registry.LUSTIFY_ENDGAME_ID, {"local_path": str(custom_dir)})
    assert registry.get_model(registry.LUSTIFY_ENDGAME_ID, require_enabled=False)["local_path"] == str(custom_dir)


def test_health_names_lustify_if_it_is_the_resident_sdxl_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "image-models.invalid.json")
    monkeypatch.setattr(registry, "MODEL_ROOTS", (tmp_path,))
    checkpoint_dir = tmp_path / "LustifyEndgame"
    checkpoint_dir.mkdir()
    checkpoint = checkpoint_dir / "standard-endgame.safetensors"
    checkpoint.write_bytes(b"test weights")
    config = checkpoint_dir / "config"
    config.mkdir()
    (config / "model_index.json").write_text("{}", encoding="utf-8")
    registry.load_registry()
    registry.update_model(registry.LUSTIFY_ENDGAME_ID, {
        "local_path": str(checkpoint_dir), "enabled": True,
    })
    monkeypatch.setattr(service, "sdxl_worker_running", lambda: True)
    monkeypatch.setattr(service, "sdxl_loaded_checkpoint", lambda: checkpoint)
    monkeypatch.setattr(service, "_loaded_mlxserve_models", lambda: [])
    monkeypatch.setattr(service, "_running", None)
    assert service.health()["running_model"] == registry.LUSTIFY_ENDGAME_ID
