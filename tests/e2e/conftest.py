import re
"""Real production web process, isolated Agent transport and strict browser diagnostics."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from .harness import AgentFixture

ROOT = Path(__file__).resolve().parents[2]


def listener():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen()
    return sock


@pytest.fixture(scope='session')
def web(tmp_path_factory):
    agent = AgentFixture()
    agent_socket, web_socket = listener(), listener()
    agent_url = f'http://127.0.0.1:{agent_socket.getsockname()[1]}'
    web_url = f'http://127.0.0.1:{web_socket.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(agent.app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [agent_socket]}, daemon=True)
    thread.start()
    log_path = tmp_path_factory.mktemp('e2e-web') / 'server.log'
    env = dict(os.environ, AGENT_URL=agent_url, MLX_ALLOWED_HOSTS='127.0.0.1,localhost',
               PYTHONDONTWRITEBYTECODE='1')
    with log_path.open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.entrypoint:app',
                                    '--fd', str(web_socket.fileno()), '--log-level', 'warning'],
                                   cwd=ROOT, env=env, pass_fds=(web_socket.fileno(),), stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urllib.request.urlopen(web_url + '/api/health', timeout=.5) as response:
                        assert response.status == 200
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(log_path.read_text())
                    time.sleep(.05)
            yield web_url, agent
        finally:
            agent.speech_gate.set()
            agent.stream_gate.set()
            agent.model_system_gate.set()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            server.should_exit = True
            thread.join(5)
            agent_socket.close()
            web_socket.close()


@pytest.fixture
def browser():
    # A fresh Chromium process per test isolates renderer/Playwright state.
    # Context-only isolation previously left a shared browser alive for all 82 cases.
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, 'report_' + report.when, report)


def navigate_chat_page(page, url):
    """Require the genuine composer and CDN libraries after bounded navigation.

    The local navigation commit is not browser 'load'; every functional
    prerequisite remains mandatory, and exceptions must fail the E2E test.
    """
    # The production HTML contains third-party parser-blocking CDN
    # scripts. Waiting for the full browser "load" event can leave the
    # local E2E fixture dependent on unrelated CDN activity. Commit is
    # sufficient to confirm navigation; then require the real composer
    # and the loaded app controllers before executing any assertion.
    # This never skips missing dependencies or test failures.
    page.goto(url + '/chat', wait_until='commit', timeout=15000)
    page.locator('#input').wait_for(timeout=10000)
    page.wait_for_function(
        """() => (
            typeof window.marked?.parse === 'function' &&
            typeof window.DOMPurify?.sanitize === 'function' &&
            typeof window.hljs?.highlightElement === 'function' &&
            typeof window.MLXChatSessions?.currentSession === 'function' &&
            typeof window.MLXChatRendering?.renderMessages === 'function' &&
            typeof window.MLXChatGeneration?.sendMessage === 'function'
        )""",
        timeout=10000,
    )

@pytest.fixture(params=[(1440, 1000), (390, 844)], ids=['desktop', 'mobile'])
def ui(request, browser, web):
    url, agent = web
    agent.reset()
    width, height = request.param
    artifact = ROOT / 'test-results' / re.sub(r'[^A-Za-z0-9_.-]+', '_', request.node.name)
    artifact.mkdir(parents=True, exist_ok=True)
    for file in artifact.iterdir():
        file.unlink()
    print(f'E2E PHASE {request.node.nodeid}: context.create', flush=True)
    video_enabled = os.environ.get('MLX_E2E_VIDEO', '0') != '0'
    tracing_enabled = os.environ.get('MLX_E2E_TRACING', '1') != '0'
    print(f'E2E DIAGNOSTICS video={video_enabled} tracing={tracing_enabled}', flush=True)
    context_options = {'viewport': {'width': width, 'height': height},
                       'permissions': ['clipboard-read', 'clipboard-write']}
    if video_enabled:
        context_options['record_video_dir'] = str(artifact)
    context = browser.new_context(**context_options)
    if tracing_enabled:
        print(f'E2E PHASE {request.node.nodeid}: tracing.start', flush=True)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(8000)
    errors, console, network = [], [], []
    allowed = []

    def message(msg):
        console.append({'type': msg.type, 'text': msg.text})
        if msg.type == 'error' and not any(pattern in msg.text for pattern in allowed):
            errors.append(msg.text)

    page.on('console', message)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: network.append({'method': response.request.method,
                                                        'url': response.url, 'status': response.status}))
    page.on('requestfailed', lambda req: network.append({'method': req.method, 'url': req.url,
                                                       'failure': req.failure}))
    verified = False
    try:
        print(f'E2E PHASE {request.node.nodeid}: page.goto', flush=True)
        navigate_chat_page(page, url)
        print(f'E2E PHASE {request.node.nodeid}: test.body', flush=True)
        yield page, agent, allowed
        print(f'E2E PHASE {request.node.nodeid}: postconditions', flush=True)
        assert not errors, 'Browser errors: ' + '\n'.join(errors)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
        verified = True
    finally:
        print(f'E2E PHASE {request.node.nodeid}: cleanup.begin', flush=True)
        failed = not verified or not hasattr(request.node, 'report_call') or request.node.report_call.failed
        cleanup_errors = []

        def cleanup_step(name, action):
            # Diagnostics must never prevent the browser from being closed.
            try:
                action()
            except Exception as exc:
                cleanup_errors.append({'step': name, 'error': repr(exc)})

        try:
            if failed:
                cleanup_step('screenshot', lambda: page.screenshot(
                    path=str(artifact / 'screenshot.png'), full_page=True, timeout=5000))
                cleanup_step('console', lambda: (artifact / 'console.json').write_text(
                    json.dumps(console, indent=2)))
                cleanup_step('network', lambda: (artifact / 'network.json').write_text(
                    json.dumps(network, indent=2)))
                cleanup_step('agent', lambda: (artifact / 'agent.json').write_text(
                    json.dumps(agent.calls, indent=2)))
            try:
                if tracing_enabled:
                    print(f'E2E PHASE {request.node.nodeid}: tracing.stop', flush=True)
                    cleanup_step('tracing.stop', lambda: context.tracing.stop(
                        path=str(artifact / 'trace.zip') if failed else None))
            finally:
                print(f'E2E PHASE {request.node.nodeid}: context.close', flush=True)
                cleanup_step('context.close', context.close)
        finally:
            # Gates must be released even if screenshots, tracing, or closing fail.
            agent.speech_gate.set()
            agent.stream_gate.set()
            agent.model_system_gate.set()
            if cleanup_errors:
                (artifact / 'cleanup-errors.json').write_text(
                    json.dumps(cleanup_errors, indent=2))
            elif not failed:
                for file in artifact.iterdir():
                    file.unlink()
                artifact.rmdir()
        print(f'E2E PHASE {request.node.nodeid}: cleanup.end', flush=True)
        if cleanup_errors and not failed:
            pytest.fail('E2E browser cleanup failed: ' + json.dumps(cleanup_errors))
