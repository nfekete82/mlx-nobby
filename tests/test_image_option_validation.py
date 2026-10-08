"""Mode-specific image option validation must never launch invalid image jobs."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent import app as agent


@pytest.mark.parametrize(
    "operation,valid",
    [
        ("generate", {"negative_prompt": "low quality", "width": 768, "height": 1024, "auto_size": True}),
        ("edit", {"model": "auto", "seed": 123, "guidance": 4.0}),
        ("reference", {"negative_prompt": "low quality", "width": 768, "auto_size": True}),
    ],
)
def test_image_option_contract_accepts_supported_fields(operation, valid):
    assert agent._validated_image_options(valid, operation) == valid


@pytest.mark.parametrize(
    "operation,field",
    [
        ("generate", "format"),
        ("edit", "negative_prompt"),
        ("edit", "width"),
        ("edit", "auto_size"),
        ("reference", "format"),
    ],
)
def test_image_option_contract_names_rejected_field_without_leaking_value(
    operation, field, capsys
):
    secret = "secret user prompt never print this"
    with pytest.raises(HTTPException) as exc:
        agent._validated_image_options({field: secret}, operation)
    assert exc.value.status_code == 422
    assert field in exc.value.detail
    assert secret not in exc.value.detail
    logs = capsys.readouterr().out
    assert operation in logs and field in logs and secret not in logs


def test_generate_accepts_negative_prompt_and_rejects_stale_ui_parameters(monkeypatch):
    monkeypatch.setattr(
        agent, "translate_image_prompt_to_english", lambda _: "a detailed red lighthouse"
    )
    request = agent.ChatActionRequest(
        prompt="Erstelle ein Bild eines roten Leuchtturms.",
        image_options={"negative_prompt": "blurry", "model": "auto", "auto_size": True},
    )
    payload = agent._image_generate_payload(request)
    assert payload["negative_prompt"] == "blurry"
    assert payload["model"] == "auto"

    request.image_options["format"] = "landscape"
    with pytest.raises(HTTPException, match="Nicht unterstützte Bildparameter") as exc:
        agent._image_generate_payload(request)
    assert "format" in str(exc.value.detail)


def test_plain_edit_requires_edit_capable_options_not_session_negative(monkeypatch):
    monkeypatch.setattr(agent, "_image_source_path", lambda *_args, **_kw: Path("/tmp/source.png"))
    monkeypatch.setattr(agent, "translate_media_prompt_to_english", lambda text: text)
    request = agent.ChatActionRequest(
        prompt="Ändere die Farbe dieses Bildes in Rot.",
        image_options={"model": "auto", "seed": 21},
    )
    payload = agent._image_edit_payload(request)
    assert payload["model"] == "auto"
    assert payload["seed"] == 21
    assert payload["source_path"] == "/tmp/source.png"

    request.image_options["negative_prompt"] = "blurry"
    with pytest.raises(HTTPException) as exc:
        agent._image_edit_payload(request)
    assert "Bildbearbeitung" in exc.value.detail
    assert "negative_prompt" in exc.value.detail


def test_reference_generation_accepts_negative_prompt_and_dimensions(monkeypatch):
    monkeypatch.setattr(agent, "_image_source_path", lambda *_args, **_kw: Path("/tmp/reference.png"))
    monkeypatch.setattr(agent, "translate_media_prompt_to_english", lambda text: text)
    request = agent.ChatActionRequest(
        prompt="Erstelle ein neues Bild derselben Person in einem Garten.",
        reference_mode="same_identity",
        image_options={"negative_prompt": "blur", "auto_size": True, "width": 768, "height": 1024},
    )
    payload = agent._image_edit_payload(request)
    assert payload["negative_prompt"] == "blur"
    assert payload["width"] == 768
    assert payload["height"] == 1024
    assert payload["semantic_operation"] == "reference_generate"
