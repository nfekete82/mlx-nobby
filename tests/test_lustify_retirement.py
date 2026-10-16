"""Retire Lustify from persisted image registry without altering Ragnarok."""
import json

import image_registry as registry


def with_lustify_as_default():
    state = registry.initial_registry()
    reference = next(m for m in state["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    experimental = dict(reference)
    experimental["id"] = "lustify-endgame-sdxl"
    experimental["name"] = "Lustify Endgame (SDXL)"
    experimental["enabled"] = True
    state["models"].append(experimental)
    state["default_model"] = experimental["id"]
    return state


def test_retirement_restores_enabled_juggernaut_and_preserves_customization(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    state = with_lustify_as_default()
    juggernaut = next(m for m in state["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    juggernaut.update(enabled=True, default_steps=37, default_guidance=4.8)
    registry.REGISTRY_FILE.write_text(json.dumps(state), encoding="utf-8")

    migrated = registry.load_registry()
    assert migrated["default_model"] == registry.JUGGERNAUT_XL_ID
    assert "lustify-endgame-sdxl" not in {m["id"] for m in migrated["models"]}
    retained = next(m for m in migrated["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    assert (retained["enabled"], retained["default_steps"], retained["default_guidance"]) == (True, 37, 4.8)
    assert registry.load_registry() == migrated
    assert registry.REGISTRY_FILE.with_suffix(".json.previous").is_file()


def test_retired_default_uses_fallback_if_juggernaut_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    registry.REGISTRY_FILE.write_text(json.dumps(with_lustify_as_default()), encoding="utf-8")
    migrated = registry.load_registry()
    assert migrated["default_model"] == registry.LEGACY_ID
    assert "lustify-endgame-sdxl" not in {m["id"] for m in migrated["models"]}


def test_no_retired_builtin_on_fresh_install():
    assert "lustify-endgame-sdxl" not in {
        m["id"] for m in registry.builtin_models()
    }


def test_cannot_reintroduce_retired_model(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    state = registry.load_registry()
    source = next(m for m in state["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    with pytest.raises(ValueError, match="entfernt"):
        registry.add_model({**source, "id": "lustify-endgame-sdxl"})
