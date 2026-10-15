"""CPU-only guards for the optional 0.16.3 distilled A2V rollout."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/ltx-talking-photo-a2v.py"


def test_runner_preserves_classic_default_and_accepts_distilled():
    spec = importlib.util.spec_from_file_location("ltx_talking_photo_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    common = ["--model", "/tmp/model", "--image", "/tmp/image.png",
              "--audio", "/tmp/audio.wav", "--output", "/tmp/out.mp4",
              "--prompt", "hello", "--width", "512", "--height", "704",
              "--frames", "73"]
    classic = module.parser().parse_args(common)
    distilled = module.parser().parse_args(common + ["--mode", "distilled",
                                                      "--stage1-steps", "8"])
    assert classic.mode == "classic"
    assert classic.stage1_steps == 15
    assert distilled.mode == "distilled"
    assert distilled.stage1_steps == 8


def test_distilled_is_explicit_and_does_not_change_classic_defaults():
    source = (ROOT / "agent/talking_photo_ltx.py").read_text(encoding="utf-8")
    assert '"distilled" if distilled else "classic"' in source
    assert '"8" if distilled else "15"' in source
    assert 'if not distilled:' in source
    assert 'command.extend(["--cfg-scale", "3.0", "--stg-scale", "1.0"])' in source
    assert 'runtime_coordinator.video_runtime(' in source


def test_runner_does_not_pass_dev_cfg_to_distilled():
    source = RUNNER.read_text(encoding="utf-8")
    assert 'if args.mode == "classic":' in source
    assert 'from ltx_pipelines_mlx.a2vid_distilled import A2VidDistilledPipeline' in source
    assert 'pipeline_type = A2VidDistilledPipeline' in source
    assert 'pipeline_module.load_audio = audited_load_audio' in source
