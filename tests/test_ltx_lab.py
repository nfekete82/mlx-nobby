"""CPU-only lab tests: no MLX import, weights, services, or GPU workloads."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
from unittest import mock

import pytest

from ltx_lab import cli, config, compatibility, quality, runner, setup, telemetry
from ltx_lab.instrumentation import Instrumentation


class FakeArray:
    def __init__(self, work=0):
        self.work = work


class FakeMLX:
    array = FakeArray
    def __init__(self):
        self.now = 0.0
        self.syncs = 0
    def eval(self, *arrays):
        # Simulate deferred GPU work: dispatch is free, materialization consumes time.
        for array in arrays:
            self.now += array.work
            array.work = 0
    def synchronize(self):
        self.syncs += 1
    def get_active_memory(self):
        return 10
    def get_cache_memory(self):
        return 2
    def get_peak_memory(self):
        return 20


def test_recorder_counts_deferred_work_and_exclusive_children():
    mx = FakeMLX()
    rec = telemetry.Recorder(mx, clock=lambda: mx.now)
    with rec.span("parent"):
        mx.now += 1
        with rec.span("child"):
            rec.materialize((FakeArray(3), {"audio": FakeArray(2)}))
        mx.now += 2
    phases = rec.report()["phases"]
    assert phases["parent"]["inclusive_seconds"] == 8
    assert phases["parent"]["self_seconds"] == 3
    assert phases["child"]["inclusive_seconds"] == 5
    assert mx.syncs == 4


def test_recorder_records_failure_and_unwinds():
    rec = telemetry.Recorder(FakeMLX())
    with pytest.raises(ValueError):
        with rec.span("failed"):
            raise ValueError("test")
    assert not rec.stack
    assert rec.events[0]["status"] == "failed"


def test_patch_restores_inherited_methods_even_after_error():
    class Base:
        def method(self):
            return 1
    obj = Base()
    with pytest.raises(RuntimeError):
        with Instrumentation(telemetry.Recorder(FakeMLX())) as hooks:
            hooks.patch(obj, "method", lambda: 2)
            assert obj.method() == 2
            raise RuntimeError("test")
    assert obj.method() == 1
    assert "method" not in vars(obj)


def fake_upstream(monkeypatch):
    names = ("ltx_core_mlx", "ltx_core_mlx.model", "ltx_core_mlx.model.video_vae",
             "ltx_core_mlx.model.video_vae.video_vae", "ltx_pipelines_mlx", "ltx_pipelines_mlx.utils",
             "ltx_pipelines_mlx.utils.blocks", "ltx_pipelines_mlx.utils.samplers",
             "ltx_pipelines_mlx.utils._orchestration", "ltx_pipelines_mlx.a2vid_two_stage")
    modules = {name: types.ModuleType(name) for name in names}
    for name, module in modules.items():
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(modules[parent], child, module)
    blocks = modules["ltx_pipelines_mlx.utils.blocks"]
    samplers = modules["ltx_pipelines_mlx.utils.samplers"]
    vae = modules["ltx_core_mlx.model.video_vae.video_vae"]
    a2v = modules["ltx_pipelines_mlx.a2vid_two_stage"]
    orchestration = modules["ltx_pipelines_mlx.utils._orchestration"]
    class Component:
        def load(self):
            return None
        def encode(self, *args):
            self.load()
            return (FakeArray(2), FakeArray(1))
        def __call__(self, *args):
            return FakeArray(1)
        def decode_and_stream(self, *args):
            with vae._ffmpeg_sink([]) as proc:
                vae.stream_chunks_to_ffmpeg(vae.VideoDecoder().tiled_decode(), proc)
    for name in ("PromptEncoder", "AudioDecoder", "AudioConditioner", "VideoDecoder"):
        # Distinct classes, as upstream, so class patches don't stack accidentally.
        setattr(blocks, name, type(name, (Component,), {}))
    class VAE:
        def tiled_decode(self):
            yield FakeArray(5)
            yield FakeArray(7)
    class Writer:
        def submit(self, value):
            pass
        def finish(self):
            pass
        def shutdown(self):
            pass
    vae.VideoDecoder = VAE
    vae.VideoEncoder = type("VideoEncoder", (Component,), {})
    vae._OrderedFrameWriter = Writer
    @contextlib.contextmanager
    def sink(cmd):
        yield object()
    vae._ffmpeg_sink = sink
    def stream(chunks, proc):
        writer = Writer()
        for chunk in chunks:
            writer.submit(chunk)
        writer.finish()
        writer.shutdown()
    vae.stream_chunks_to_ffmpeg = stream
    samplers._step_timed = lambda *args: None
    def loop(*args, **kwargs):
        for index in range(kwargs.get("steps", 3)):
            samplers._step_timed(None, index, FakeArray(2), FakeArray(1))
        return (FakeArray(), FakeArray())
    for name in ("denoise_loop", "euler_ancestral_denoising_loop", "guided_denoise_loop"):
        setattr(samplers, name, loop)
    a2v.encode_source_audio = lambda *args, **kwargs: FakeArray(1)
    a2v.load_audio = lambda *args, **kwargs: FakeArray(1)
    orchestration.save_waveform = lambda *args, **kwargs: None
    pipe = Component()
    pipe.image_conditioner = Component()
    pipe.dit = types.SimpleNamespace(inner=types.SimpleNamespace(compute_dtype="bfloat16"))
    return pipe, blocks, samplers, vae


def test_instrumentation_mock_integration_syncs_terminal_step_and_lazy_vae(monkeypatch):
    pipe, blocks, samplers, vae = fake_upstream(monkeypatch)
    original_loop, original_tiles = samplers.denoise_loop, vae.VideoDecoder.tiled_decode
    mx = FakeMLX()
    rec = telemetry.Recorder(mx, clock=lambda: mx.now)
    with Instrumentation(rec) as hooks:
        hooks.install(pipe)
        pipe.load()
        blocks.PromptEncoder().encode("prompt")
        samplers.denoise_loop(steps=8)
        samplers.denoise_loop(steps=3)
        blocks.AudioDecoder()(FakeArray())
        blocks.VideoDecoder().decode_and_stream()
    phases = rec.report()["phases"]
    assert phases["text_encoding"]["inclusive_seconds"] == 3
    assert phases["denoising_stage_1"]["inclusive_seconds"] == 24
    assert phases["denoising_stage_2"]["inclusive_seconds"] == 9
    assert len(rec.steps) == 11
    assert rec.steps[-1]["step"] == 3
    assert rec.steps[-1]["seconds"] == 3
    assert phases["vae_decoding"]["inclusive_seconds"] == 12
    assert phases["mux_session"]["self_seconds"] == 0
    assert phases["mux_session"]["inclusive_seconds"] == 12
    assert samplers.denoise_loop is original_loop
    assert vae.VideoDecoder.tiled_decode is original_tiles
    assert rec.effective["dit_compute"][0]["dtype"] == "bfloat16"


def test_profile_environment_clears_inherited_overrides(monkeypatch):
    monkeypatch.setenv("LTX2_VAE_DECODE_KEEP_CACHE", "1")
    monkeypatch.setenv("LTX2_GEMMA_MAX_LENGTH", "12")
    monkeypatch.setenv("PYTHONPATH", "/production")
    for name, profile in config.PROFILES.items():
        env = config.experiment_environment(name, config.LAB / "cache")
        assert env["HF_HUB_OFFLINE"] == "1"
        assert env["LTX2_COMPUTE_DTYPE"] == profile["dtype"]
        assert (env["LTX2_SOL_TAU"] != "off") == profile["sparse"]
        assert "LTX2_VAE_DECODE_KEEP_CACHE" not in env
        assert "LTX2_GEMMA_MAX_LENGTH" not in env
        assert "PYTHONPATH" not in env


@pytest.mark.parametrize("path", ["/tmp/results", config.PRODUCTION, config.LAB, config.LAB / "../bad"])
def test_outputs_cannot_escape_lab(path):
    with pytest.raises(ValueError):
        config.inside_lab(path)


def test_lab_symlink_escape_is_rejected(tmp_path):
    link = config.LAB / "test-output-symlink"
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(tmp_path, target_is_directory=True)
    try:
        with pytest.raises(ValueError):
            config.inside_lab(link / "outside")
    finally:
        link.unlink()


def test_vm_accounting_and_existing_swap_growth_are_separate():
    vm = telemetry.parse_vm_stat("""Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free: 10.
Pages active: 20.
Pages inactive: 30.
Pages wired down: 40.
Pages occupied by compressor: 50.
Pages speculative: 60.
Pageins: 5.
Pageouts: 2.
""")
    assert vm["ram_used_bytes"] == 200 * 16384
    assert vm["available_estimate_bytes"] == 100 * 16384
    assert vm["pageins"] == 5
    memory = telemetry.MemorySampler()
    memory.samples = [{"ram_used_bytes": 100, "swap_used_bytes": 10},
                      {"ram_used_bytes": 150, "swap_used_bytes": 10}]
    result = memory.summary()
    assert result["peak_system_ram_bytes"] == 150
    assert result["peak_swap_bytes"] == 10
    assert result["swap_growth_bytes"] == 0


def test_runtime_memory_guard_only_aborts_test_work():
    memory = telemetry.MemorySampler()
    memory.samples = [{"swap_used_bytes": 10, "memory_pressure_level": 1}]
    memory.check()
    memory.samples.append({"swap_used_bytes": 10 + 257 * 1024**2, "memory_pressure_level": 1})
    with pytest.raises(RuntimeError, match="swap growth"):
        memory.check()
    memory.samples[-1] = {"swap_used_bytes": 10, "memory_pressure_level": 4}
    with pytest.raises(RuntimeError, match="critical"):
        memory.check()


def test_recorder_correlates_sampled_memory_with_phase_clock():
    mx = FakeMLX()
    rec = telemetry.Recorder(mx, clock=lambda: mx.now)
    with rec.span("phase"):
        mx.now += 2
    samples = [{"timestamp": rec.unix_origin + 1, "ram_used_bytes": 100, "rss_bytes": 10},
               {"timestamp": rec.unix_origin + 3, "ram_used_bytes": 900, "rss_bytes": 90}]
    phase = rec.report(samples)["phases"]["phase"]
    assert phase["sampled_peak_ram_used_bytes"] == 100
    assert phase["sampled_peak_rss_bytes"] == 10
    assert phase["memory_sample_count"] == 1


@pytest.mark.parametrize("pressure,available,processes,allowed", [
    (1, 30, "123 /usr/bin/idle", True), (2, 30, "123 /usr/bin/idle", False),
    (1, 12, "123 /usr/bin/idle", False), (1, 30, "123 python -m mlx_vlm server", False),
    (1, 30, "", False), (None, 30, "123 /usr/bin/idle", False)])
def test_resource_admission_fails_closed(pressure, available, processes, allowed):
    with mock.patch.object(telemetry, "system_snapshot", return_value={
        "memory_pressure_level": pressure, "available_estimate_bytes": available * 1024**3,
        "swap_used_bytes": 10}), mock.patch.object(telemetry, "command", return_value=processes):
        assert telemetry.preflight()["allowed"] is allowed


def test_execute_requires_explicit_approval_before_resource_check():
    args = cli.parser().parse_args(["--execute"])
    with mock.patch.object(cli, "preflight") as preflight:
        with pytest.raises(ValueError, match="approve-gpu"):
            cli.execute(args, {}, {})
        preflight.assert_not_called()


def test_denied_admission_never_spawns_child():
    args = cli.parser().parse_args(["--execute", "--approve-gpu"])
    with mock.patch.object(cli, "preflight", return_value={"allowed": False, "reasons": ["memory"]}), \
            mock.patch.object(cli, "launch_child") as child:
        with pytest.raises(RuntimeError, match="admission"):
            cli.execute(args, {}, {})
        child.assert_not_called()


@pytest.mark.parametrize("start_mode,expected_counts", [("both", [3]), ("cold", [1, 1, 1]), ("warm", [3])])
def test_controller_cold_warm_plan_preserves_inputs_and_isolated_environment(tmp_path, monkeypatch,
                                                                           start_mode, expected_counts):
    monkeypatch.setattr(config, "LAB", tmp_path)
    monkeypatch.setattr(cli, "LAB", tmp_path)
    monkeypatch.setattr(cli, "preflight", lambda *a: {"allowed": True})
    monkeypatch.setattr(cli, "production_fingerprint", lambda: {"head": "same"})
    monkeypatch.setattr(cli, "input_fingerprint", lambda request: {"seed": request["seed"]})
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *a, **kw: "sha")
    planned = []
    def launch(command, environment, log, timeout):
        request = json.loads(Path(command[command.index("--request-file") + 1]).read_text())
        assert "--approve-gpu" in command
        assert environment["HF_HUB_OFFLINE"] == "1"
        assert environment["LTX2_COMPUTE_DTYPE"] == "bfloat16"
        assert request["prompt"] == "same prompt" and request["seed"] == 42
        assert request["runtime"].startswith(str(tmp_path))
        planned.append(request)
        return 0
    monkeypatch.setattr(cli, "launch_child", launch)
    args = cli.parser().parse_args(["--execute", "--approve-gpu", "--versions", "0.17.0",
                                    "--profiles", "bf16-baseline", "--start-mode", start_mode,
                                    "--warm-runs", "2"])
    result = cli.execute(args, {"pipeline": "t2v", "prompt": "same prompt", "seed": 42}, {})
    assert [r["runs"] for r in planned] == expected_counts
    assert planned[0]["first_run_role"] == ("warmup" if start_mode == "warm" else "measurement")
    assert json.loads(Path(result["suite"]).read_text())["production_unchanged"] is True


def test_runner_mock_integration_saves_two_runs_and_all_phase_results(tmp_path, monkeypatch):
    pipe, blocks, samplers, vae = fake_upstream(monkeypatch)
    mx = FakeMLX()
    mx.reset_peak_memory = lambda: None
    mx_package = types.ModuleType("mlx")
    mx_package.__path__ = []
    mx_package.core = mx
    monkeypatch.setitem(sys.modules, "mlx", mx_package)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    class Pipeline(type(pipe)):
        def __init__(self, **kwargs):
            self.image_conditioner = type(pipe)()
            self.video_decoder_block = blocks.VideoDecoder()
            self.dit = pipe.dit
        def generate_and_save(self, **kwargs):
            self.load()
            blocks.PromptEncoder().encode(kwargs["prompt"])
            samplers.denoise_loop(steps=8)
            samplers.denoise_loop(steps=3)
            blocks.AudioDecoder()(FakeArray())
            self.video_decoder_block.decode_and_stream()
            Path(kwargs["output_path"]).write_bytes(b"mock video")
    for name, cls in (("distilled", "DistilledPipeline"), ("a2vid_distilled", "A2VidDistilledPipeline")):
        module = types.ModuleType(f"ltx_pipelines_mlx.{name}")
        setattr(module, cls, Pipeline)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        setattr(sys.modules["ltx_pipelines_mlx"], name, module)
    sys.modules["ltx_pipelines_mlx.a2vid_two_stage"].A2VidPipelineTwoStage = Pipeline
    monkeypatch.setattr(config, "LAB", tmp_path)
    runtime = tmp_path / "runtime"
    for module_name in ("ltx_pipelines_mlx.distilled", "ltx_pipelines_mlx.a2vid_distilled",
                        "ltx_pipelines_mlx.a2vid_two_stage"):
        sys.modules[module_name].__file__ = str(runtime / "packages" / (module_name + ".py"))
    monkeypatch.setattr(sys, "prefix", str(runtime / ".venv"))
    monkeypatch.setenv("LTX2_COMPUTE_DTYPE", "bfloat16")
    monkeypatch.setenv("LTX2_SOL_TAU", "off")
    monkeypatch.setattr(runner, "inspect_runtime", lambda *a: {
        "compatible": True, "profiles": {"bf16-baseline": True}})
    monkeypatch.setattr(runner, "validate_environment", lambda *a: {})
    monkeypatch.setattr(runner, "validate_model", lambda *a: tmp_path)
    monkeypatch.setattr(runner, "input_fingerprint", lambda *a: {"sha256": "same"})
    monkeypatch.setattr(runner, "preflight", lambda *a: {"allowed": True})
    monkeypatch.setattr(runner, "MemorySampler", lambda: telemetry.MemorySampler(snapshot=lambda: {
        "timestamp": __import__("time").time(), "ram_used_bytes": 100, "swap_used_bytes": 10,
        "memory_pressure_level": 1}))
    monkeypatch.setattr(runner, "media_evidence", lambda video, directory: {
        "video": str(video), "probe": {"streams": [{"codec_type": "video", "width": 1280,
        "height": 704, "nb_read_frames": "121", "avg_frame_rate": "24/1"}]}})
    request = {"runtime": str(runtime), "output": str(tmp_path / "runs"), "version": "0.17.0",
               "profile": "bf16-baseline", "model": str(tmp_path), "pipeline": "t2v", "runs": 2,
               "min_available_gib": 20, "prompt": "same", "seed": 42, "width": 1280, "height": 704,
               "frames": 121, "fps": 24, "stage1_steps": 8, "stage2_steps": 3}
    paths = runner.run(request)
    cold, warm = (json.loads(Path(path).read_text()) for path in paths)
    assert cold["status"] == warm["status"] == "completed"
    assert cold["start"] == "cold_process" and warm["start"] == "warm_process"
    for result in (cold, warm):
        assert len(result["telemetry"]["steps"]) == 11
        assert result["memory"]["swap_growth_bytes"] == 0
        assert result["telemetry"]["phases"]["vae_decoding"]["calls"] == 3
        assert result["input_fingerprint"] == {"sha256": "same"}


def test_unsupported_profile_is_rejected_before_any_child_launch(monkeypatch):
    monkeypatch.setattr(cli, "inspect_runtime", lambda *a: {
        "compatible": True, "profiles": {"fp16": False}})
    monkeypatch.setattr(cli, "validate_environment", lambda *a: {})
    with mock.patch.object(cli, "launch_child") as launch:
        with pytest.raises(ValueError, match="Unsupported profile"):
            cli.main(["--profiles", "fp16", "--execute", "--approve-gpu"])
        launch.assert_not_called()


def test_child_gate_does_not_import_mlx():
    p = subprocess.run([sys.executable, "-B", "-m", "ltx_lab.runner", "--request-file", "/nonexistent"],
                       text=True, capture_output=True)
    assert p.returncode != 0
    assert "approve-gpu" in p.stderr
    # A fresh CPU-only import of all controller modules must not import MLX.
    code = "import ltx_lab.cli,sys; assert not any(x=='mlx' or x.startswith('mlx.') for x in sys.modules)"
    subprocess.run([sys.executable, "-B", "-c", code], check=True)


@pytest.mark.parametrize("version", list(config.COMMITS))
def test_installed_isolated_runtime_contract_and_venv(version):
    runtime = config.runtime_path(version)
    if not (runtime / ".venv/bin/python").exists():
        pytest.skip("optional local isolated runtime not installed")
    report = compatibility.inspect_runtime(runtime, version)
    assert report["compatible"], report["checks"]
    assert all(report["profiles"].values())
    assert report["features"]["stage1_resume"] is (version == "0.17.0")
    env = compatibility.validate_environment(runtime, version)
    assert env["packages"]["mlx"] == "0.32.2"
    assert env["packages"]["ltx-core-mlx"] == version


def test_production_fingerprint_detects_lock_changes_without_writing(tmp_path, monkeypatch):
    (tmp_path / ".venv").mkdir()
    for name in ("uv.lock", "pyproject.toml", ".venv/pyvenv.cfg"):
        (tmp_path / name).write_text("original")
    monkeypatch.setattr(setup, "PRODUCTION", tmp_path)
    monkeypatch.setattr(setup, "git", lambda root, *args: "sha" if args[0] == "rev-parse" else "")
    before = setup.production_fingerprint()
    assert setup.production_fingerprint() == before
    assert all((tmp_path / name).read_text() == "original" for name in before["files"])
    (tmp_path / "uv.lock").write_text("changed")
    assert setup.production_fingerprint() != before


def test_input_fingerprint_changes_for_content_seed_prompt_and_model(tmp_path):
    (tmp_path / "embedded_config.json").write_text("{}")
    (tmp_path / "quantize_config.json").write_text("{}")
    image = tmp_path / "image.png"
    image.write_bytes(b"first")
    request = dict(model=str(tmp_path), prompt="one", seed=42, width=1280, height=704,
                   frames=121, fps=24, stage1_steps=8, stage2_steps=3, pipeline="i2v", image=str(image))
    a = runner.input_fingerprint(request)
    for key, value in (("seed", 43), ("prompt", "two"), ("frames", 129)):
        assert runner.input_fingerprint(dict(request, **{key: value})) != a
    image.write_bytes(b"second")
    assert runner.input_fingerprint(request) != a


@pytest.mark.parametrize("args", [["--width", "1281"], ["--frames", "120"], ["--pipeline", "i2v"],
                                  ["--pipeline", "a2v-classic"], ["--seed", "-1"], ["--warm-runs", "-1"]])
def test_invalid_generation_inputs_fail_without_inference(args):
    with pytest.raises(ValueError):
        cli.request_from_args(cli.parser().parse_args(args))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_cpu_media_integration_produces_video_audio_frames_and_comparison(tmp_path):
    # Tiny synthetic CPU codec fixture, not an LTX generation or GPU benchmark.
    paths = []
    for label in ("reference", "candidate"):
        directory = tmp_path / label
        directory.mkdir()
        video = directory / "video.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=red:s=64x64:r=24", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=48000", "-t", "0.375", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True, timeout=30)
        artifacts = quality.media_evidence(video, directory)
        assert Path(artifacts["audio"]).is_file()
        assert artifacts["audio_metrics"]["sample_rate"] == 48000
        assert artifacts["audio_metrics"]["rms_amplitude"] > 0
        assert artifacts["audio_metrics"]["clipped_sample_fraction"] == 0
        assert (directory / "frame-0008.png").is_file()
        review = json.loads((directory / "quality-review.json").read_text())
        assert set(review["scores"]) == set(quality.CATEGORIES)
        result = directory / "result.json"
        telemetry.write_json(result, {"status": "completed", "input_fingerprint": {"sha256": "same"},
                                      "artifacts": artifacts})
        paths.append(result)
    comparison = quality.compare(*paths, tmp_path / "comparison")
    assert comparison["decoded_frame_hashes_equal"]
    assert comparison["quality_accepted"] is None
    assert comparison["metrics"]["ssim"]
    changed = json.loads(paths[1].read_text())
    changed["input_fingerprint"] = {"sha256": "different"}
    telemetry.write_json(paths[1], changed)
    with pytest.raises(ValueError, match="do not match"):
        quality.compare(*paths, tmp_path / "bad")
