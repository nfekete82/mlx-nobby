"""Region-aware Qwen image editing keeps the Mac RAM watchdog unchanged."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

import image_region_edit as region
import image_service as service
from agent.app import _validated_image_options


def _model():
    return {
        "id": "mflux-osaurus-qwen-image-2.1-edit",
        "provider": "mflux",
        "model_family": "qwen-image21-edit",
        "capabilities": ["image_edit"],
        "default_steps": 20, "default_guidance": 1.0,
        "step_cache_default": True, "quantization": "q4", "loras": [],
    }


def test_region_geometry_crop_is_aligned_and_never_loses_selected_pixels():
    mask = Image.new("L", (832, 1216), 0)
    ImageDraw.Draw(mask).ellipse((255, 336, 382, 465), fill=255)
    crop = region.region_box(mask.size, mask)
    assert crop[2] - crop[0] == 512
    assert crop[3] - crop[1] == 512
    assert crop[0] <= 255 and crop[1] <= 336
    assert crop[2] >= 382 and crop[3] >= 465
    assert crop[0] >= 0 and crop[1] >= 0


def test_large_mask_rejected_early():
    mask = Image.new("L", (832, 1216), 0)
    ImageDraw.Draw(mask).rectangle((12, 10, 700, 800), fill=255)
    with pytest.raises(HTTPException, match="kleinere Auswahl"):
        region.region_box(mask.size, mask)


def test_region_edit_crops_before_qwen_and_preserves_unselected_pixels(tmp_path, monkeypatch):
    output = tmp_path / "images"
    output.mkdir()
    source = output / "1791111111-aaaaaaaaaaaa.png"
    mask = output / "input-mask.png"
    Image.new("RGB", (832, 1216), (50, 100, 150)).save(source)
    selected = Image.new("L", (832, 1216), 0)
    ImageDraw.Draw(selected).rectangle((300, 400, 365, 465), fill=255)
    selected.save(mask)
    before = source.read_bytes()
    calls = []
    def provider(model, params, target, **_kwargs):
        assert model["step_cache_default"] is False
        assert params["_region_low_ram"] is True
        assert params["width"] <= 512 and params["height"] <= 512
        with Image.open(params["source_path"]) as cut, Image.open(params["mask_path"]) as paint:
            assert cut.size == paint.size == (params["width"], params["height"])
            assert paint.getbbox() is not None
            calls.append((params["width"], params["height"], params["steps"]))
        Image.new("RGB", (params["width"], params["height"]), (230, 40, 90)).save(target)
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(service, "_edit_model", lambda *args, **kwargs: _model())
    monkeypatch.setattr(service, "run_provider", provider)
    monkeypatch.setattr(service.runtime_coordinator, "ensure_model_load_allowed", lambda *_args, **_kwargs: None)
    request = service.Edit(
        source_path=str(source), mask_path=str(mask),
        prompt="Refine only selected face details",
        region_edit=True, model="auto", quality="standard", seed=10
    )
    result = service._edit_result(request)
    assert calls == [(512, 512, 20)]
    assert (result["width"], result["height"]) == (832, 1216)
    assert source.read_bytes() == before
    assert result["source_image_id"] == "1791111111-aaaaaaaaaaaa"
    with Image.open(result["path"]) as edited:
        assert edited.getpixel((1, 1)) == (50, 100, 150)
        assert edited.getpixel((310, 420)) == (230, 40, 90)
        assert edited.getpixel((380, 420)) == (50, 100, 150)
    assert not list(output.glob(".edit-source-*.png"))


def test_reject_oversized_region_before_provider(tmp_path, monkeypatch):
    output = tmp_path / "images"
    output.mkdir()
    src = output / "1791111111-bbbbbbbbbbbb.png"
    mask = output / "big-mask.png"
    Image.new("RGB", (832, 1216), "white").save(src)
    Image.new("L", (832, 1216), 255).save(mask)
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(service, "_edit_model", lambda *_args, **_kwargs: _model())
    monkeypatch.setattr(service, "run_provider", lambda *_args, **_kwargs: pytest.fail("Provider must not start"))
    with pytest.raises(HTTPException, match="kleinere Auswahl"):
        service._edit_result(service.Edit(
            source_path=str(src), mask_path=str(mask),
            prompt="Refine face", region_edit=True
        ))
    assert not list(output.glob(".edit-source-*.png"))


def test_region_edit_requires_manual_mask_and_single_source():
    with pytest.raises(ValueError, match="Region edit requires"):
        service.Edit(source_path="/tmp/input.png", prompt="Enhance face", region_edit=True)
    with pytest.raises(ValueError, match="Region edit requires"):
        service.Edit(source_path="/tmp/input.png", mask_path="/tmp/mask.png",
                     source_paths=["/tmp/input.png"], prompt="Enhance face", region_edit=True)


def test_region_field_only_permitted_in_edit_contract():
    assert _validated_image_options({"region_edit": True, "mask_path": "/uploads/m.png"}, "edit")["region_edit"]
    with pytest.raises(HTTPException):
        _validated_image_options({"region_edit": True}, "generate")
