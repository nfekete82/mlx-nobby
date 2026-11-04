"""Ensure the scheduled job cannot touch protected categories."""
import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "maintenance-launchagent.py"
spec = importlib.util.spec_from_file_location("mlx_maintenance_launchagent", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_daily_job_is_opt_in_and_artifact_only(tmp_path):
    plist = module.make_plist(tmp_path / "mlx-web", tmp_path / "bin" / "python")
    assert plist["RunAtLoad"] is False
    assert plist["KeepAlive"] is False
    assert plist["StartCalendarInterval"] == {"Hour": 4, "Minute": 30}
    argv = plist["ProgramArguments"]
    assert argv[-1] == "--yes"
    assert argv[-3:] == ["14", "--apply", "--yes"]
    assert "clean" in argv
    assert "--include-legacy-logs" not in argv
    assert "remove-preview" not in argv
    assert "docker" not in argv
