"""Retire an unsuccessful FLUX 3 trial without altering existing image models."""
import json

import pytest

import image_registry as registry


FLUX3_ID = "mflux-flux3-image-klein-q4"


def saved_test_registry():
    state = registry.initial_registry()
    juggernaut = next(
        model for model in state["models"]
        if model["id"] == registry.JUGGERNAUT_XL_ID
    )
    tested = dict(juggernaut)
    tested.update(
        id=FLUX3_ID,
        name="FLUX 3 Image Klein · Q4 · Test",
        provider="mflux",
        repository="mflux-community/flux-3-image-klein-mflux-q4",
        local_path=None,
        model_family="flux3-klein",
        base_model="flux3-image-klein",
        quantization="q4",
        quantize_on_load=False,
        enabled=True,
        default_steps=16,
        default_guidance=0.0,
    )
    state["models"].append(tested)
    return state


def test_flux3_retired_from_persisted_registry_preserving_all_other_models(tmp_path, monkeypatch):
    path = tmp_path / "image-models.json"
    monkeypatch.setattr(registry, "REGISTRY_FILE", path)
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    state = saved_test_registry()
    juggernaut = next(
        model for model in state["models"]
        if model["id"] == registry.JUGGERNAUT_XL_ID
    )
    juggernaut.update(enabled=True, default_steps=38, default_guidance=4.5)
    state["default_model"] = registry.JUGGERNAUT_XL_ID
    path.write_text(json.dumps(state), encoding="utf-8")

    migrated = registry.load_registry()
    ids = {model["id"] for model in migrated["models"]}
    assert FLUX3_ID not in ids
    assert migrated["default_model"] == registry.JUGGERNAUT_XL_ID
    retained = next(
        model for model in migrated["models"]
        if model["id"] == registry.JUGGERNAUT_XL_ID
    )
    assert (retained["enabled"], retained["default_steps"], retained["default_guidance"]) == (
        True, 38, 4.5,
    )
    assert path.with_suffix(".json.previous").is_file()
    assert registry.load_registry() == migrated


def test_retired_flux3_default_falls_back_to_enabled_juggernaut(tmp_path, monkeypatch):
    path = tmp_path / "image-models.json"
    monkeypatch.setattr(registry, "REGISTRY_FILE", path)
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    state = saved_test_registry()
    state["default_model"] = FLUX3_ID
    for item in state["models"]:
        if item["id"] == registry.JUGGERNAUT_XL_ID:
            item["enabled"] = True
    path.write_text(json.dumps(state), encoding="utf-8")
    migrated = registry.load_registry()
    assert migrated["default_model"] == registry.JUGGERNAUT_XL_ID
    assert FLUX3_ID not in {m["id"] for m in migrated["models"]}


def test_retired_flux3_is_absent_and_cannot_be_readded(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "image-models.json")
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    state = registry.load_registry()
    assert FLUX3_ID in registry.RETIRED_MODEL_IDS
    assert FLUX3_ID not in {model["id"] for model in state["models"]}
    # Use a schema-valid SDXL record: a retired ID must be blocked even
    # before considering whether its historical experimental family exists.
    former = next(m for m in state["models"] if m["id"] == registry.JUGGERNAUT_XL_ID)
    with pytest.raises(ValueError, match="entfernt"):
        registry.add_model({**former, "id": FLUX3_ID})
