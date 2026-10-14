"""Offline, no-model, no-network tests for the opt-in DFlash2 v2 suite."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-dflash-extended.py"
spec = importlib.util.spec_from_file_location("benchmark_dflash_extended", PATH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_v2_suite_is_frozen_separate_from_v1():
    assert bench.SUITE != bench.legacy.SUITE
    assert bench.SUITE_HASH != bench.legacy.SUITE_HASH
    assert bench.CASES[:len(bench.legacy.CASES)] == bench.legacy.CASES
    assert {item[1] for item in bench.CASES} >= {
        "german", "reasoning", "python", "javascript", "php", "sql"
    }
    ids = [row[0] for row in bench.CASES + bench.SPEED_CASES]
    assert len(ids) == len(set(ids))
    assert [row[1] for row in bench.SPEED_CASES] == [1024, 1536, 1536]


@pytest.mark.parametrize("content,expected,strict,semantic,format_valid,label", [
    ('{"answer":"60"}', "60", True, True, True, "strict_json"),
    (' { "answer": "6" } ', "6", True, True, True, "strict_json"),
    ('{"answer":"6","note":"ok"}', "6", False, True, False, "extra_json_fields"),
    ("6", "6", False, True, False, "plain_answer"),
    ("6.", "6", False, False, False, "invalid_or_verbose"),
    ('{"answer":"7"}', "6", False, False, True, "strict_json"),
    ('{"answer":6}', "6", False, False, False, "invalid_or_verbose"),
    ('{"answer":"6"} extra', "6", False, False, False, "invalid_or_verbose"),
    ('{"answer":"6"}\n{"answer":"7"}', "6", False, False, False, "invalid_or_verbose"),
    (None, "6", False, False, False, "invalid"),
])
def test_classification_separates_format_from_substance(
        content, expected, strict, semantic, format_valid, label):
    result = bench.classify(content, expected)
    assert (result["correct"], result["content_correct"],
            result["format_valid"], result["format"]) == (
                strict, semantic, format_valid, label
            )


def test_query_does_not_execute_code_or_add_stream():
    response = Mock()
    response.content = b'{"choices":[]}'
    response.json.return_value = {
        "choices": [{"message": {"content": '{"answer":"B"}'}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 40},
        "timings": {"predicted_ms": 1000.0},
    }
    client = Mock()
    client.post.return_value = response
    with patch.object(bench.time, "perf_counter", side_effect=[1.0, 2.2]):
        result = bench.request(client, "/models/a", "question", 128, 60)
    assert result["content"] == '{"answer":"B"}'
    assert result["generation_tps"] == 40
    assert result["wall_ms"] == 1200
    sent = client.post.call_args.kwargs["json"]
    assert sent["stream"] is False
    assert sent["temperature"] == 0
    assert sent["max_tokens"] == 128
    assert sent["messages"] == [{"role": "user", "content": "question"}]


def synthetic(mode, repeats=2, failed=(), format_failed=(), lengths=None):
    failed, format_failed = set(failed), set(format_failed)
    rows = []
    for rep in range(1, repeats + 1):
        for name, category, _question, _expected in bench.CASES:
            correct = (rep, name) not in failed
            format_valid = (rep, name) not in format_failed
            rows.append({
                "id": name, "category": category, "repeat": rep, "graded": True,
                "correct": correct and format_valid,
                "content_correct": correct, "format_valid": format_valid,
                "format": "strict_json" if format_valid else "plain_answer",
            })
        for speed_id, max_tokens, _prompt in bench.SPEED_CASES:
            token_count = ((lengths or {}).get((rep, speed_id), max_tokens))
            rows.append({
                "id": speed_id, "category": "speed", "repeat": rep, "graded": False,
                "completion_tokens": token_count, "finish_reason": "length",
                "generation_tps": 30 if mode == "off" else 42,
                "wall_ms": 10000 if mode == "off" else 8000,
            })
    return {
        "schema": 2, "suite": bench.SUITE, "suite_sha256": bench.SUITE_HASH,
        "mode": mode, "model": "/model/qwen", "repeats": repeats,
        "verified_process_mode": True, "results": rows,
    }


def test_compare_paired_profiles_and_ten_repeats():
    out = bench.compare(synthetic("off", repeats=10), synthetic("on", repeats=10))
    assert out["speed_gain_pct"] == 40
    assert all(item["paired_samples"] == 10 for item in out["speed_profiles"].values())
    assert out["recommendation"] == "candidate_for_broader_review"
    assert out["cases_regressed"] == []
    assert out["content_regressed"] == []


def test_compare_diagnoses_plain_answer_vs_actual_wrong_answer():
    off = synthetic("off")
    on = synthetic("on", failed={(1, "js-abort")},
                   format_failed={(1, "reason-profit")})
    out = bench.compare(off, on)
    assert out["cases_regressed"] == [
        {"repeat": 1, "id": "js-abort"}, {"repeat": 1, "id": "reason-profit"}
    ]
    assert out["content_regressed"] == [{"repeat": 1, "id": "js-abort"}]
    assert out["recommendation"] == "inconclusive_or_regression"


def test_token_length_mismatch_prevents_false_speed_win():
    changed = {(rep, key): 100 for rep in (1, 2)
               for key, _, _ in bench.SPEED_CASES}
    out = bench.compare(synthetic("off"), synthetic("on", lengths=changed))
    assert out["speed_gain_pct"] is None
    assert out["recommendation"] == "inconclusive_or_regression"
    assert all(p["skipped_noncomparable"] == 2 for p in out["speed_profiles"].values())


def test_duplicate_or_incompatible_report_is_rejected():
    off, on = synthetic("off"), synthetic("on")
    on["results"].append(on["results"][0].copy())
    with pytest.raises(ValueError, match="Missing, duplicate"):
        bench.compare(off, on)
    on = synthetic("on")
    on["suite_sha256"] = "x"
    with pytest.raises(ValueError, match="hash"):
        bench.compare(off, on)
    on = synthetic("on")
    on["model"] = "other"
    with pytest.raises(ValueError, match="same model"):
        bench.compare(off, on)


def test_run_persists_metrics_only_with_mode_guards(tmp_path):
    out = tmp_path / "report.json"
    args = SimpleNamespace(mode="on", model="/model", url=bench.ORIGIN,
                           repeats=1, timeout=240, output=out)

    def fake_request(_client, _model, prompt, limit, _timeout):
        case = next((x for x in bench.CASES if prompt.startswith(x[2])), None)
        raw = '{"answer":"' + case[3] + '"}' if case else "SECRET GENERATED PHP"
        return {
            "content": raw, "wall_ms": 100, "completion_tokens": limit,
            "generation_tps": 40, "finish_reason": "length",
        }

    with (patch.object(bench.legacy, "verify_runtime") as verify,
          patch.object(bench, "request", side_effect=fake_request),
          patch.object(bench.httpx, "Client")):
        report = bench.run(args)
    assert verify.call_count == 2
    assert report["summary"]["quality"]["correct"] == len(bench.CASES)
    raw = out.read_text(encoding="utf-8")
    assert "SECRET GENERATED PHP" not in raw
    assert "Ein Verein" not in raw
    assert '"content_correct": true' in raw
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="overwrite"):
        bench.write_exclusive(out, {})


def test_run_rejects_unbounded_repetitions(tmp_path):
    args = SimpleNamespace(mode="on", model="/model", url=bench.ORIGIN,
                           repeats=11, timeout=240, output=tmp_path / "x")
    with pytest.raises(ValueError, match="1..10"):
        bench.run(args)
