"""CPU-only safety and media validation checks for the opt-in real runner."""
import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location('real_acceptance', Path(__file__).parent / 'acceptance/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_acceptance_rejects_remote_targets_and_credentials():
    for target in ['https://127.0.0.1:8090', 'http://example.com', 'http://user:password@localhost:8090']:
        with pytest.raises(runner.argparse.ArgumentTypeError):
            runner.loopback_url(target)
    assert runner.loopback_url('http://127.0.0.1:8090/') == 'http://127.0.0.1:8090'


def test_image_validation_rejects_uniform_and_corrupt_bytes():
    with pytest.raises(Exception):
        runner.inspect_image(b'not an image' * 20)
    output = io.BytesIO()
    Image.new('RGB', (128, 128), 'red').save(output, format='PNG')
    with pytest.raises(AssertionError, match='uniform'):
        runner.inspect_image(output.getvalue())
    image = Image.new('RGB', (128, 128), 'red')
    image.putpixel((32, 32), (0, 0, 0))
    output = io.BytesIO()
    image.save(output, format='PNG')
    assert runner.inspect_image(output.getvalue())['width'] == 128


def test_advertised_broken_service_fails_and_absent_service_skips(monkeypatch):
    acceptance = object.__new__(runner.Acceptance)
    acceptance.probe_errors = {'speech': (True, 'unreachable')}
    with pytest.raises(AssertionError, match='advertised online'):
        acceptance.readiness('speech')
    acceptance.probe_errors['speech'] = (False, 'unreachable')
    with pytest.raises(runner.Skip, match='unavailable'):
        acceptance.readiness('speech')


def test_cancel_cleanup_refuses_foreign_jobs(tmp_path):
    acceptance = object.__new__(runner.Acceptance)
    acceptance.context = acceptance.browser = acceptance.playwright = None
    acceptance.jobs = [('video', 'a' * 24)]
    acceptance.chat_id = 'acceptance-own'
    calls = []
    def json(method, path, *args, **kwargs):
        calls.append((method, path))
        return {'status': 'generating', 'data': {'job': {'chat_id': 'foreign'}}}
    acceptance.json = json
    with pytest.raises(AssertionError, match='foreign'):
        acceptance.cleanup()
    assert calls == [('GET', '/api/mlx/video-jobs/' + 'a' * 24)]


def test_poll_timeout_reports_job_status_phase_and_progress(tmp_path, monkeypatch):
    acceptance = object.__new__(runner.Acceptance)
    acceptance.root = tmp_path
    acceptance.json = lambda *a, **kw: {'status': 'generating', 'data': {'job': {
        'id': 'a' * 24, 'status': 'generating', 'phase': 'denoising', 'progress': .25}}}
    clock = iter([0, 0, 0, 2])
    monkeypatch.setattr(runner.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(runner.time, 'sleep', lambda _: None)
    with pytest.raises(AssertionError, match='denoising.*0.25'):
        acceptance.poll('video', 'a' * 24, 1)


def test_preview_budget_accepts_ltx_first_frame_and_rejects_production():
    artifact = {'quality': 'preview', 'resolution': 'preview', 'duration': 2.125, 'fps': 8, 'width': 384, 'height': 256}
    runner.inspect_preview(artifact)
    with pytest.raises(AssertionError, match='frame budget'):
        runner.inspect_preview(dict(artifact, duration=5))
    with pytest.raises(AssertionError, match='resolution'):
        runner.inspect_preview(dict(artifact, width=1024))
    with pytest.raises(AssertionError, match='not a Preview'):
        runner.inspect_preview(dict(artifact, quality='standard'))
