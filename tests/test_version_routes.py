import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import version_routes


def test_version_file_matches_release(monkeypatch):
    """Prevent VERSION, README and CHANGELOG drifting during future releases."""
    monkeypatch.delenv("MLX_NOBBY_VERSION", raising=False)
    version = version_routes.VERSION_FILE.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), version

    readme = (version_routes.PROJECT_DIR / "README.md").read_text(encoding="utf-8")
    changelog = (version_routes.PROJECT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"release-v{version}-informational" in readme
    assert re.search(rf"^## v{re.escape(version)}$", changelog, re.MULTILINE)
    assert re.search(r"^## Unreleased\s*$", changelog, re.MULTILINE)
    assert changelog.index("## Unreleased") < changelog.index(f"## v{version}")

    info = version_routes.version_info()
    assert info["name"] == "MLX Nobby"
    assert info["version"] == version


def test_version_environment_overrides(monkeypatch):
    monkeypatch.setenv("MLX_NOBBY_VERSION", "9.9.9")
    monkeypatch.setenv("MLX_NOBBY_COMMIT", "abcdef1234567890")

    assert version_routes.version_info() == {
        "name": "MLX Nobby",
        "version": "9.9.9",
        "commit": "abcdef123456",
    }


def test_version_endpoint(monkeypatch):
    monkeypatch.setenv("MLX_NOBBY_VERSION", "1.4.0")
    monkeypatch.setenv("MLX_NOBBY_COMMIT", "release-build")

    app = FastAPI()
    version_routes.install_routes(app)
    response = TestClient(app).get("/api/version")

    assert response.status_code == 200
    assert response.json() == {
        "name": "MLX Nobby",
        "version": "1.4.0",
        "commit": "release-buil",
    }
