"""Ragnarok creator-aligned defaults, reproducible sampler and safe migration."""
import json

import image_registry as registry
import image_service as service
from quality_profiles import resolve_image_profile


def test_ragnarok_factory_defaults_match_creator_range():
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.JUGGERNAUT_XL_ID)
    assert model["default_steps"] == 35
    assert model["default_guidance"] == 4.0
    assert resolve_image_profile(model, "standard") == {
        "steps": 35, "guidance": 4.0, "long_edge": 1216,
    }
    assert resolve_image_profile(model, "quality") == {
        "steps": 30, "guidance": 4.0, "long_edge": 1216,
    }


def test_existing_ragnarok_defaults_migrate_without_disabling_model(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "image-models.invalid.json")
    saved = registry.initial_registry()
    saved["builtin_defaults_revision"] = 8
    model = next(m for m in saved["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    model["enabled"] = True
    model["default_steps"] = 30
    model["default_guidance"] = 5.0
    saved["default_model"] = registry.JUGGERNAUT_XL_ID
    registry.REGISTRY_FILE.write_text(json.dumps(saved), encoding="utf-8")

    migrated = registry.load_registry()
    new = next(m for m in migrated["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    assert new["enabled"] is True
    assert (new["default_steps"], new["default_guidance"]) == (35, 4.0)
    assert migrated["default_model"] == registry.JUGGERNAUT_XL_ID
    assert migrated["builtin_defaults_revision"] == 9
    assert registry.load_registry() == migrated


def test_migration_preserves_explicit_customized_values(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "image-models.invalid.json")
    saved = registry.initial_registry()
    saved["builtin_defaults_revision"] = 8
    model = next(m for m in saved["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    model["default_steps"] = 38
    model["default_guidance"] = 3.7
    registry.REGISTRY_FILE.write_text(json.dumps(saved), encoding="utf-8")
    loaded = registry.load_registry()
    same = next(m for m in loaded["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    assert same["default_steps"] == 38
    assert same["default_guidance"] == 3.7


def test_ragnarok_default_portrait_and_scheduler_are_reproducible(monkeypatch):
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.JUGGERNAUT_XL_ID)
    monkeypatch.setattr(service, "_generation_model", lambda *_: model)
    request = service.Generate(
        prompt="Realistic candid photograph of an adult woman on a sidewalk",
        model="juggernaut-xl", quality="standard",
        auto_size=True, width=832, height=1216, seed=42,
    )
    params = service._resolve_generation(request)["params"]
    assert (params["width"], params["height"]) == (832, 1216)
    assert params["steps"] == 35
    assert params["guidance"] == 4.0
    assert params["seed"] == 42
    assert params["scheduler"] == "dpmpp-2m-sde-karras"
    assert "negative_prompt" not in params


def test_explicit_controls_and_negatives_are_preserved(monkeypatch):
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.JUGGERNAUT_XL_ID)
    monkeypatch.setattr(service, "_generation_model", lambda *_: model)
    request = service.Generate(
        prompt="Studio portrait of an adult", model="juggernaut-xl",
        steps=30, guidance=5.0, seed=24, negative_prompt="watermark",
    )
    params = service._resolve_generation(request)["params"]
    assert params["steps"] == 30
    assert params["guidance"] == 5.0
    assert params["negative_prompt"] == "watermark"
    assert params["scheduler"] == "dpmpp-2m-sde-karras"


def test_other_sdxl_models_keep_existing_scheduler(monkeypatch):
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.JUGGERNAUT_XL_ID)
    monkeypatch.setattr(service, "_generation_model",
                        lambda *_: {**model, "id": "my-local-sdxl"})
    request = service.Generate(prompt="An adult studio portrait", model="my-local-sdxl")
    assert "scheduler" not in service._resolve_generation(request)["params"]
