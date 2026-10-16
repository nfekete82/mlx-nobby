"""Dry-run contracts for the guarded SDXL terminal blind comparison."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compare-sdxl-safe.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("compare_sdxl_safe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_blind_plan_pairs_prompts_seeds_and_settings():
    tool = load_tool()
    args = tool.parse_args(["--size", "512", "--steps", "20", "--cfg", "3.5"])
    jobs = tool.build_plan(args)
    assert len(jobs) == 8
    assert len({x["scene"] for x in jobs}) == 4
    for scene in dict.fromkeys(job["scene"] for job in jobs):
        pair = [job for job in jobs if job["scene"] == scene]
        assert {job["label"] for job in pair} == {"A", "B"}
        assert {job["model"] for job in pair} == set(tool.MODELS)
        for field in ("prompt", "seed", "width", "height", "steps", "guidance"):
            assert pair[0][field] == pair[1][field]


def test_custom_prompt_via_terminal_dry_run_does_not_connect_to_service():
    command = [
        sys.executable, str(SCRIPT), "--dry-run", "--size", "512",
        "--prompt", "A photorealistic adult portrait",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    jobs = json.loads(completed.stdout)
    assert len(jobs) == 2
    assert {job["model"] for job in jobs} == {
        "juggernaut-xl", "lustify-endgame-sdxl",
    }
    assert all(job["prompt"] == "A photorealistic adult portrait" for job in jobs)


def test_only_local_loopback_service_is_permitted():
    tool = load_tool()
    import pytest
    with pytest.raises(SystemExit):
        tool.parse_args(["--image-url", "https://external.example.com:8030"])


def test_uses_guarded_http_image_service_not_raw_sdxl_worker():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"/generate"' in source
    assert "subprocess.Popen(" not in source
    assert "benchmark-juggernaut" not in source
    assert "PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0" not in source


def test_waits_for_async_launchd_start_without_spawning_worker(monkeypatch):
    import io
    import urllib.error
    tool = load_tool()
    requests = []

    def urlopen(request, timeout):
        requests.append(request.full_url)
        if len(requests) == 1:
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        return io.BytesIO(b'{"status":"ready"}')

    monkeypatch.setattr(tool, "urlopen", urlopen)
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    tool.wait_for_service("http://127.0.0.1:8030", timeout=1)
    assert requests == [
        "http://127.0.0.1:8030/health",
        "http://127.0.0.1:8030/health",
    ]


def test_unreachable_service_does_not_create_benchmark_outputs(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    monkeypatch.setattr(tool, "wait_for_service",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("not running")))
    target = tmp_path / "benchmarks"
    assert tool.main(["--output-dir", str(target)]) == 1
    assert not target.exists()
    assert "Benchmark nicht gestartet" in capsys.readouterr().err
