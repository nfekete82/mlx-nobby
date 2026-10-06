import image_registry as registry
import mflux_capabilities
from quality_profiles import resolve_image_profile


def _builtins():
    return {model["id"]: model for model in registry.builtin_models()}


def test_mflux_020_quality_models_are_opt_in():
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

    krea = models[registry.MFLUX_KREA2_ID]
    assert krea["provider"] == "mflux"
    assert krea["model_family"] == "krea2"
    assert krea["repository"] == "krea/Krea-2-Turbo"
    assert krea["quantization"] == "q8"
    assert krea["default_steps"] == 8
    assert krea["default_guidance"] == 1.0
    assert krea["enabled"] is False
    assert "lora" in krea["capabilities"]

    boogu = models[registry.MFLUX_BOOGU_ID]
    assert boogu["provider"] == "mflux"
    assert boogu["model_family"] == "boogu"
    assert boogu["repository"] == "Boogu/Boogu-Image-0.1-Turbo"
    assert boogu["quantization"] == "q8"
    assert boogu["default_steps"] == 8
    assert boogu["default_guidance"] == 0.0
    assert boogu["enabled"] is False
    assert "lora" not in boogu["capabilities"]


def test_mflux_020_quality_profiles_match_upstream_sampling():
    models = _builtins()

    qwen = resolve_image_profile(models[registry.MFLUX_QWEN_IMAGE21_ID], "quality")
    assert qwen == {"steps": 40, "guidance": 1.0, "long_edge": 1024}

    krea = resolve_image_profile(models[registry.MFLUX_KREA2_ID], "quality")
    assert krea == {"steps": 8, "guidance": 1.0, "long_edge": 1024}

    boogu_fast = resolve_image_profile(models[registry.MFLUX_BOOGU_ID], "fast")
    assert boogu_fast == {"steps": 4, "guidance": 0.0, "long_edge": 768}

    boogu_quality = resolve_image_profile(models[registry.MFLUX_BOOGU_ID], "quality")
    assert boogu_quality == {"steps": 8, "guidance": 0.0, "long_edge": 1024}


def test_boogu_contract_does_not_require_guidance():
    model = _builtins()[registry.MFLUX_BOOGU_ID]
    flags = mflux_capabilities.required_mflux_flags(model)
    assert "--guidance" not in flags
    assert "--quantize" in flags


def test_dedicated_mflux_020_clis_do_not_require_base_model():
    models = _builtins()

    for model_id in (
        registry.MFLUX_QWEN_IMAGE21_ID,
        registry.MFLUX_KREA2_ID,
        registry.MFLUX_BOOGU_ID,
    ):
        flags = mflux_capabilities.required_mflux_flags(models[model_id])
        assert "--base-model" not in flags
        assert "--model" in flags
        assert "--quantize" in flags


def test_mflux_020_cli_families_are_exact():
    assert registry.FAMILIES["qwen-image21"][0] == "mflux-generate-qwen-2.1"
    assert registry.FAMILIES["krea2"][0] == "mflux-generate-krea2"
    assert registry.FAMILIES["boogu"][0] == "mflux-generate-boogu"
