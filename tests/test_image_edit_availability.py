"""Regression coverage for automatic image edit availability diagnostics."""
from unittest.mock import patch

from fastapi import HTTPException

import image_service


def test_image_edit_has_no_configured_model():
    with patch.object(image_service.registry, "load_registry", return_value={
        "default_model": "generator", "models": [
            {"id": "generator", "enabled": True, "capabilities": ["text_to_image"]},
        ],
    }):
        try:
            image_service._edit_model("auto")
            assert False, "Expected an actionable 503"
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "konfiguriert" in exc.detail


def test_image_edit_configured_but_disabled():
    with patch.object(image_service.registry, "load_registry", return_value={
        "default_model": "edit", "models": [
            {"id": "edit", "enabled": False, "capabilities": ["image_edit"]},
        ],
    }):
        try:
            image_service._edit_model("auto")
            assert False, "Expected an actionable 503"
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "deaktiviert" in exc.detail


def test_image_edit_model_unavailable():
    model = {"id": "edit", "enabled": True, "capabilities": ["image_edit"]}
    with patch.object(image_service.registry, "load_registry", return_value={
        "default_model": "edit", "models": [model],
    }), patch.object(image_service, "availability", return_value=(False, "Missing weights")):
        try:
            image_service._edit_model("auto")
            assert False, "Expected an actionable 503"
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "Modellgewichte" in exc.detail


def test_image_edit_prefers_ready_model():
    models = [
        {"id": "first", "enabled": True, "capabilities": ["image_edit"]},
        {"id": "second", "enabled": True, "capabilities": ["image_edit"]},
    ]
    with patch.object(image_service.registry, "load_registry", return_value={
        "default_model": "first", "models": models,
    }), patch.object(image_service, "availability", side_effect=[
        (False, "Unavailable"), (True, "Ready"),
    ]):
        assert image_service._edit_model("auto")["id"] == "second"
