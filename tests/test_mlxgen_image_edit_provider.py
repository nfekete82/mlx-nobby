"""Qwen Image Edit 2511 uses isolated MLX-Gen, never the incompatible MFLUX loader."""
from pathlib import Path
from unittest.mock import patch

import image_registry
import image_providers


def test_builtin_and_persisted_qwen_edit_use_mlxgen():
    model = next(m for m in image_registry.builtin_models()
                 if m["id"] == image_registry.QWEN_IMAGE_EDIT_ID)
    assert model["provider"] == "mlxgen"
    old = {**model, "provider": "mflux", "enabled": True}
    migrated = image_registry._canonicalize_known_builtin(
        old, {model["id"]: model})
    assert migrated["provider"] == "mlxgen"
    assert migrated["enabled"] is True


def test_mlxgen_requires_local_weights_and_executable(tmp_path):
    model = next(m for m in image_registry.builtin_models()
                 if m["id"] == image_registry.QWEN_IMAGE_EDIT_ID)
    with patch.object(image_providers, "model_directory", return_value=tmp_path):
        ok, reason = image_providers.availability(model)
        assert not ok and "Cache" in reason
    for directory in ("text_encoder", "transformer", "vae"):
        (tmp_path / directory).mkdir()
    (tmp_path / "transformer" / "0.safetensors").write_bytes(b"fixture")
    runner = tmp_path / "mlxgen"
    runner.write_text("#!/bin/sh\nexit 0\n")
    runner.chmod(0o755)
    with patch.object(image_providers, "model_directory", return_value=tmp_path), \
         patch.object(image_providers, "MLXGEN_BIN", runner):
        ok, reason = image_providers.availability(model)
        assert ok and "MLX-Gen" in reason


def test_mlxgen_edit_command_uses_source_and_local_model(tmp_path):
    model = next(m for m in image_registry.builtin_models()
                 if m["id"] == image_registry.QWEN_IMAGE_EDIT_ID)
    source = tmp_path / "source.png"
    source.write_bytes(b"fixture")
    output = tmp_path / "result.png"
    runner = tmp_path / "mlxgen"
    runner.write_text("#!/bin/sh\nexit 0\n")
    runner.chmod(0o755)
    for directory in ("text_encoder", "transformer", "vae"):
        (tmp_path / directory).mkdir()
    (tmp_path / "transformer" / "0.safetensors").write_bytes(b"fixture")
    params = {"source_path": str(source), "prompt": "Make the tree orange",
              "width": 512, "height": 512, "steps": 4, "guidance": 3.5, "seed": 42}
    captured = {}
    class FakeProcess:
        returncode = 0
        pid = 1
        def communicate(self, input=None, timeout=None):
            output.write_bytes(b"fake png")
        def poll(self):
            return 0
    def start(command, **kwargs):
        captured["command"] = command
        return FakeProcess()
    with patch.object(image_providers, "model_directory", return_value=tmp_path), \
         patch.object(image_providers, "MLXGEN_BIN", runner), \
         patch.object(image_providers.subprocess, "Popen", side_effect=start), \
         patch.object(image_providers, "terminate_process_tree"), \
         patch.object(image_providers, "_validate_provider_output"), \
         patch.object(image_providers, "_maybe_quality_upscale"):
        image_providers.run_provider(model, params, output)
    command = captured["command"]
    assert command[:2] == [str(runner), "generate"]
    assert command[command.index("--image") + 1] == str(source)
    assert command[command.index("--model") + 1] == "AbstractFramework/qwen-image-edit-2511-4bit"
    assert "--task" not in command and "--i2i-mode" not in command
    assert "--prompt" in command and "--output" in command


def test_mlxgen_model_is_not_a_general_purpose_provider():
    model = next(m for m in image_registry.builtin_models()
                 if m["id"] == image_registry.QWEN_IMAGE_EDIT_ID)
    model["repository"] = "other/repository"
    try:
        image_registry.ImageModel(**model)
        assert False, "Unexpected unrestricted provider accepted"
    except ValueError:
        pass
