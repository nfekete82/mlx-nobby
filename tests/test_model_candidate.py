"""Dry CPU checks for optional candidate registration; no live model/download."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "model-candidate.py"
spec = importlib.util.spec_from_file_location("model_candidate", SCRIPT)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


def test_candidate_matches_published_mlx_model():
    info = candidate.CANDIDATES["dark-scarlett"]
    assert info["alias"] == "dark-scarlett-27b"
    assert info["repository"] == "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp"
    assert info["model_page"] == "https://huggingface.co/" + info["repository"]


def test_default_status_is_read_only_and_skips_subprocess(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Status must not execute shell/model/download commands")
    monkeypatch.setattr(candidate.subprocess, "run", forbidden)
    config = tmp_path / ".config" / "mlx-server"
    config.mkdir(parents=True)
    selected = config / "config"
    selected.write_text('MODEL="/original/qwen38"\nTHINKING=false\n')
    assert candidate.prepare("dark-scarlett", "status", home=tmp_path) == 0
    assert "not registered" in capsys.readouterr().out
    assert not (config / "models").exists()
    assert selected.read_text() == 'MODEL="/original/qwen38"\nTHINKING=false\n'


def test_register_uses_only_existing_alias_add_preserving_current_model(tmp_path, monkeypatch):
    config = tmp_path / ".config" / "mlx-server"
    config.mkdir(parents=True)
    selected = config / "config"
    selected.write_text('MODEL="/models/qwen38"\n')
    aliases = config / "models"
    aliases.write_text('coding=other/coder\n')
    called = []
    def fake_run(argv, **kwargs):
        called.append((argv, kwargs))
        assert argv[2:] == [
            "model", "add", "dark-scarlett-27b",
            "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp",
        ]
        assert kwargs["timeout"] == 30
        aliases.write_text(aliases.read_text() +
                           "dark-scarlett-27b=jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp\n")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(candidate.subprocess, "run", fake_run)
    assert candidate.prepare("dark-scarlett", "register", home=tmp_path,
                             launcher=tmp_path / "mlx") == 0
    assert len(called) == 1
    assert selected.read_text() == 'MODEL="/models/qwen38"\n'
    assert aliases.read_text().startswith("coding=other/coder")
    assert candidate.prepare("dark-scarlett", "register", home=tmp_path,
                             launcher=tmp_path / "mlx") == 0
    assert len(called) == 1  # idempotent


def test_alias_conflict_or_symlink_never_invokes_launcher(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe alias state must fail before executing any command")
    monkeypatch.setattr(candidate.subprocess, "run", forbidden)
    directory = tmp_path / ".config" / "mlx-server"
    directory.mkdir(parents=True)
    aliases = directory / "models"
    aliases.write_text("dark-scarlett-27b=another/model\n")
    with pytest.raises(ValueError, match="different"):
        candidate.prepare("dark-scarlett", "register", home=tmp_path)
    aliases.write_text("dark-scarlett-27b=A\ndark-scarlett-27b=B\n")
    with pytest.raises(ValueError, match="more than once"):
        candidate.prepare("dark-scarlett", "register", home=tmp_path)
    aliases.unlink()
    external = tmp_path / "foreign"
    external.write_text("secret")
    aliases.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        candidate.prepare("dark-scarlett", "register", home=tmp_path)
    assert external.read_text() == "secret"


def test_failure_does_not_continue_to_download_or_select(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1)
    monkeypatch.setattr(candidate.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        candidate.prepare("dark-scarlett", "register", home=tmp_path,
                          launcher=tmp_path / "mlx")
    assert not candidate.alias_file(tmp_path).exists()


def test_cli_requires_explicit_candidate_and_action(capsys):
    with pytest.raises(SystemExit):
        candidate.main(["unknown", "register"])
    with pytest.raises(SystemExit):
        candidate.main(["dark-scarlett", "install"])
