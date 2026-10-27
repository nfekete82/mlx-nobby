"""Real subprocess pipes; no image models, GPU work or native services."""

import subprocess
import sys
import threading
import time

from PIL import Image
import pytest

import image_providers as providers


@pytest.mark.parametrize("output", ["", "partial progress", None])
def test_silent_or_unterminated_output_does_not_block_deadline(output, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER_POLL_INTERVAL", 0.02)
    code = (
        "import os,time; os.close(1); time.sleep(2)" if output is None else
        f"import sys,time; sys.stdout.write({output!r}); sys.stdout.flush(); time.sleep(2)"
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE, start_new_session=True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="test deadline"):
            list(providers.iter_process_lines(
                process, cancel_event=None, deadline=started + 0.2,
                timeout_message="test deadline",
            ))
        assert time.monotonic() - started < 1.5
        assert process.stdout.closed
    finally:
        providers.terminate_process_tree(process)


def test_unterminated_diagnostic_output_is_split_into_bounded_fragments():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 524288)"],
        stdout=subprocess.PIPE, start_new_session=True,
    )
    try:
        lines = list(providers.iter_process_lines(
            process, cancel_event=None, deadline=time.monotonic() + 3,
            timeout_message="test deadline",
        ))
        assert "".join(lines) == "x" * 524288
        assert max(map(len, lines)) <= 65536
    finally:
        providers.terminate_process_tree(process)


def test_progress_carriage_returns_utf8_and_trailing_output(monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER_POLL_INTERVAL", 0.02)
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write('10%\\r50%\\r\\nGrüße\\n100%'.encode())"],
        stdout=subprocess.PIPE, start_new_session=True,
    )
    try:
        lines = list(providers.iter_process_lines(
            process, cancel_event=None, deadline=time.monotonic() + 3,
            timeout_message="test deadline",
        ))
        assert [line for line in lines if line] == ["10%", "50%", "Grüße", "100%"]
        assert process.returncode == 0
    finally:
        providers.terminate_process_tree(process)


@pytest.mark.parametrize("quality_plus", [False, True])
def test_both_upscale_paths_cancel_and_reap_a_silent_child(tmp_path, monkeypatch, quality_plus):
    import image_service as service

    source = tmp_path / "source.png"
    Image.new("RGB", (32, 24), "white").save(source)
    monkeypatch.setattr(providers, "PROVIDER_POLL_INTERVAL", 0.02)
    monkeypatch.setattr(service, "OUTPUT", tmp_path)
    monkeypatch.setattr(service, "validate_edit_source", lambda path: source)
    monkeypatch.setattr(service.runtime_coordinator, "ensure_model_load_allowed", lambda workload: None)
    monkeypatch.setattr(providers, "quality_upscale_available", lambda: True)
    command = lambda *a, **kw: [sys.executable, "-c", "import time; time.sleep(2)"]
    monkeypatch.setattr(service, "realesrgan_command", command)
    monkeypatch.setattr(providers, "realesrgan_command", command)
    cancel = threading.Event()
    seen = []
    timer = None

    def changed(process):
        nonlocal timer
        seen.append(process)
        if process is not None:
            timer = threading.Timer(0.1, cancel.set)
            timer.start()

    started = time.monotonic()
    try:
        with pytest.raises(providers.ProviderCancelled):
            if quality_plus:
                providers._maybe_quality_upscale(
                    {"quality": "quality"}, source,
                    cancel_event=cancel, process_callback=changed,
                )
            else:
                service._upscale_result(
                    service.Upscale(source_path=str(source)),
                    provider_options={"cancel_event": cancel, "process_callback": changed},
                )
        assert time.monotonic() - started < 1.5
        assert len(seen) == 2 and seen[-1] is None
        assert seen[0].poll() is not None
        assert seen[0].stdout.closed
        assert service._running is None
        assert not list(tmp_path.glob(".*-quality-*.png"))
    finally:
        if timer:
            timer.cancel()
        if seen and seen[0] is not None:
            providers.terminate_process_tree(seen[0])
