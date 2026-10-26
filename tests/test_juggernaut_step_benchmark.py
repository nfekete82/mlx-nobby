"""CPU-only tests for the explicit Juggernaut same-seed A/B workflow."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "juggernaut_step_benchmark",
    ROOT / "scripts" / "benchmark-juggernaut-steps.py",
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_high_resolution_step_comparison_requests_are_identical_except_steps():
    items = [benchmark.image_request("A crisp realistic red fox", 17, steps)
             for steps in benchmark.STEPS]
    assert [item["payload"]["steps"] for item in items] == [30, 35, 40]
    for item in items:
        assert item["operation"] == "generate"
        assert item["payload"]["model"] == "juggernaut-xl"
        assert item["payload"]["quality"] == "quality"
        assert item["payload"]["auto_size"] is True
        assert item["payload"]["seed"] == 17
        assert item["payload"]["guidance"] == 4.0
    assert len({
        json.dumps({k: v for k, v in item["payload"].items() if k != "steps"}, sort_keys=True)
        for item in items
    }) == 1


def test_benchmark_runs_sequential_jobs_and_verifies_seed_resolution():
    calls = []
    active = None
    times = [0]

    def clock():
        times[0] += .25
        return times[0]

    def requester(origin, method, path, data=None):
        nonlocal active
        calls.append((method, path))
        if path == "/health":
            return {"status": "ready", "active_generation": False, "models": ["juggernaut-xl"]}
        if path == "/jobs" and method == "POST":
            assert active is None
            active = data
            return {"id": format(len([c for c in calls if c == ("POST", "/jobs")]), "024x")}
        assert path.startswith("/jobs/")
        assert active is not None
        if method == "GET":
            params = active["payload"]
            active = None
            return {
                "status": "completed",
                "result": {
                    "model": "juggernaut-xl", "steps": params["steps"],
                    "seed": params["seed"], "width": 1216, "height": 1216,
                    "path": "/locally/generated/not-made-by-test.webp",
                },
                "performance_timings": {
                    "execution_ms": 25000, "provider_and_setup_ms": 21000,
                    "runtime_return_ms": 3000,
                },
            }
        raise AssertionError("Unexpected request")

    result = benchmark.run_compare(
        "http://127.0.0.1:8030", "A realistic fox", 7,
        getter=requester, clock=clock, sleep=lambda _sec: None,
    )
    assert len(result) == 3
    assert [sample["steps"] for sample in result] == [30, 35, 40]
    assert calls == [
        ("GET", "/health"), ("POST", "/jobs"), ("GET", "/jobs/" + format(1, "024x")),
        ("POST", "/jobs"), ("GET", "/jobs/" + format(2, "024x")),
        ("POST", "/jobs"), ("GET", "/jobs/" + format(3, "024x")),
    ]


def test_benchmark_never_starts_when_busy_or_nonlocal():
    with pytest.raises(Exception):
        benchmark.origin_only("https://otherhost.example:8030")
    with pytest.raises(Exception):
        benchmark.origin_only("http://127.0.0.1:8030/evil")
    with pytest.raises(RuntimeError, match="ready and idle"):
        benchmark.run_compare(
            "http://127.0.0.1:8030", "A realistic fox", 17,
            getter=lambda _origin, _method, _path: {
                "status": "busy", "active_generation": True,
                "models": ["juggernaut-xl"],
            },
        )


def test_benchmark_stops_and_cancels_only_its_own_failed_job():
    calls = []
    job_id = "a" * 24

    def requester(origin, method, path, data=None):
        calls.append((method, path))
        if path == "/health":
            return {"status": "ready", "active_generation": False, "models": ["juggernaut-xl"]}
        if path == "/jobs" and method == "POST":
            return {"id": job_id}
        if path == "/jobs/" + job_id and method == "GET":
            return {"status": "failed", "error": "synthetic failure"}
        if path == "/jobs/" + job_id + "/cancel" and method == "POST":
            return {"status": "failed"}
        raise AssertionError("Unexpected request")

    with pytest.raises(RuntimeError, match="compare aborted"):
        benchmark.run_compare(
            "http://127.0.0.1:8030", "A realistic fox", 7,
            getter=requester, sleep=lambda _s: None,
        )
    assert calls == [
        ("GET", "/health"), ("POST", "/jobs"),
        ("GET", "/jobs/" + job_id),
        ("POST", "/jobs/" + job_id + "/cancel"),
    ]


def test_backend_applies_requested_30_35_40_without_reducing_resolution(monkeypatch):
    import image_service as service

    monkeypatch.setattr(service, "_generation_model", lambda *_args: {
        "id": "juggernaut-xl", "model_family": "sdxl", "base_model": "sdxl",
        "provider": "sdxl", "default_steps": 35, "default_guidance": 4.0,
    })
    params = []
    for step in benchmark.STEPS:
        resolved = service._resolve_generation(service.Generate(
            prompt="A detailed realistic fox", model="juggernaut-xl",
            quality="quality", width=512, height=512,
            steps=step, guidance=4.0, seed=31337, auto_size=True,
        ))
        p = resolved["params"]
        assert (p["width"], p["height"]) == (1216, 1216)
        assert p["steps"] == step
        assert p["guidance"] == 4.0
        assert p["scheduler"] == "dpmpp-2m-sde-karras"
        assert p["seed"] == 31337
        params.append(p)
    assert all(params[0][key] == item[key]
               for item in params[1:]
               for key in params[0] if key != "steps")
    # The original quality and standard profiles must retain their defaults.
    assert service._resolve_generation(service.Generate(
        prompt="A detailed realistic fox", model="juggernaut-xl",
        quality="quality", width=512, height=512, auto_size=True,
    ))["params"]["steps"] == 40
    assert service._resolve_generation(service.Generate(
        prompt="A detailed realistic fox", model="juggernaut-xl",
        quality="standard", width=512, height=512, auto_size=True,
    ))["params"]["steps"] == 35
