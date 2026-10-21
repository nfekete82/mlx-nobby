"""CPU-only admission launcher compatibility: no real server, models or GPU."""
from __future__ import annotations

import importlib
import os
import sys
import types
from unittest import mock

import pytest

from ltx_lab import guarded_serve


def test_lifecycle_requires_chat_role_and_explicit_enable(monkeypatch):
    for role, flag, args in (
        ("router", "1", ["-m", "model_lifecycle_launcher", "server"]),
        ("chat", "0", ["-m", "model_lifecycle_launcher", "server"]),
        ("chat", "1", ["-m", "model_lifecycle_launcher"]),
    ):
        monkeypatch.setenv("MLX_LIFECYCLE_ENABLE", flag)
        with pytest.raises(SystemExit):
            guarded_serve.main(["--role", role, "--", *args])


def test_lifecycle_preserves_original_server_and_wraps_with_admission(monkeypatch):
    """Exercise nested monkeypatches from both real launchers; suppress imports."""
    calls = []
    upstream_app = object()
    lifecycle_app = object()
    wrapped_app = object()
    uvicorn = types.ModuleType("uvicorn")
    importer = types.ModuleType("uvicorn.importer")
    importer.import_from_string = lambda name: (
        lifecycle_app if name == "model_lifecycle_asgi:app"
        else upstream_app if name == "mlx_vlm.server:app" else None
    )
    cli_module = types.ModuleType("uvicorn.main")

    def real_run(application, *args, **kwargs):
        calls.append(("uvicorn", application, kwargs))
    uvicorn.run = real_run
    cli_module.run = real_run
    uvicorn.importer = importer
    mlx_vlm = types.ModuleType("mlx_vlm")
    mlx_vlm.__path__ = []
    vlm_utils = types.ModuleType("mlx_vlm.utils")
    vlm_utils.get_model_path = lambda p: p
    vlm_server = types.ModuleType("mlx_vlm.server")
    vlm_server.__path__ = []
    vlm_app = types.ModuleType("mlx_vlm.server.app")
    vlm_app.app = upstream_app
    vlm_cli = types.ModuleType("mlx_vlm.server.cli")

    def fake_vlm_main():
        import uvicorn as current_uvicorn
        current_uvicorn.run("mlx_vlm.server:app", host="127.0.0.1", port=8000)
    vlm_cli.main = fake_vlm_main
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.__path__ = []
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = True
    constants.HF_HUB_CACHE = "/tmp/test-hub-cache"
    fake_hub.constants = constants
    monkeypatch.setenv("MLX_LIFECYCLE_ENABLE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    for name, module in {
        "uvicorn": uvicorn, "uvicorn.importer": importer, "uvicorn.main": cli_module,
        "mlx_vlm": mlx_vlm, "mlx_vlm.utils": vlm_utils,
        "mlx_vlm.server": vlm_server, "mlx_vlm.server.app": vlm_app,
        "mlx_vlm.server.cli": vlm_cli,
        "huggingface_hub": fake_hub, "huggingface_hub.constants": constants,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    mlx_vlm.utils = vlm_utils
    mlx_vlm.server = vlm_server
    vlm_server.app = vlm_app
    vlm_server.cli = vlm_cli

    def wrapped(application, **kwargs):
        calls.append(("admission", application, kwargs))
        return wrapped_app

    with mock.patch.object(guarded_serve, "Gate") as gate, \
         mock.patch.object(guarded_serve, "AdmissionMiddleware", side_effect=wrapped):
        guarded_serve.main([
            "--role", "chat", "--", "-m", "model_lifecycle_launcher", "server",
            "--host", "127.0.0.1", "--port", "8000",
        ])
    assert calls == [
        ("admission", lifecycle_app, mock.ANY),
        ("uvicorn", wrapped_app, {"host": "127.0.0.1", "port": 8000}),
    ]
    assert uvicorn.run is real_run
    assert cli_module.run is real_run
    gate.assert_called_once()
