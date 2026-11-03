"""Regression tests for resolving an installed MLX manager CLI to its checkout."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "mlx"


def _resolver_source():
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("mlx_repository_root() {")
    end = text.index("\n}\n", start) + 2
    return text[start:end]


def _fixture(tmp_path: Path):
    project = tmp_path / "project"
    script = project / "scripts" / "mlx"
    runner = project / "tests" / "acceptance" / "runner.py"
    runner.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n" + _resolver_source() + "\nmlx_repository_root\n")
    script.chmod(0o755)
    runner.write_text("# test harness\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return project, script, bindir, elsewhere


def test_installed_absolute_symlink_resolves_real_checkout(tmp_path):
    project, script, bindir, elsewhere = _fixture(tmp_path)
    command = bindir / "mlx"
    command.symlink_to(script)
    result = subprocess.run(["bash", str(command)], cwd=elsewhere, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(project)


def test_installed_relative_symlink_resolves_real_checkout(tmp_path):
    project, script, bindir, elsewhere = _fixture(tmp_path)
    command = bindir / "mlx"
    command.symlink_to(os.path.relpath(script, bindir))
    result = subprocess.run(["bash", str(command)], cwd=elsewhere, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(project)


def test_direct_source_cli_works_from_any_directory(tmp_path):
    project, script, _, elsewhere = _fixture(tmp_path)
    result = subprocess.run(["bash", str(script)], cwd=elsewhere, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(project)


def test_legacy_copied_cli_from_checkout(tmp_path):
    project, script, bindir, _ = _fixture(tmp_path)
    copied = bindir / "mlx"
    shutil.copyfile(script, copied)
    result = subprocess.run(["bash", str(copied)], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(project)


def test_legacy_copied_cli_fails_closed_elsewhere(tmp_path):
    project, script, bindir, elsewhere = _fixture(tmp_path)
    copied = bindir / "mlx"
    shutil.copyfile(script, copied)
    result = subprocess.run(["bash", str(copied)], cwd=elsewhere, capture_output=True, text=True)
    assert result.returncode != 0
    assert not result.stdout.strip()
    assert "checkout not found" in result.stderr


def test_legacy_copied_cli_explicit_checkout(tmp_path):
    project, script, bindir, elsewhere = _fixture(tmp_path)
    copied = bindir / "mlx"
    shutil.copyfile(script, copied)
    result = subprocess.run(
        ["bash", str(copied)],
        cwd=elsewhere,
        env={**os.environ, "MLX_NOBBY_PROJECT_DIR": str(project)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(project)
