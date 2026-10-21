"""Release diagnostic is read-only and deliberately cannot approve deployment."""
import importlib.util
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ltx-release-readiness.py"
spec = importlib.util.spec_from_file_location("ltx_release_readiness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_missing_admission_proof_remains_no_go(tmp_path):
    def unavailable():
        raise RuntimeError("HTTP Error 404")
    with mock.patch.object(mod.subprocess, "check_output",
                           side_effect=OSError("runtime missing")):
        report = mod.assess(
            lab_root=tmp_path, admission_check=unavailable,
            memory_check=lambda: {"allowed": True, "reasons": []})
    assert report["status"] == "NO-GO"
    assert report["checks"]["all_listener_admission"]["ok"] is False
    assert report["checks"]["memory_admission"]["ok"] is True


def test_even_all_static_checks_cannot_replace_gpu_and_restore(tmp_path):
    def fake_check(args, **_kwargs):
        if args[-1] == "HEAD":
            from ltx_lab.config import COMMITS
            version = args[2].rsplit("runtime-v", 1)[1]
            return COMMITS[version] + "\n"
        return ""
    with mock.patch.object(mod.subprocess, "check_output", side_effect=fake_check), \
         mock.patch.object(Path, "is_file", return_value=True):
        report = mod.assess(
            lab_root=tmp_path, admission_check=lambda: {"chat": {}, "router": {}},
            memory_check=lambda: {"allowed": True, "reasons": []})
    assert report["all_readonly_checks_passed"] is True
    assert report["status"] == "NO-GO"
    assert "GPU A/B" in report["remaining_requirements"][1]
