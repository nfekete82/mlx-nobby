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
    acceptance.browser_history_before = None
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


def test_browser_history_boundary_only_exposes_owned_chat():
    from types import SimpleNamespace
    acceptance = object.__new__(runner.Acceptance)
    acceptance.chat_id = 'acceptance-own'
    acceptance.args = SimpleNamespace(url='http://127.0.0.1:8090')
    acceptance.history_violations = []
    calls = []

    class Route:
        def __init__(self, method, path, body=None):
            self.request = SimpleNamespace(method=method, url=acceptance.args.url + path,
                                           post_data_json=body)
        def fetch(self, **kwargs):
            calls.append(('fetch', kwargs))
            return SimpleNamespace(ok=True, json=lambda: {'chat': {'id': acceptance.chat_id}})
        def fulfill(self, **kwargs):
            calls.append(('fulfill', kwargs))
        def continue_(self):
            calls.append(('continue',))

    acceptance.route_browser_history(Route('GET', '/api/mlx/chats'))
    assert calls == [('fetch', {'url': acceptance.args.url + '/api/mlx/chats/acceptance-own'}),
                     ('fulfill', {'json': {'chats': [{'id': 'acceptance-own'}], 'deleted_ids': []}})]
    calls.clear()
    acceptance.route_browser_history(Route('PUT', '/api/mlx/chats/acceptance-own', {'id': 'acceptance-own'}))
    assert calls == [('continue',)]
    for method, path, body in [('GET', '/api/mlx/chats/foreign', None),
                               ('PUT', '/api/mlx/chats/foreign', {'id': 'foreign'}),
                               ('DELETE', '/api/mlx/chats', None),
                               ('DELETE', '/api/mlx/chats/acceptance-own', None),
                               ('POST', '/api/mlx/chats/acceptance-own/reset', None),
                               ('PUT', '/api/mlx/chats/acceptance-own', {'id': 'foreign'})]:
        calls.clear()
        acceptance.route_browser_history(Route(method, path, body))
        assert calls == [('fulfill', {'status': 403, 'json': {'detail': 'Acceptance history boundary'}})]
    assert len(acceptance.history_violations) == 6


@pytest.mark.parametrize('change', ['revision', 'updated', 'title', 'messages', 'deleted', 'new'])
def test_foreign_history_comparison_detects_all_changes(tmp_path, change):
    import copy
    acceptance = object.__new__(runner.Acceptance)
    acceptance.root = tmp_path
    acceptance.history_checks = []
    acceptance.history_violations = []
    before = {'foreign': {'id': 'foreign', 'revision': 1, 'updated': 2, 'title': 'New chat', 'messages': []}}
    after = copy.deepcopy(before)
    if change == 'deleted':
        after.clear()
    elif change == 'new':
        after['generic-new'] = {'id': 'generic-new'}
    else:
        after['foreign'][change] = 'changed'
    acceptance.browser_history_before = before
    acceptance.foreign_history = lambda: after
    with pytest.raises(AssertionError, match='Foreign chat history changed'):
        acceptance.verify_browser_history('fixture')
    assert acceptance.history_checks[0]['identical'] is False
    assert 'messages' not in (tmp_path / 'history-isolation.json').read_text()
