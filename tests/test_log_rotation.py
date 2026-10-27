"""Rotation, retention and real inherited file-descriptor output."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.log_rotation import RotatingLog


def test_rotation_enforces_exact_byte_cap_and_retention(tmp_path):
    path = tmp_path / "agent.log"
    log = RotatingLog(path, max_bytes=10, backups=2)
    try:
        log.write(b"a" * 10 + b"b" * 10 + b"c" * 10 + b"d" * 7)
    finally:
        log.close()
    assert path.read_bytes() == b"d" * 7
    assert path.with_suffix(".log.1").read_bytes() == b"c" * 10
    assert path.with_suffix(".log.2").read_bytes() == b"b" * 10
    assert not path.with_suffix(".log.3").exists()


def test_oversized_legacy_log_is_renamed_without_copy_or_deletion(tmp_path):
    path = tmp_path / "agent.log"
    with path.open("wb") as handle:
        handle.seek(10 * 1024**3)
        handle.write(b"end")
    old = path.stat()
    log = RotatingLog(path, max_bytes=100, backups=1)
    try:
        log.write(b"new" * 100)
    finally:
        log.close()
    legacy, = tmp_path.glob("agent.log.legacy-*")
    assert legacy.stat().st_ino == old.st_ino
    assert legacy.stat().st_size == old.st_size
    assert path.stat().st_size <= 100


def test_only_one_writer_can_rotate_and_reopen_after_close(tmp_path):
    path = tmp_path / "agent.log"
    first = RotatingLog(path, max_bytes=10)
    try:
        with pytest.raises(BlockingIOError):
            RotatingLog(path, max_bytes=10)
    finally:
        first.close()
    second = RotatingLog(path, max_bytes=10)
    second.write(b"reopened")
    second.close()
    assert path.read_bytes() == b"reopened"


def test_capture_includes_python_native_and_child_output_and_restores_fd(tmp_path):
    code = '''
import os, subprocess, sys
from pathlib import Path
from agent.log_rotation import capture_output
with capture_output(1, Path(sys.argv[1]), max_bytes=4096):
    print("python", flush=True)
    os.write(1, b"native\\n")
    subprocess.run([sys.executable, "-c", "print('child')"], check=True)
print("restored", flush=True)
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "agent.log")],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=True,
    )
    assert result.stdout == b"restored\n"
    assert (tmp_path / "agent.log").read_bytes() == b"python\nnative\nchild\n"


def test_capture_drains_after_disk_failure_instead_of_blocking_jobs(tmp_path):
    code = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
from agent.log_rotation import capture_output, RotatingLog
with patch.object(RotatingLog, 'write', side_effect=OSError('test disk failure')):
    with capture_output(1, Path(sys.argv[1])):
        for _ in range(100):
            os.write(1, b'x' * 65536)
print('still responsive')
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "agent.log")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=True,
    )
    assert b"still responsive" in result.stdout
    assert result.stdout.count(b"log write failed") == 1
