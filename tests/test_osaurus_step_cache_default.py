"""Osaurus-only default Step Cache, with model UI opt-out and per-job overrides."""
from pathlib import Path

import pytest

import image_providers as providers
import image_registry as registry


def test_only_osaurus_built_in_enabled_and_registry_opt_out_survives_migration():
    models = {m["id"]: m for m in registry.builtin_models()}
    target = models[registry.OSAURUS_QWEN21_EDIT_ID]
    assert target["enabled"] is False  # Never auto-enable model availability.
    assert target["step_cache_default"] is True
    assert all(not m["step_cache_default"] for k, m in models.items()
               if k != registry.OSAURUS_QWEN21_EDIT_ID)

    previous = target | {"step_cache_default": False, "enabled": True}
    migrated = registry._canonicalize_known_builtin(previous, models)
    assert migrated["step_cache_default"] is False
    assert migrated["enabled"] is True

    assert registry.ImageModel(**previous).step_cache_default is False
    for other_id in ("mflux-qwen-image-2.1-edit", registry.QWEN_IMAGE_EDIT_ID,
                     registry.JUGGERNAUT_XL_ID):
        if other_id in models:
            with pytest.raises(ValueError, match="nur für Osaurus"):
                registry.ImageModel(**(models[other_id] | {"step_cache_default": True}))


@pytest.fixture()
def qwen_cli(monkeypatch):
    def contract(model, executable):
        return True, "ok"

    available = {
        "--image-paths", "--model", "--prompt", "--width", "--height",
        "--steps", "--guidance", "--seed", "--output",
        "--use-kv-cache", "--no-use-kv-cache",
        "--use-step-cache", "--no-use-step-cache",
        "--step-cache-threshold", "--mlx-cache-limit-gb",
        "--output-resolution", "--vae-tiling", "--low-ram",
    }
    monkeypatch.setattr(providers, "mflux_contract", contract)
    monkeypatch.setattr(providers, "model_directory", lambda model: Path("/tmp/benchmark-weights"))
    monkeypatch.setattr(providers, "probe_mflux_cli",
                        lambda executable: {"supported_flags": available})
    monkeypatch.setattr(providers, "mflux_memory_policy",
                        lambda: {"low_ram": False, "cache_gb": 8})
    return available


def command(model, **override):
    params = {
        "prompt": "change only the lighting",
        "source_path": "/tmp/source.png",
        "width": 1024, "height": 1024,
        "steps": 40, "guidance": 1.0, "seed": 42,
    } | override
    return providers.mflux_command(model, params, Path("/tmp/output.png"))


def test_osaurus_default_turns_on_only_with_supported_flags(qwen_cli):
    model = registry.builtin_models()
    osaurus = next(m for m in model if m["id"] == registry.OSAURUS_QWEN21_EDIT_ID)
    argv = command(osaurus)
    assert "--use-step-cache" in argv
    assert "--use-kv-cache" in argv
    assert "--mlx-cache-limit-gb" in argv
    assert argv[argv.index("--mlx-cache-limit-gb") + 1] == "8"
    assert "--low-ram" not in argv
    assert "--step-cache-threshold" not in argv  # MFLUX 0.12 default unchanged.


def test_model_setting_off_and_per_job_false_are_respected(qwen_cli):
    models = {m["id"]: m for m in registry.builtin_models()}
    model = models[registry.OSAURUS_QWEN21_EDIT_ID]
    off = command(model | {"step_cache_default": False})
    assert "--use-step-cache" not in off
    assert "--no-use-step-cache" not in off

    explicit_off = command(model, use_step_cache=False, use_kv_cache=True)
    assert "--no-use-step-cache" in explicit_off
    assert "--use-step-cache" not in explicit_off
    assert "--use-kv-cache" in explicit_off

    explicit_false_kv = command(model, use_kv_cache=False)
    assert "--use-step-cache" not in explicit_false_kv
    assert "--no-use-kv-cache" in explicit_false_kv

    manual_on = command(model | {"step_cache_default": False},
                        use_step_cache=True, use_kv_cache=True)
    assert "--use-step-cache" in manual_on


def test_other_models_never_receive_implicit_step_cache(qwen_cli):
    models = {m["id"]: m for m in registry.builtin_models()}
    normal_qwen = models["mflux-qwen-image-2.1-edit"]
    assert "--use-step-cache" not in command(normal_qwen)
    assert "--use-kv-cache" not in command(normal_qwen)

    old_qwen = models[registry.QWEN_IMAGE_EDIT_ID]
    assert "--use-step-cache" not in command(old_qwen)


def test_missing_step_cache_cli_flag_falls_back_without_failing(qwen_cli):
    qwen_cli.discard("--use-step-cache")
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.OSAURUS_QWEN21_EDIT_ID)
    argv = command(model)
    assert "--use-step-cache" not in argv
    assert "--use-kv-cache" not in argv
    # Explicit ON is never silently ignored.
    with pytest.raises(providers.ProviderFailure):
        command(model, use_step_cache=True)


def test_region_edit_forces_low_ram_and_limits_mlx_cache(qwen_cli):
    model = next(m for m in registry.builtin_models()
                 if m["id"] == registry.OSAURUS_QWEN21_EDIT_ID)
    argv = command(
        {**model, "step_cache_default": False},
        _region_low_ram=True,
        width=512, height=512,
    )
    assert "--low-ram" in argv
    assert "--mlx-cache-limit-gb" in argv
    assert argv[argv.index("--mlx-cache-limit-gb") + 1] == "2"
    assert "--use-step-cache" not in argv
    assert "--use-kv-cache" not in argv
    assert argv[argv.index("--width") + 1] == "512"
    assert argv[argv.index("--height") + 1] == "512"
