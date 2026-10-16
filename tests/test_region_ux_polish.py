"""Zoom/soft-mask editor upgrades: bounded inner feather without global edits."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

from agent.app import _validated_image_options
import image_region_edit
import image_service


def test_feather_preserves_exact_nonselected_pixels_and_original(tmp_path):
    original = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    generated = tmp_path / "generated.png"
    final = tmp_path / "final.png"
    Image.new("RGB", (512, 512), (30, 80, 120)).save(original)
    selection = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(selection).rectangle((100, 100, 200, 200), fill=255)
    selection.save(mask)
    Image.new("RGB", (512, 512), (220, 50, 60)).save(generated)
    src_bytes = original.read_bytes()

    image_region_edit.composite_region(
        original, mask, generated, (0, 0, 512, 512), final, feather_px=5
    )

    with Image.open(final) as output:
        assert output.size == (512, 512)
        assert output.getpixel((99, 150)) == (30, 80, 120)
        assert output.getpixel((300, 300)) == (30, 80, 120)
        assert output.getpixel((150, 150)) == (220, 50, 60)
        r, g, b = output.getpixel((100, 150))
        assert 30 < r < 220
        assert 50 < g < 80
        assert 60 < b < 120
    assert original.read_bytes() == src_bytes
    assert not list(tmp_path.glob(".edit-source-*.png"))


def test_zero_feather_retains_exact_original_mask_boundary(tmp_path):
    original = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    generated = tmp_path / "generated.png"
    final = tmp_path / "final.png"
    Image.new("RGB", (256, 256), "black").save(original)
    selection = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(selection).rectangle((100, 100, 150, 150), fill=255)
    selection.save(mask)
    Image.new("RGB", (256, 256), "white").save(generated)
    image_region_edit.composite_region(
        original, mask, generated, (0, 0, 256, 256), final, feather_px=0
    )
    with Image.open(final) as output:
        assert output.getpixel((99, 100)) == (0, 0, 0)
        assert output.getpixel((100, 100)) == (255, 255, 255)


@pytest.mark.parametrize("invalid", [-1, 13, 1.5])
def test_feather_outside_range_rejected_by_schema(invalid):
    with pytest.raises(ValueError):
        image_service.Edit(
            prompt="Alter the selected eyes", source_path="/a.png",
            mask_path="/m.png", region_edit=True, region_feather_px=invalid
        )


def test_feather_requires_manual_region_mask():
    with pytest.raises(ValueError, match="Mask feather requires region edit"):
        image_service.Edit(
            prompt="Alter the selected eyes", source_path="/a.png",
            mask_path="/m.png", region_feather_px=4
        )


def test_feather_only_accepted_in_edit_options():
    opts = {"region_edit": True, "mask_path": "/private/mask.png", "region_feather_px": 3}
    assert _validated_image_options(opts, "edit") == opts
    with pytest.raises(HTTPException):
        _validated_image_options({"region_feather_px": 3}, "generate")
    with pytest.raises(HTTPException):
        _validated_image_options({"region_feather_px": 3}, "reference")


def test_overlarge_feather_cannot_change_image(tmp_path):
    source = tmp_path / "original.png"
    result = tmp_path / "model.png"
    mask = tmp_path / "mask.png"
    target = tmp_path / "composite.png"
    Image.new("RGB", (256, 256), (0, 0, 0)).save(source)
    Image.new("RGB", (256, 256), (255, 255, 255)).save(result)
    Image.new("L", (256, 256), 255).save(mask)
    with pytest.raises(ValueError):
        image_region_edit.composite_region(source, mask, result, (0,0,256,256),
                                           target, feather_px=20)
    assert not target.exists()
