"""Opt-in FLUX 3 Klein Q4 integration: no model downloads or global MFLUX upgrades."""
from pathlib import Path

import pytest

import image_registry as registry
import image_providers as providers
import mflux_capabilities as contracts
from quality_profiles import resolve_image_profile


def flux3_model():
    return next(model for model in registry.builtin_models()
                if model["id"] == registry.FLUX3_KLEIN_Q4_ID)


def test_flux3_is_additive_and_not_default():
    model = flux3_model()
    assert model["enabled"] is False
    assert model["provider"] == "mflux"
    assert model["repository"] == "mflux-community/flux-3-image-klein-mflux-q4"
    assert model["quantization"] == "q4"
    assert model["quantize_on_load"] is False
    assert model["default_steps"] == 16
    assert {"text_to_image", "image_edit", "multi_image_edit"} <= set(model["capabilities"])
    assert registry.initial_registry()["default_model"] == registry.LEGACY_ID
    juggernaut = next(model for model in registry.builtin_models() if model["id"] == registry.JUGGERNAUT_XL_ID)
    assert juggernaut["model_family"] == "sdxl"
    assert resolve_image_profile(model, "standard") == {
        "steps": 16, "guidance": 0.0, "long_edge": 1024,
    }


def test_flux3_rejects_unverified_checkpoint_or_double_quantization():
    model = flux3_model()
    for patch in (
        {"quantize_on_load": True},
        {"repository": "black-forest-labs/FLUX.3-image-klein"},
        {"base_model": "flux3-klein-base"},
        {"default_guidance": 1.0},
    ):
        with pytest.raises(ValueError):
            registry.ImageModel(**(model | patch))


def test_flux3_cli_resolves_only_to_isolated_venv():
    model = flux3_model()
    assert providers.mflux_executable(model).name == "mflux-generate-flux3"
    assert providers.mflux_executable(model, edit=True).name == "mflux-generate-flux3-edit"
    assert providers.mflux_executable(model).parent == providers.FLUX3_MFLUX_BIN
    expected = contracts.required_mflux_flags(model)
    assert {"--base-model", "--low-ram", "--steps", "--seed"} <= expected
    assert not {"--quantize", "--guidance", "--mlx-cache-limit-gb"} & expected


def test_flux3_generate_and_reference_edit_commands_are_offline_and_q4(monkeypatch, tmp_path):
    model = flux3_model()
    model["enabled"] = True
    root = tmp_path / "weights"
    root.mkdir()
    (root / "model.safetensors").write_bytes(b"fake")
    venv = tmp_path / "bin"
    venv.mkdir()
    for name in ("mflux-generate-flux3", "mflux-generate-flux3-edit"):
        cli = venv / name
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o700)
    monkeypatch.setattr(providers, "FLUX3_MFLUX_BIN", venv)
    monkeypatch.setattr(providers, "model_directory", lambda _model: root)
    flags = frozenset(("--model", "--base-model", "--prompt", "--width", "--height",
                      "--steps", "--seed", "--output", "--image-paths", "--low-ram"))
    probe = lambda _cli: {"available": True, "supported_flags": flags,
                          "version": "0.24.0", "error": None}
    monkeypatch.setattr(providers, "probe_mflux_cli", probe)
    monkeypatch.setattr(contracts, "probe_mflux_cli", probe)
    assert providers.availability(model)[0] is True
    generated = providers.mflux_command(
        model, {"prompt": "A portrait", "width": 1024, "height": 1024,
                "steps": 16, "seed": 42, "guidance": 0.0},
        tmp_path / "out.png",
    )
    assert generated[0] == str(venv / "mflux-generate-flux3")
    assert generated[generated.index("--model") + 1] == str(root)
    assert "--low-ram" in generated
    assert "--quantize" not in generated
    assert "--guidance" not in generated
    assert "--image-paths" not in generated
    edited = providers.mflux_command(
        model, {"prompt": "Same adult woman, neutral background",
                "source_paths": ["/tmp/source-one.png", "/tmp/source-two.png"],
                "width": 1024, "height": 1024,
                "steps": 16, "seed": 42, "guidance": 0.0},
        tmp_path / "edited.png",
    )
    assert edited[0] == str(venv / "mflux-generate-flux3-edit")
    assert edited[edited.index("--image-paths") + 1:edited.index("--image-paths") + 3] == [
        "/tmp/source-one.png", "/tmp/source-two.png",
    ]
    assert "--quantize" not in edited
    assert "--guidance" not in edited
    with pytest.raises(providers.ProviderFailure):
        providers.mflux_command(
            model, {"prompt": "Edit", "steps": 16, "seed": 42,
                    "source_path": "/tmp/source.png",
                    "negative_prompt": "bad anatomy"},
            tmp_path / "rejected.png",
        )
    (venv / "mflux-generate-flux3-edit").unlink()
    assert providers.availability(model)[0] is False


def test_existing_registry_gains_opt_in_model_without_touching_default(tmp_path, monkeypatch):
    dest = tmp_path / "image-models.json"
    monkeypatch.setattr(registry, "REGISTRY_FILE", dest)
    monkeypatch.setattr(registry, "INVALID_REGISTRY_FILE", tmp_path / "invalid.json")
    data = registry.initial_registry()
    data["models"] = [m for m in data["models"] if m["id"] != registry.FLUX3_KLEIN_Q4_ID]
    dest.write_text(__import__("json").dumps(data))
    upgraded = registry.load_registry()
    assert upgraded["default_model"] == data["default_model"]
    assert next(m for m in upgraded["models"] if m["id"] == registry.FLUX3_KLEIN_Q4_ID)["enabled"] is False



def test_legacy_negative_prompt_is_removed_before_flux3_generation(monkeypatch):
    import image_service

    model = flux3_model() | {"enabled": True}
    monkeypatch.setattr(image_service, "_generation_model",
                        lambda _model_id, _prompt: model)
    request = image_service.Generate(
        prompt="Portrait of an adult woman", model=registry.FLUX3_KLEIN_Q4_ID,
        width=1024, height=1024, negative_prompt="old saved SDXL exclusion",
    )
    resolved = image_service._resolve_generation(request)
    assert resolved["model"]["id"] == registry.FLUX3_KLEIN_Q4_ID
    assert resolved["params"]["steps"] == 16
    assert "negative_prompt" not in resolved["params"]
    # The same optional exclusion is still passed to models that support it.
    another = model | {"model_family": "flux2-klein", "base_model": "flux2-klein-4b",
                       "default_guidance": 1.0}
    monkeypatch.setattr(image_service, "_generation_model",
                        lambda _model_id, _prompt: another)
    resolved_other = image_service._resolve_generation(request)
    assert resolved_other["params"]["negative_prompt"] == "old saved SDXL exclusion"
