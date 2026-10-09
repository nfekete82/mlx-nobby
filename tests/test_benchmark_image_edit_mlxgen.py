"""Offline benchmark contracts. No real MLX model is required."""
import argparse
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark-image-edit-mlxgen.py"
spec = importlib.util.spec_from_file_location("image_edit_benchmark", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_bounds_and_progress():
    assert mod.positive_samples("5") == 5
    with pytest.raises(argparse.ArgumentTypeError):
        mod.positive_samples("6")
    assert mod.parse_progress("100%| 4/4 [00:18<00:00]") == {"last_step": 4, "steps": 4}
    assert mod.parse_progress("nothing") is None


def test_cli_rejects_invalid_dimensions_before_start(tmp_path):
    runner = tmp_path / "mlxgen"
    runner.write_text("#!/bin/sh\nexit 0\n")
    runner.chmod(0o755)
    source = tmp_path / "source.png"
    source.write_bytes(b"fake")
    with pytest.raises(SystemExit):
        mod.main(["--runner", str(runner), "--image", str(source),
                  "--width", "513", "--output-dir", str(tmp_path / "out")])


def test_benchmark_mock_cli_does_not_emit_prompt_or_source_to_json(tmp_path):
    runner = tmp_path / "mlxgen"
    runner.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib,sys\n"
        "args=sys.argv\n"
        "pathlib.Path(args[args.index('--output')+1]).write_bytes(b'fake-image')\n"
        "print('100%| 4/4 [00:01<00:00]')\n"
    )
    runner.chmod(0o755)
    source = tmp_path / "source.png"
    source.write_bytes(b"fake")
    target = tmp_path / "report"
    assert mod.main(["--runner", str(runner), "--image", str(source),
                     "--samples", "1", "--output-dir", str(target)]) == 0
    report = (target / "summary.json").read_text()
    assert "source.png" not in report
    assert mod.PROMPT not in report
    assert "output_created" in report
