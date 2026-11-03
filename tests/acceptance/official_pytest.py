"""Discover only version-controlled Python unit tests for release acceptance.

Ignored local benchmark snapshots, private experiments and generated artifacts
must never become an implicit part of the official release test suite.
Explicit targeted pytest runs can still execute those experiments separately.
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys


def tracked_python_tests(root: Path) -> list[str]:
    root = root.resolve()
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        candidate = Path(name)
        parts = candidate.parts
        if (
            len(parts) < 2
            or parts[0] != "tests"
            or (len(parts) >= 3 and parts[1] == "e2e")
            or candidate.suffix != ".py"
            or not candidate.name.startswith("test_")
            or not (root / candidate).is_file()
        ):
            continue
        paths.append(name)
    tests = sorted(set(paths))
    if not tests:
        raise RuntimeError("No tracked Python test files were found; release gate cannot pass.")
    return tests


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[2]
    try:
        paths = tracked_python_tests(project)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Official test discovery failed: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.stdout.buffer.write(b"".join(os.fsencode(path) + b"\0" for path in paths))
