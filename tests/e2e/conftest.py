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


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, 'report_' + report.when, report)


@pytest.fixture(params=[(1440, 1000), (390, 844)], ids=['desktop', 'mobile'])
def ui(request, browser, web):
    url, agent = web
    agent.reset()
    width, height = request.param
    artifact = ROOT / 'test-results' / request.node.name
    artifact.mkdir(parents=True, exist_ok=True)
    for file in artifact.iterdir():
        file.unlink()
    context = browser.new_context(viewport={'width': width, 'height': height},
                                  permissions=['clipboard-read', 'clipboard-write'],
                                  record_video_dir=str(artifact))
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
        page.goto(url + '/chat')
        page.locator('#input').wait_for()
        yield page, agent, allowed
        assert not errors, 'Browser errors: ' + '\n'.join(errors)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
        verified = True
    finally:
        failed = not verified or not hasattr(request.node, 'report_call') or request.node.report_call.failed
        if failed:
            page.screenshot(path=str(artifact / 'screenshot.png'), full_page=True)
            (artifact / 'console.json').write_text(json.dumps(console, indent=2))
            (artifact / 'network.json').write_text(json.dumps(network, indent=2))
            (artifact / 'agent.json').write_text(json.dumps(agent.calls, indent=2))
        context.tracing.stop(path=str(artifact / 'trace.zip') if failed else None)
        context.close()
        if not failed:
            for file in artifact.iterdir():
                file.unlink()
            artifact.rmdir()
        agent.speech_gate.set()
        agent.stream_gate.set()
        agent.model_system_gate.set()
