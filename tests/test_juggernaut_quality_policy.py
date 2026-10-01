from pathlib import Path

from quality_profiles import resolve_image_profile


ROOT = Path(__file__).resolve().parents[1]


def test_juggernaut_quality_uses_native_1216_with_30_steps():
    model = {
        "id": "juggernaut-xl",
        "model_family": "sdxl",
        "base_model": "sdxl",
        "default_steps": 30,
        "default_guidance": 5.0,
    }

    profile = resolve_image_profile(model, "quality")

    assert profile == {
        "steps": 30,
        "guidance": 5.0,
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
