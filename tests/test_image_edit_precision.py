"""Precision Image Editing V2: no surprise masks, protected previews, honest audits."""
from pathlib import Path

from PIL import Image
import pytest

import image_edit_precision as precision
import image_service as service


@pytest.mark.parametrize("prompt,expected", [
    ("Mach den Pullover blau, aber verändere sonst nichts", "sweater"),
    ("Ändere die Farbe des T-Shirts in Rot, Hintergrund erhalten", "shirt"),
    ("Change the dress to green, keep the face", "dress"),
    ("Make the jacket black, preserve the rest", "jacket"),
    ("Färbe die Haare rot, aber sonst nichts ändern", "hair"),
    ("Replace the sky with a cloudy sky", "sky"),
    ("Verbessere die Beleuchtung", None),
    ("Mach den Pullover und die Hose blau", None),
    ("Nicht die Haare ändern, sondern den Hintergrund", None),
    ("Keep the shirt identical", None),
    ("Mach alles schöner", None),
    ("Show me what is in the picture", None),
    ("", None),
])
def test_mask_inference_is_explicit_and_conservative(prompt, expected):
    assert precision.infer_auto_mask_target(prompt) == expected


def test_local_reference_preview_is_private_and_exif_free(tmp_path):
    upload = tmp_path / "uploads" / "portrait.jpg"
    upload.parent.mkdir()
    Image.new("RGB", (1200, 1600), "navy").save(upload)
    output = tmp_path / "images"
    before = upload.read_bytes()
    image_id = precision.comparison_image_id(upload, output)
    assert image_id is not None
    assert len(image_id) == 23
    preview = output / f"{image_id}.png"
    assert preview.is_file()
    assert preview.stat().st_mode & 0o777 == 0o600
    with Image.open(preview) as image:
        assert image.size == (768, 1024)
        assert image.getexif() == {}
    assert upload.read_bytes() == before
    assert precision.comparison_image_id(preview, output) == image_id


def test_source_comparison_does_not_expose_unrelated_files(tmp_path):
    output = tmp_path / "images"
    output.mkdir()
    unrelated = tmp_path / "secret.png"
    Image.new("RGB", (512, 512)).save(unrelated)
    assert precision.original_image_id(unrelated, output) is None
    arbitrary = output / "not-an-image-id.png"
    Image.new("RGB", (512, 512)).save(arbitrary)
    assert precision.original_image_id(arbitrary, output) is None


def test_quality_advisory_flags_noop_but_never_certifies_success(tmp_path):
    source = tmp_path / "source.png"
    noop = tmp_path / "noop.png"
    changed = tmp_path / "changed.png"
    Image.new("RGB", (512, 512), "navy").save(source)
    Image.new("RGB", (512, 512), "navy").save(noop)
    Image.new("RGB", (512, 512), "yellow").save(changed)
    report = precision.image_change_advisory(source, noop)
    assert report == {"status": "review", "changed_fraction": 0.0}
    report = precision.image_change_advisory(source, changed)
    assert report["status"] == "review"
    assert report["changed_fraction"] == 1.0
    assert "passed" not in str(report).lower()


def test_edit_service_applies_precision_only_when_allowed(monkeypatch, tmp_path):
    image_source = tmp_path / "uploads" / "source.png"
    image_source.parent.mkdir()
    Image.new("RGB", (1024, 1024), "navy").save(image_source)
    output = tmp_path / "images"
    output.mkdir()
    model = {
        "id": "mflux-osaurus-qwen-image-2.1-edit",
        "provider": "mflux",
        "model_family": "qwen-image21-edit",
        "capabilities": ["image_edit", "auto_mask"],
        "default_steps": 20,
        "default_guidance": 1.0,
        "quantization": "q4",
        "loras": [],
    }
    seen = []
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(service, "_edit_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(service, "availability", lambda _: (True, "ok"))
    monkeypatch.setattr(service, "validate_edit_source", lambda _: image_source)
    monkeypatch.setattr(service.runtime_coordinator, "ensure_model_load_allowed", lambda *a: None)

    def provider(chosen, params, target, **kwargs):
        seen.append(dict(params))
        Image.new("RGB", (params["width"], params["height"]), "blue").save(target)

    monkeypatch.setattr(service, "run_provider", provider)
    request = dict(model=model["id"], source_path=str(image_source),
                   prompt="Mach den Pullover blau, aber verändere sonst nichts",
                   quality="quality", seed=42)
    result = service._edit_result(service.Edit(**request))
    assert seen[-1]["auto_mask"] == "sweater"
    assert "precision_edit" not in seen[-1]
    assert result["source_image_id"]
    assert (output / (result["source_image_id"] + ".png")).is_file()
    assert result["quality_check"]["status"] in {"review", "unverified"}

    service._edit_result(service.Edit(**request, precision_edit=False))
    assert seen[-1].get("auto_mask") is None

    service._edit_result(service.Edit(**request, auto_mask="jacket"))
    assert seen[-1].get("auto_mask") == "jacket"

    service._edit_result(service.Edit(**(request | {"prompt": "Improve the lighting"})))
    assert seen[-1].get("auto_mask") is None

    service._edit_result(service.Edit(**(request | {
        "semantic_operation": "reference_generate", "reference_mode": "resemblance",
    })))
    assert seen[-1].get("auto_mask") is None
