"""A hand-painted grayscale mask stays confined to the guarded Qwen edit path."""
import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

import image_service as service


@pytest.fixture
def local_editor(monkeypatch, tmp_path):
    output = tmp_path / "images"
    output.mkdir()
    source = output / "1781634000-abc123abc123.png"
    Image.new("RGB", (256, 256), "#666666").save(source)
    mask = output / "mask.png"
    model = {
        "id": "mflux-osaurus-qwen-image-2.1-edit",
        "provider": "mflux",
        "model_family": "qwen-image21-edit",
        "capabilities": ["image_edit"],
        "default_steps": 20,
        "default_guidance": 1.0,
        "quantization": "q4",
        "loras": [],
    }
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(service, "_edit_model", lambda *args, **kwargs: model)
    captures = []
    def provider(_model, params, target, **_kwargs):
        with Image.open(params["mask_path"]) as working:
            captures.append({
                "mask_size": working.size,
                "corner": working.getpixel((0, 0)),
                "center": working.getpixel((128, 128)),
                "auto_mask": params.get("auto_mask"),
            })
        Image.new("RGB", (256, 256), "#777777").save(target)
    monkeypatch.setattr(service, "run_provider", provider)
    return source, mask, captures


def test_manual_mask_reaches_existing_edit_without_auto_mask(local_editor):
    source, mask, captures = local_editor
    image = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(image).ellipse((110, 110, 148, 148), fill=255)
    image.save(mask)
    result = service._edit_result(service.Edit(
        source_path=str(source), mask_path=str(mask),
        prompt="Make selected facial details more realistic",
        model="auto", quality="standard", seed=12,
    ))
    assert captures == [{
        "mask_size": (256, 256),
        "corner": 0,
        "center": 255,
        "auto_mask": None,
    }]
    assert result["source_image_id"] == "1781634000-abc123abc123"
    assert result["model"] == "mflux-osaurus-qwen-image-2.1-edit"
    assert result["id"] != result["source_image_id"]
    assert source.is_file()


def test_empty_black_mask_rejected_without_running_model(local_editor):
    source, mask, captures = local_editor
    Image.new("L", (256, 256), 0).save(mask)
    with pytest.raises(HTTPException) as exc:
        service._edit_result(service.Edit(
            source_path=str(source), mask_path=str(mask),
            prompt="Change the marked area",
        ))
    assert exc.value.status_code == 422
    assert "keinen markierten Bereich" in str(exc.value.detail)
    assert captures == []


def test_different_mask_dimensions_are_rejected(local_editor):
    source, mask, captures = local_editor
    Image.new("L", (128, 128), 255).save(mask)
    with pytest.raises(HTTPException, match="Größe"):
        service._edit_result(service.Edit(
            source_path=str(source), mask_path=str(mask),
            prompt="Modify selected area",
        ))
    assert captures == []
