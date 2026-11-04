"""Safety regressions for the optional, local maintenance CLI."""
import importlib.util
import os
from pathlib import Path
import subprocess
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "maintenance.py"
spec = importlib.util.spec_from_file_location("mlx_maintenance", SCRIPT)
maintenance = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = maintenance
spec.loader.exec_module(maintenance)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "agent" / "log_rotation.py").write_text("# marker")
    (tmp_path / "scripts" / "agent-server.py").write_text("# marker")
    return tmp_path


def make_old(directory, days=20):
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / "summary.json"
    file.write_text('{"synthetic":true}')
    old = time.time() - days * 86400
    os.utime(file, (old, old))
    os.utime(directory, (old, old))
    return file


def test_only_known_old_artifacts_are_candidates(repo):
    eligible = repo / "artifacts" / "ltx-quality-20261031"
    unknown = repo / "artifacts" / "my-media"
    recent = repo / "artifacts" / "ltx-quality-20261101"
    acceptance = repo / "artifacts" / "acceptance" / "acceptance-20261031-abc"
    make_old(eligible)
    make_old(unknown)
    make_old(recent, days=1)
    make_old(acceptance)
    result = maintenance.artifact_candidates(repo, days=14, now=time.time())
    assert {p.path for p in result} == {eligible, acceptance}


def test_symlinks_and_keep_markers_block_cleanup(repo, tmp_path):
    directory = repo / "artifacts" / "ltx-quality-causes-20261031"
    make_old(directory)
    secret = tmp_path / "private-chat.db"
    secret.write_text("never touch")
    (directory / "linked").symlink_to(secret)
    assert maintenance.artifact_candidates(repo, days=14, now=time.time()) == []
    (directory / "linked").unlink()
    marker = directory / ".nobby-keep"
    marker.write_text("")
    old = time.time() - 20 * 86400
    os.utime(marker, (old, old))
    assert maintenance.artifact_candidates(repo, days=14, now=time.time()) == []
    assert secret.read_text() == "never touch"


def test_dry_run_and_explicit_apply(repo, capsys):
    target = repo / "artifacts" / "ltx-quality-20261031"
    make_old(target)
    assert maintenance.main(["scan", "--root", str(repo)]) == 0
    assert target.exists()
    assert "DRY-RUN" in capsys.readouterr().out
    assert maintenance.main(["clean", "--root", str(repo), "--apply"]) == 0
    assert target.exists()
    assert maintenance.main(["clean", "--root", str(repo), "--apply", "--yes"]) == 0
    assert not target.exists()


def test_active_directory_and_unknown_media_are_preserved(repo):
    old = repo / "artifacts" / "ltx-quality-20261031"
    make_old(old)
    changed = old / "active-progress.json"
    changed.write_text("working")
    protected = repo / "artifacts" / "media-library"
    make_old(protected)
    assert maintenance.artifact_candidates(repo, days=14, now=time.time()) == []
    assert changed.exists() and protected.exists()


def test_legacy_logs_are_opt_in_and_must_be_old(repo, monkeypatch):
    log = repo / "agent.log.legacy-1234567890123"
    log.write_text("private log")
    old = time.time() - 40 * 86400
    os.utime(log, (old, old))
    assert maintenance.artifact_candidates(repo, days=14, now=time.time()) == []
    assert maintenance.legacy_candidates(repo, days=14, now=time.time())[0].path == log
    assert maintenance.main(["clean", "--root", str(repo), "--apply", "--yes"]) == 0
    assert log.exists()
    monkeypatch.setattr(maintenance, "unused_log", lambda p: True)
    assert maintenance.main(["clean", "--root", str(repo), "--apply", "--yes",
                             "--include-legacy-logs"]) == 0
    assert not log.exists()


def test_preview_removal_requires_exact_name_and_confirmation(monkeypatch, tmp_path):
    project = "mlx-pr417-preview"
    working = tmp_path / "mlx-pr417-preview"
    working.mkdir()
    entry = {
        "Name": "/test-container", "Id": "abcdef",
        "Config": {"Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.project.working_dir": str(working)}},
        "Mounts": [{"Type": "bind", "Source": str(working / "edge.py")}],
    }
    monkeypatch.setattr(maintenance, "_docker_previews", lambda: {project: [entry]})
    calls = []
    monkeypatch.setattr(maintenance, "_run", lambda args:
                        (calls.append(args) or subprocess.CompletedProcess(args, 0, "", "")))
    assert maintenance.remove_preview("mlx-web", apply=True, yes=True) == 2
    assert maintenance.remove_preview(project, apply=False, yes=True) == 0
    assert calls == []
    assert maintenance.remove_preview(project, apply=True, yes=True) == 0
    assert calls == [["docker", "rm", "-f", "abcdef"]]


def test_external_mount_or_volume_blocks_preview_removal(monkeypatch, tmp_path):
    name = "mlx-pr415-preview"
    entry = {
        "Name": "/unsafe", "Id": "xyz",
        "Config": {"Labels": {
            "com.docker.compose.project": name,
            "com.docker.compose.project.working_dir": str(tmp_path / "preview")}},
        "Mounts": [{"Type": "volume", "Source": str(tmp_path / "sensitive")}],
    }
    monkeypatch.setattr(maintenance, "_docker_previews", lambda: {name: [entry]})
    assert maintenance.remove_preview(name, apply=True, yes=True) == 2
