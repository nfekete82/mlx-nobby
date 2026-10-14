"""A/B benchmark is opt-in, local, sequential and never relaxes GPU guards."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-qwen21-step-cache.py"
spec = importlib.util.spec_from_file_location("qwen21_step_cache_ab", SCRIPT)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


def test_sequence_alternates_with_balanced_order():
    assert ab.sequence(1) == (False, True, True, False)
    assert ab.sequence(2) == (False, True, True, False) * 2
    with pytest.raises(ValueError):
        ab.sequence(3)


@pytest.mark.parametrize("bad", [
    "http://example.com:8030",
    "https://127.0.0.1:8030",
    "http://127.0.0.1:8030/jobs",
    "http://user:pass@127.0.0.1:8030",
    "http://127.0.0.1:8030?q=a",
])
def test_local_origin_disallows_external_or_credentials(bad):
    with pytest.raises(Exception):
        ab.local_origin(bad)


def test_payload_identical_except_step_cache():
    source = Path("/tmp/not-a-real-source.png")
    off = ab.payload(source, "Original test prompt", 123, False, .12)
    on = ab.payload(source, "Original test prompt", 123, True, .12)
    assert off["model"] == on["model"] == ab.MODEL
    assert off["quality"] == on["quality"] == "quality"
    assert off["steps"] == on["steps"] == 40
    assert off["guidance"] == on["guidance"] == 1.0
    assert off["seed"] == on["seed"] == 123
    assert off["use_kv_cache"] is on["use_kv_cache"] is True
    assert off["use_step_cache"] is False
    assert on["use_step_cache"] is True
    assert "step_cache_threshold" not in off
    assert on["step_cache_threshold"] == .12
    assert {k: v for k, v in on.items() if k not in ("step_cache_threshold", "use_step_cache")} == {
        k: v for k, v in off.items() if k not in ("step_cache_threshold", "use_step_cache")
    }


def test_source_validation_accepts_only_allowed_square_images(monkeypatch, tmp_path):
    pil_image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(ab.Path, "home", lambda: tmp_path)
    folder = tmp_path / ".config" / "mlx-web" / "images"
    folder.mkdir(parents=True)
    allowed = folder / "image.png"
    pil_image.new("RGB", (1024, 1024)).save(allowed)
    assert ab.source_info(allowed) == allowed
    outside = tmp_path / "outside.png"
    outside.write_bytes(allowed.read_bytes())
    with pytest.raises(ValueError, match="approved"):
        ab.source_info(outside)
    small = folder / "small.png"
    pil_image.new("RGB", (512, 512)).save(small)
    with pytest.raises(ValueError, match="square"):
        ab.source_info(small)


def telemetry(enabled):
    return {
        "steps": 40, "width": 1024, "height": 1024,
        "guidance": 1.0, "reference_count": 1,
        "use_step_cache": enabled, "use_kv_cache": True,
        "low_ram": False, "mflux_cache_limit_gb": 8.0,
        "process_wall_ms": 80000, "tqdm_window_ms": 70000,
    }


def test_summary_requires_all_metadata_and_matching_memory_policy():
    rows = [
        {"step_cache": enabled, "total_ms": ms, "provider_timing": telemetry(enabled)}
        for enabled, ms in zip(ab.sequence(1), (90000, 70000, 72000, 92000))
    ]
    result = ab.summary(rows)
    assert result["comparable"] is True
    assert result["cache_off_median_ms"] == 91000
    assert result["cache_on_median_ms"] == 71000
    assert result["cache_on_change_pct"] == pytest.approx(-21.98, abs=.01)
    rows[1]["provider_timing"]["low_ram"] = True
    assert ab.summary(rows)["comparable"] is False
    rows[1]["provider_timing"]["low_ram"] = False
    rows[1]["provider_timing"]["width"] = 768
    assert ab.summary(rows)["comparable"] is False
    rows[1]["provider_timing"]["width"] = 1024
    rows[1]["provider_timing"]["use_step_cache"] = None
    assert ab.summary(rows)["comparable"] is False


def test_dry_run_does_not_open_http_or_start_jobs(monkeypatch, tmp_path, capsys):
    source = tmp_path / ".config" / "mlx-web" / "images" / "source.png"
    source.parent.mkdir(parents=True)
    pil_image = pytest.importorskip("PIL.Image")
    pil_image.new("RGB", (1024, 1024)).save(source)
    monkeypatch.setattr(ab.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ab, "request_json", lambda *args, **kwargs: pytest.fail("HTTP in dry-run"))
    assert ab.main(["--source", str(source), "--prompt", "A gentle edit"]) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_run_four_jobs_sequentially_and_write_private_report(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"stable-image-input")
    posted = []
    polled = []

    def requester(origin, path, *, body=None):
        if path == "/health":
            return {"status": "ready", "models": [ab.MODEL], "active_job_id": None}
        if path.startswith("/models/"):
            return {"model_family": "qwen-image21-edit", "provider": "mflux"}
        if path == "/jobs":
            assert body["operation"] == "edit"
            posted.append(body["payload"])
            return {"id": f"{len(posted):024x}"}
        raise AssertionError(path)

    def poller(origin, job_id):
        index = int(job_id, 16) - 1
        assert index == len(polled)
        polled.append(index)
        settings = posted[index]
        return {
            "status": "completed",
            "created_at": 100.0,
            "finished_at": 100.0 + (72 if settings["use_step_cache"] else 92),
            "result": {
                "path": f"/private/output-{index}.png",
                "model": ab.MODEL, "steps": 40,
                "width": 1024, "height": 1024,
                "prompt": "SECRET PROMPT",
            },
            "provider_timing": telemetry(settings["use_step_cache"]),
        }

    monkeypatch.setattr(ab, "request_json", requester)
    output = tmp_path / "results.json"
    report = ab.run("http://127.0.0.1:8030", source, "SECRET PROMPT",
                    seed=99, cycles=1, threshold=.12, output=output,
                    requester=requester, poller=poller)
    assert len(posted) == 4
    assert [p["use_step_cache"] for p in posted] == list(ab.sequence(1))
    assert all(p["seed"] == 99 and p["steps"] == 40 for p in posted)
    assert polled == [0, 1, 2, 3]
    assert report["summary"]["comparable"] is True
    assert report["summary"]["cache_on_change_pct"] == pytest.approx(-21.74, abs=.01)
    data = output.read_text()
    assert "SECRET PROMPT" not in data
    assert str(source) not in data
    assert "/private/output-1.png" in data
    assert json.loads(data)["jobs"][2]["step_cache"] is True
    assert output.stat().st_mode & 0o777 == 0o600


def test_failed_job_stops_remaining_jobs(monkeypatch, tmp_path):
    source = tmp_path / "ref"
    source.write_text("stable")
    calls = []

    def fake(origin, path, *, body=None):
        if path == "/health":
            return {"status": "ready", "active_job_id": None, "models": [ab.MODEL]}
        if path.startswith("/models/"):
            return {"model_family": "qwen-image21-edit", "provider": "mflux"}
        if path == "/jobs":
            calls.append(body)
            return {"id": "a" * 24}
        raise AssertionError(path)

    monkeypatch.setattr(ab, "request_json", fake)
    with pytest.raises(RuntimeError, match="ended"):
        ab.run("http://127.0.0.1:8030", source, "test prompt", seed=9,
               cycles=1, threshold=.12, output=tmp_path / "failed.json",
               requester=fake, poller=lambda *args: {"status": "failed"})
    assert len(calls) == 1
