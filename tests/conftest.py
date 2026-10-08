import os
from pathlib import Path
import tempfile
from unittest import mock

import pytest


def pytest_sessionstart(session):
    """Keep CPU discovery/imports and runtime leases off the running local app."""
    if session.config.getoption('--e2e'):
        return
    directory = tempfile.TemporaryDirectory(prefix='mlx-pytest-home-')
    root = Path(directory.name)
    home_patch = mock.patch.object(Path, 'home', return_value=root)
    environment_patch = mock.patch.dict(os.environ, {
        'MLX_RUNTIME_COORDINATOR_LOCK': str(root / 'runtime.lock'),
        'MLX_RUNTIME_COORDINATOR_STATE_DIR': str(root / 'runtime-state'),
    })
    home_patch.start()
    environment_patch.start()
    session.config._mlx_isolation = (directory, home_patch, environment_patch)


def pytest_sessionfinish(session, exitstatus):
    isolation = getattr(session.config, '_mlx_isolation', None)
    if isolation:
        directory, home_patch, environment_patch = isolation
        environment_patch.stop()
        home_patch.stop()
        directory.cleanup()



def pytest_addoption(parser):
    parser.addoption('--e2e', action='store_true', help='Run Chromium acceptance tests')


def pytest_ignore_collect(collection_path, config):
    if collection_path.name == 'e2e' and not config.getoption('--e2e'):
        return True


@pytest.fixture
def mflux_cli_contract(monkeypatch):
    """Provider unit tests use a CLI contract independently of host Metal access.

    The real probe and missing-flag contracts are exercised in test_mflux_capabilities.
    """
    import mflux_capabilities
    import image_providers
    flags = frozenset('--model --base-model --prompt --width --height --steps --guidance --seed --output --quantize --image-paths --lora-paths --lora-scales --low-ram --mlx-cache-limit-gb'.split())
    probe = lambda _executable: {'available': True, 'supported_flags': flags, 'version': '0.19.1', 'error': None}
    monkeypatch.setattr(mflux_capabilities, 'probe_mflux_cli', probe)
    monkeypatch.setattr(image_providers, 'probe_mflux_cli', probe)

@pytest.fixture(autouse=True)
def stable_runtime_memory_snapshot(monkeypatch, request):
    """Keep non-memory tests independent from the CI runner's physical RAM.

    The dedicated runtime budget/coordinator suites exercise the real memory
    accounting and explicit critical snapshots. All other tests use a roomy,
    deterministic Apple-unified-memory snapshot so mocked model generation is
    not rejected merely because the GitHub macOS runner is small.
    """
    if request.node.path.name in {
        "test_runtime_budget.py",
        "test_runtime_coordinator.py",
    }:
        return

    try:
        import runtime_coordinator
    except ImportError:
        return

    snapshot = {
        "total_gb": 48.0,
        "available_estimate_gb": 36.0,
        "used_estimate_gb": 12.0,
        "free_percent": 75.0,
        "reserve_gb": 6.0,
        "headroom_gb": 30.0,
        "swap_total_gb": 0.0,
        "swap_used_gb": 0.0,
        "pressure": "normal",
    }
    monkeypatch.setattr(
        runtime_coordinator,
        "memory_budget_snapshot",
        lambda: dict(snapshot),
    )

