"""No-model, no-network regression suite for DFlash2 quality A/B runner."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-dflash-quality.py"
spec = importlib.util.spec_from_file_location("benchmark_dflash_quality", PATH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def process(model, mode):
    flags = (" --draft-model z-lab/Qwen3.8-27B-DFlash2 --draft-kind dflash"
             if mode == "on" else "")
    return ("/opt/mlx/bin/python -m mlx_vlm server"
            f" --model {model} --host 127.0.0.1 --port 8000{flags}")


def test_public_task_ids_answers_and_categories_are_fixed():
    ids = [task[0] for task in bench.CASES]
    assert len(ids) == len(set(ids)) >= 16
    assert {case[1] for case in bench.CASES} == {"german", "reasoning", "python", "javascript"}
    assert all(isinstance(item[2], str) and isinstance(item[3], str) for item in bench.CASES)
    assert len(bench.SUITE_HASH) == 64
    assert "exec(" not in bench.SPEED_PROMPT


@pytest.mark.parametrize("mode", ["on", "off"])
def test_runtime_guard_accepts_only_matching_process(tmp_path, mode):
    result = SimpleNamespace(stdout=process("/tmp/current", mode) + "\n", returncode=0)
    with patch.object(bench.subprocess, "run", return_value=result):
        bench.verify_runtime(mode, "/tmp/current", bench.ORIGIN, tmp_path / "result.json")


def test_runtime_guard_rejects_wrong_mode_model_url_and_existing_output(tmp_path):
    result = SimpleNamespace(stdout=process("/tmp/current", "on") + "\n", returncode=0)
    with patch.object(bench.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="Expected OFF"):
            bench.verify_runtime("off", "/tmp/current", bench.ORIGIN, tmp_path / "new.json")
        with pytest.raises(RuntimeError, match="uniquely"):
            bench.verify_runtime("on", "/tmp/different", bench.ORIGIN, tmp_path / "new.json")
        with pytest.raises(ValueError, match="127.0.0.1"):
            bench.verify_runtime("on", "/tmp/current", "http://external.invalid:8000",
                                 tmp_path / "new.json")
        (tmp_path / "existing.json").write_text("{}")
        with pytest.raises(ValueError, match="overwrite"):
            bench.verify_runtime("on", "/tmp/current", bench.ORIGIN, tmp_path / "existing.json")


@pytest.mark.parametrize("raw,expected", [
    ('{"answer":"Carla"}', "Carla"),
    (' {"answer":"6,12"} ', "6,12"),
    ('{"answer": 5}', None),
    ('{"answer":"5","extra":true}', None),
    ('plain text not JSON', None),
    ('{"answer":"5"}\n{"answer":"6"}', None),
    ('{"answer":"5"} extra', None),
    ('{"answer":"5"', None),
    ('not json', None),
    (None, None),
])
def test_strict_json_answer_is_deterministic_and_fails_closed(raw, expected):
    assert bench.answer_from_response(raw) == expected


def test_query_posts_fixed_nonstreaming_payload_and_does_not_return_raw_text():
    response = Mock()
    response.content = b'{"choices": "private output"}'
    response.json.return_value = {
        "choices": [{"message": {"content": '{"answer":"10"}'},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 44, "completion_tokens": 20},
        "timings": {"predicted_ms": 500.0},
    }
    client = Mock()
    client.post.return_value = response
    with patch.object(bench.time, "perf_counter", side_effect=[0.0, 0.55]):
        data = bench.query(client, "/test/model", "Safe public question", 128, 120)
    assert data["answer"] == "10"
    assert data["generation_tps"] == 40.0
    assert data["wall_ms"] == 550.0
    payload = client.post.call_args.kwargs["json"]
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    assert payload["model"] == "/test/model"
    assert payload["max_tokens"] == 128
    assert "private output" not in str(data)
    assert "Safe public question" not in str(data)


def synthetic(mode, repeats=2, wrong=()):
    wrong = set(wrong)
    rows = []
    for rep in range(1, repeats + 1):
        for case_id, category, _, _ in bench.CASES:
            rows.append({
                "id": case_id, "repeat": rep, "category": category,
                "graded": True, "correct": (rep, case_id) not in wrong,
                "wall_ms": 100, "generation_tps": 40,
            })
        rows.append({"id": "long-speed", "repeat": rep, "category": "speed",
                     "graded": False, "wall_ms": 12000 if mode == "off" else 9000,
                     "generation_tps": 30 if mode == "off" else 40,
                     "completion_tokens": 384, "finish_reason": "length"})
    return {
        "suite": bench.SUITE, "suite_sha256": bench.SUITE_HASH, "mode": mode,
        "model": "/test/target", "repeats": repeats, "verified_process_mode": True,
        "results": rows,
    }


def test_compare_reports_speed_gain_and_unchanged_quality_only_as_candidate():
    result = bench.compare(synthetic("off"), synthetic("on"))
    assert result["speed_gain_pct"] == pytest.approx(33.33)
    assert result["quality_delta_correct"] == 0
    assert result["cases_regressed"] == []
    assert result["off"]["quality"]["correct"] == len(bench.CASES) * 2
    assert result["recommendation"] == "candidate_for_broader_review"


def test_compare_detects_regression_even_if_aggregate_is_same():
    off = synthetic("off", wrong={(1, "de-remaining")})
    on = synthetic("on", wrong={(1, "reason-order")})
    report = bench.compare(off, on)
    assert report["quality_delta_correct"] == 0
    assert report["cases_regressed"] == [{"id": "reason-order", "repeat": 1}]
    assert report["recommendation"] == "inconclusive_or_regression"


def test_compare_rejects_changed_model_suite_mode_and_incomplete_run():
    off, on = synthetic("off"), synthetic("on")
    on["model"] = "/different"
    with pytest.raises(ValueError, match="same model"):
        bench.compare(off, on)
    on["model"] = off["model"]
    on["suite_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="suite"):
        bench.compare(off, on)
    on["suite_sha256"] = bench.SUITE_HASH
    on["results"].pop()
    with pytest.raises(ValueError, match="Missing"):
        bench.compare(off, on)


def test_run_report_contains_metrics_only_and_preserves_runtime(tmp_path):
    out = tmp_path / "private.json"
    args = SimpleNamespace(mode="on", model="/model", url=bench.ORIGIN,
                           output=out, repeats=1, timeout=120)
    def fake_query(_client, _model, prompt, limit, timeout):
        if limit == 384:
            return {"answer": "PRIVATE RESPONSE", "wall_ms": 9000,
                    "generation_tps": 40, "completion_tokens": 384,
                    "finish_reason": "length"}
        case = next(item for item in bench.CASES if prompt.startswith(item[2]))
        return {"answer": case[3], "wall_ms": 100,
                "generation_tps": 38, "completion_tokens": 8,
                "finish_reason": "stop"}
    with (patch.object(bench, "verify_runtime") as verify,
          patch.object(bench, "query", side_effect=fake_query),
          patch.object(bench.httpx, "Client") as mock_client):
        report = bench.run(args)
    verify.assert_called_once()
    mock_client.assert_called_once_with(base_url=bench.ORIGIN, trust_env=False)
    assert report["summary"]["quality"]["correct"] == len(bench.CASES)
    raw = out.read_text(encoding="utf-8")
    assert "PRIVATE RESPONSE" not in raw
    assert "Ein Verein" not in raw
    assert '"correct": true' in raw
    assert json.loads(raw)["verified_process_mode"]
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="overwrite"):
        bench.verify_runtime("on", "/model", bench.ORIGIN, out)
