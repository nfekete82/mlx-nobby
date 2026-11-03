"""Regression: local ignored experiments must not contaminate release tests."""
from pathlib import Path
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[1]
tracked_python_tests = runpy.run_path(
    str(ROOT / "tests" / "acceptance" / "official_pytest.py")
)["tracked_python_tests"]


def test_only_tracked_official_python_tests(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name in (
        "tests/test_regular.py",
        "tests/nested/test_subsuite.py",
        "tests/e2e/test_browser.py",
        "tests/test_helper.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok(): assert True\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "tests/test_regular.py", "tests/nested/test_subsuite.py",
         "tests/e2e/test_browser.py"],
        cwd=tmp_path,
        check=True,
    )
    # Ignored/untracked snapshots and local-only test files are never collected.
    local = tmp_path / "tests" / "test_local_experiment.py"
    local.write_text("raise RuntimeError('must not be collected')\n", encoding="utf-8")
    artifact = tmp_path / "artifacts" / "engineering" / "tests" / "test_copy.py"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("raise RuntimeError('must not be collected')\n", encoding="utf-8")

    assert tracked_python_tests(tmp_path) == [
        "tests/nested/test_subsuite.py",
        "tests/test_regular.py",
    ]
