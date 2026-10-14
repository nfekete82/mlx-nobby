"""Qwen Image 2.1 Edit MFLUX subprocess telemetry never records private CLI data."""
from pathlib import Path
from unittest.mock import patch

import pytest

import image_providers


@pytest.mark.parametrize("low_ram,logs", [(True, True), (False, False)])
def test_qwen21_edit_reports_content_free_process_timing(tmp_path, low_ram, logs):
    model = {
        "id": "mflux-osaurus-qwen-image-2.1-edit", "provider": "mflux",
        "model_family": "qwen-image21-edit",
    }
    params = {
        "prompt": "A private image prompt", "source_path": "/private/source.png",
        "width": 512, "height": 512, "steps": 20, "guidance": 1, "seed": 42,
    }
    output = tmp_path / "edited.png"
    events = []
    command = ["/fake/mflux-generate-qwen-edit", "--mlx-cache-limit-gb", "4"]
    if low_ram:
        command.append("--low-ram")

    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, log_stream):
            self.log_stream = log_stream
            self.polls = 0

        def communicate(self, input=None, timeout=None):
            self.polls += 1
            if logs and self.polls == 1:
                raise image_providers.subprocess.TimeoutExpired("mflux", timeout)
            if logs:
                self.log_stream.write(b"100%|##########| 20/20 [00:40<00:00, 2.00s/it]\\n")
                self.log_stream.flush()
            output.write_bytes(b"mock png")

        def poll(self):
            return 0

    def fake_popen(command, **kwargs):
        if logs:
            kwargs["stdout"].write(b"loading model\\n")
            kwargs["stdout"].write(b"  0%|          | 0/20 [00:00<?, ?it/s]\\r")
            kwargs["stdout"].flush()
        return FakeProcess(kwargs["stdout"])

    with patch.object(image_providers, "availability", return_value=(True, "ok")), \
         patch.object(image_providers, "mflux_command", return_value=command), \
         patch.object(image_providers, "probe_mflux_cli", return_value={"supported_flags": set()}), \
         patch.object(image_providers.subprocess, "Popen", side_effect=fake_popen), \
         patch.object(image_providers, "terminate_process_tree"), \
         patch.object(image_providers, "_validate_provider_output"), \
         patch.object(image_providers, "_maybe_quality_upscale"):
        image_providers.run_provider(
            model, params, output, progress_callback=events.append
        )

    timing = next(entry["provider_timing"] for entry in events if "provider_timing" in entry)
    assert timing["schema"] == 1
    assert timing["provider"] == "mflux"
    assert timing["fresh_process"] is True
    assert timing["low_ram"] is low_ram
    assert timing["mflux_cache_limit_gb"] == 4.0
    assert timing["process_wall_ms"] >= 0
    assert timing["process_spawn_ms"] >= 0
    assert (timing["first_output_ms"] is not None) is logs
    assert (timing["tqdm_first_ms"] is not None) is logs
    assert (timing["tqdm_complete_ms"] is not None) is logs
    assert (timing["tqdm_window_ms"] is not None) is logs
    assert timing["tqdm_first_step"] == (0 if logs else None)
    if logs:
        assert 0 <= timing["tqdm_first_ms"] <= timing["tqdm_complete_ms"]
        assert timing["tqdm_window_ms"] >= 0
    assert timing["exit_code"] == 0
    assert timing["steps"] == 20
    assert timing["width"] == 512 and timing["height"] == 512
    assert "prompt" not in str(timing)
    assert "/private" not in str(timing)
    assert "source_path" not in str(timing)
