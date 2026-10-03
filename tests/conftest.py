import pytest


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
