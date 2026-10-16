from pathlib import Path

from quality_profiles import resolve_image_profile


ROOT = Path(__file__).resolve().parents[1]


def test_juggernaut_quality_uses_native_1216_with_40_steps():
    model = {
        "id": "juggernaut-xl",
        "model_family": "sdxl",
        "base_model": "sdxl",
        "default_steps": 35,
        "default_guidance": 4.0,
    }

    profile = resolve_image_profile(model, "quality")

    assert profile == {
        "steps": 40,
        "guidance": 4.0,
        "long_edge": 1216,
    }


def test_production_image_service_disables_automatic_quality_upscale():
    template = (
        ROOT
        / "launchd"
        / "templates"
        / "de.nobby.mlx-images.plist.template"
    ).read_text(encoding="utf-8")

    assert "<key>MLX_IMAGE_QUALITY_UPSCALE</key><string>off</string>" in template
    assert "image_service_pipeline:app" in template


def test_juggernaut_ultra_uses_native_1536_with_model_quality_steps():
    model = {
        "id": "juggernaut-xl",
        "model_family": "sdxl",
        "base_model": "sdxl",
        "default_steps": 35,
        "default_guidance": 4.0,
    }
    profile = resolve_image_profile(model, "ultra")
    assert profile == {"steps": 40, "guidance": 4.0, "long_edge": 1536}
    assert resolve_image_profile(model, "quality")["long_edge"] == 1216


def test_ultra_preserves_qwen_model_specific_guidance():
    model = {
        "id": "mflux-qwen-image-2.1",
        "model_family": "qwen-image21",
        "base_model": "qwen-image21",
        "default_steps": 30,
        "default_guidance": 1.0,
    }
    profile = resolve_image_profile(model, "ultra")
    assert profile["long_edge"] == 1536
    assert profile["guidance"] == 1.0
    assert profile["steps"] == 40
