"""CPU-only regressions for photo-preserving Real-ESRGAN modes."""
from pathlib import Path
import io

import pytest
from PIL import Image

from agent import app as agent
import image_providers as providers
from image_upscale_finish import PHOTO_FINISH, finish_photo_upscale
import image_service as service


def test_natural_finish_reduces_neural_color_change_without_smoothing_original(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "upscaled.png"
    Image.new("RGB", (10, 8), (80, 110, 140)).save(source)
    Image.new("RGB", (20, 16), (200, 210, 220)).save(output)
    original_bytes = source.read_bytes()

    assert finish_photo_upscale(source, output, "photo-natural-2x")
    with Image.open(output) as image:
        assert image.size == (20, 16)
        assert image.getpixel((7, 5)) == (146, 165, 184)
    assert source.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*.finishing.png"))


def test_four_x_natural_finish_respects_scale_and_legacy_presets(tmp_path):
    source = tmp_path / "original.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (6, 6), (30, 50, 70)).save(source)
    Image.new("RGB", (24, 24), (130, 150, 170)).save(output)
    old = output.read_bytes()
    assert finish_photo_upscale(source, output, "photo-4x") is False
    assert output.read_bytes() == old
    assert finish_photo_upscale(source, output, "anime-4x") is False
    assert output.read_bytes() == old
    assert finish_photo_upscale(source, output, "photo-natural-4x")
    with Image.open(output) as image:
        assert image.size == (24, 24)
        assert image.getpixel((0, 0)) == (90, 110, 130)


def test_photo_sharp_is_explicit_and_not_the_default(tmp_path):
    source = tmp_path / "original.png"
    natural = tmp_path / "natural.png"
    crisp = tmp_path / "crisp.png"
    # Synthetic high-contrast edge, not any real person/photo.
    Image.new("RGB", (16, 12), (115, 115, 115)).save(source)
    for dest in (natural, crisp):
        with Image.new("RGB", (64, 48), (115, 115, 115)) as image:
            for x in range(32, 64):
                for y in range(48):
                    image.putpixel((x, y), (180, 180, 180))
            image.save(dest)
    assert finish_photo_upscale(source, natural, "photo-natural-4x")
    assert finish_photo_upscale(source, crisp, "photo-sharp-4x")
    with Image.open(natural) as a, Image.open(crisp) as z:
        assert a.size == z.size == (64, 48)
        assert a.tobytes() != z.tobytes()
    assert PHOTO_FINISH["photo-natural-2x"][0] < PHOTO_FINISH["photo-sharp-4x"][0]


def test_transparency_from_source_is_preserved(tmp_path):
    source = tmp_path / "alpha.png"
    output = tmp_path / "output.png"
    with Image.new("RGBA", (8, 8), (100, 120, 140, 100)) as image:
        image.save(source)
    Image.new("RGB", (16, 16), (230, 230, 230)).save(output)
    assert finish_photo_upscale(source, output, "photo-natural-2x")
    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((8, 8))[3] == 100


@pytest.mark.parametrize("preset,scale", [
    ("photo-natural-2x", 2), ("photo-natural-4x", 4),
    ("photo-sharp-4x", 4), ("photo-2x", 2), ("photo-4x", 4),
    ("anime-4x", 4),
])
def test_all_presets_use_the_expected_installed_esrgan_weights(tmp_path, monkeypatch, preset, scale):
    binary = tmp_path / "realesrgan"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    for model in ("realesrgan-x4plus", "realesrgan-x4plus-anime"):
        for ext in (".param", ".bin"):
            (models / f"{model}{ext}").write_bytes(b"existing model fixture")
    monkeypatch.setattr(providers, "REALESRGAN_BIN", binary)
    monkeypatch.setattr(providers, "REALESRGAN_MODELS", models)
    command = providers.realesrgan_command(
        tmp_path / "input.png", tmp_path / "output.png",
        preset=preset,
    )
    assert command[command.index("-s") + 1] == str(scale)
    assert command[command.index("-n") + 1] == (
        "realesrgan-x4plus-anime" if preset == "anime-4x"
        else "realesrgan-x4plus"
    )


@pytest.mark.parametrize("preset,scale", [
    ("photo-natural-2x", 2), ("photo-natural-4x", 4),
    ("photo-sharp-4x", 4),
])
def test_agent_source_and_preset_validation_unchanged(monkeypatch, tmp_path, preset, scale):
    source = tmp_path / "source.png"
    Image.new("RGB", (6, 6), "gray").save(source)
    monkeypatch.setattr(agent, "_image_source_path", lambda *_args, **_kwargs: source)
    payload = agent._image_upscale_payload(agent.ChatActionRequest(
        prompt="Bild verbessern",
        action="image_upscale",
        image_options={"preset": preset, "scale": scale},
    ))
    assert payload == {"source_path": str(source), "preset": preset}


def test_legacy_api_default_still_works():
    assert service.Upscale(source_path="/tmp/sample.png").preset == "photo-2x"
