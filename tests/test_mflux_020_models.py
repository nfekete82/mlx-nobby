import image_registry as registry
import mflux_capabilities
from quality_profiles import resolve_image_profile


def _builtins():
    return {model["id"]: model for model in registry.builtin_models()}


def test_mflux_020_quality_models_are_opt_in_and_krea_stays_removed():
    models = _builtins()

    qwen = models[registry.MFLUX_QWEN_IMAGE21_ID]
    assert qwen["provider"] == "mflux"
    assert qwen["model_family"] == "qwen-image21"
    assert qwen["base_model"] == "qwen-image-2.1"
    assert qwen["repository"] == "Qwen/Qwen-Image-2.1"
    assert qwen["quantization"] == "q8"
    assert qwen["default_steps"] == 40
    assert qwen["default_guidance"] == 1.0
    assert qwen["enabled"] is False
    assert "lora" not in qwen["capabilities"]

    boogu = models[registry.MFLUX_BOOGU_ID]
    assert boogu["provider"] == "mflux"
    assert boogu["model_family"] == "boogu"
    assert boogu["repository"] == "Boogu/Boogu-Image-0.1-Turbo"
    assert boogu["quantization"] == "q8"
    assert boogu["default_steps"] == 8
    assert boogu["default_guidance"] == 0.0
    assert boogu["enabled"] is False
    assert "lora" not in boogu["capabilities"]

    assert registry.BUILTIN_DEFAULTS_REVISION == 8
    assert not (registry.LEGACY_KREA_MODEL_IDS & models.keys())


def test_mflux_020_quality_profiles_match_upstream_sampling():
    models = _builtins()
    qwen = resolve_image_profile(models[registry.MFLUX_QWEN_IMAGE21_ID], "quality")
    assert qwen == {"steps": 40, "guidance": 1.0, "long_edge": 1024}

    boogu_fast = resolve_image_profile(models[registry.MFLUX_BOOGU_ID], "fast")
    assert boogu_fast == {"steps": 4, "guidance": 0.0, "long_edge": 768}

    boogu_quality = resolve_image_profile(models[registry.MFLUX_BOOGU_ID], "quality")
    assert boogu_quality == {"steps": 8, "guidance": 0.0, "long_edge": 1024}


def test_boogu_contract_does_not_require_guidance_or_base_model():
    flags = mflux_capabilities.required_mflux_flags(
        _builtins()[registry.MFLUX_BOOGU_ID]
    )
    assert "--guidance" not in flags
    assert "--base-model" not in flags
    assert "--quantize" in flags


def test_qwen21_dedicated_cli_does_not_require_base_model():
    flags = mflux_capabilities.required_mflux_flags(
        _builtins()[registry.MFLUX_QWEN_IMAGE21_ID]
    )
    assert "--base-model" not in flags
    assert "--guidance" in flags
    assert "--quantize" in flags


def test_mflux_020_cli_families_are_exact():
    assert registry.FAMILIES["qwen-image21"][0] == "mflux-generate-qwen-2.1"
    assert registry.FAMILIES["boogu"][0] == "mflux-generate-boogu"
    assert "krea2" not in registry.FAMILIES
