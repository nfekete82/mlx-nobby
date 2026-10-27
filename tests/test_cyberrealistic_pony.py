"""Opt-in Pony registry/profile integration; no weights or GPU required."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import image_providers as providers
import image_registry as registry
import image_service as service
from quality_profiles import resolve_image_profile


def pony_builtin():
    return next(m for m in registry.builtin_models()
                if m["id"] == registry.CYBERREALISTIC_PONY_V18_ID)


@pytest.fixture
def registry_file(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    return registry.REGISTRY_FILE


def test_pony_is_additional_disabled_local_sdxl_builtin():
    model = pony_builtin()
    assert model["name"] == "CyberRealistic Pony v18 CoreShift"
    assert (model["provider"], model["model_family"], model["base_model"]) == (
        "sdxl", "sdxl", "sdxl",
    )
    assert model["quantization"] == "none"
    assert model["enabled"] is False
    assert model["repository"] is None
    assert model["local_path"] == str(Path.home() / "Models" / "CyberRealisticPonyV18")
    assert (model["default_steps"], model["default_guidance"]) == (35, 5.0)
    assert {"text_to_image", "image_edit", "img2img"} <= set(model["capabilities"])
    assert registry.initial_registry()["default_model"] == registry.LEGACY_ID
    juggernaut = next(m for m in registry.builtin_models()
                      if m["id"] == registry.JUGGERNAUT_XL_ID)
    assert (juggernaut["default_steps"], juggernaut["default_guidance"]) == (35, 4.0)


def test_existing_registry_adds_pony_without_changing_user_choices(registry_file):
    state = registry.initial_registry()
    state["models"] = [m for m in state["models"]
                       if m["id"] != registry.CYBERREALISTIC_PONY_V18_ID]
    juggernaut = next(m for m in state["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    juggernaut.update(enabled=True, default_steps=37, default_guidance=4.8)
    custom = copy.deepcopy(juggernaut)
    custom.update(id="custom-sdxl", name="User SDXL", local_path=str(Path.home() / "Models" / "Custom"))
    state["models"].append(custom)
    state["default_model"] = juggernaut["id"]
    registry_file.write_text(json.dumps(state), encoding="utf-8")

    migrated = registry.load_registry()
    assert migrated["default_model"] == state["default_model"]
    assert migrated["builtin_defaults_revision"] == state["builtin_defaults_revision"]
    assert [m for m in migrated["models"]
            if m["id"] != registry.CYBERREALISTIC_PONY_V18_ID] == state["models"]
    assert migrated["models"][-1] == pony_builtin()
    assert json.loads(registry_file.with_suffix(".json.previous").read_text()) == state
    assert registry.load_registry() == migrated
    assert json.loads(registry_file.with_suffix(".json.previous").read_text()) == state
    with pytest.raises(ValueError, match="deaktiviert"):
        registry.get_model(registry.CYBERREALISTIC_PONY_V18_ID)


def test_pony_user_tuning_survives_reload(registry_file):
    state = registry.initial_registry()
    pony = next(m for m in state["models"] if m["id"] == registry.CYBERREALISTIC_PONY_V18_ID)
    pony.update(enabled=True, default_steps=31, default_guidance=6.0)
    state["default_model"] = pony["id"]
    registry_file.write_text(json.dumps(state), encoding="utf-8")
    assert registry.load_registry() == state
    assert registry.get_model()["default_guidance"] == 6.0


@pytest.mark.parametrize("quality,steps,guidance,long_edge", [
    ("fast", 20, 5.0, 768),
    ("standard", 35, 5.0, 1216),
    ("quality", 35, 5.5, 1216),
])
def test_pony_profiles_reach_generation_params(monkeypatch, quality, steps, guidance, long_edge):
    model = pony_builtin() | {"enabled": True}
    monkeypatch.setattr(service, "_generation_model", lambda *_args: model)
    expected = {"steps": steps, "guidance": guidance, "long_edge": long_edge}
    assert resolve_image_profile(model, quality) == expected
    resolved = service._resolve_generation(service.Generate(
        model=model["id"], prompt="A lighthouse at sunset", quality=quality,
        auto_size=True, seed=42,
    ))
    assert resolved["quality_profile"] == expected
    params = resolved["params"]
    assert (params["steps"], params["guidance"]) == (steps, guidance)
    assert (params["width"], params["height"]) == (long_edge, long_edge)
    assert params["seed"] == 42
    assert params["scheduler"] == "dpmpp-2m-sde-karras"
    # Diffusers SDXL already selects hidden_states[-2] by default (UI Clip Skip 2).
    # Its clip_skip=2 would incorrectly select hidden_states[-4].
    assert "clip_skip" not in params


def test_pony_explicit_sampler_settings_override_profile(monkeypatch):
    model = pony_builtin() | {"enabled": True}
    monkeypatch.setattr(service, "_generation_model", lambda *_args: model)
    params = service._resolve_generation(service.Generate(
        model=model["id"], prompt="A lighthouse at sunset", quality="quality",
        steps=28, guidance=6.0, width=768, height=512,
    ))["params"]
    assert (params["steps"], params["guidance"], params["width"], params["height"]) == (
        28, 6.0, 768, 512,
    )


def test_pony_uses_shared_offline_sdxl_worker(tmp_path, monkeypatch):
    from PIL import Image

    checkpoint = tmp_path / "pony.safetensors"
    checkpoint.write_bytes(b"test placeholder; not model weights")
    config = tmp_path / "config"
    config.mkdir()
    (config / "model_index.json").write_text("{}", encoding="utf-8")
    model = pony_builtin() | {"local_path": str(tmp_path)}
    monkeypatch.setattr(registry, "MODEL_ROOTS", (tmp_path,))
    monkeypatch.setattr(providers, "availability", lambda _model: (True, "test worker"))
    output = tmp_path / "output.png"
    params = {"prompt": "A lighthouse at sunset", "width": 256, "height": 256,
              "steps": 35, "guidance": 5.0, "seed": 42, "quality": "standard"}
    worker = Mock(side_effect=lambda *_args, **_kwargs: Image.new("RGB", (256, 256)).save(output))
    monkeypatch.setattr(providers._sdxl_worker_manager, "generate", worker)

    providers.run_provider(model, params, output)

    assert worker.call_args.args == (checkpoint, config, params, output)
    environment = worker.call_args.kwargs["environment"]
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert output.is_file()
