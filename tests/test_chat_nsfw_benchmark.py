"""CPU-only NSFW suite contracts: opt-in, private, adult, never auto-rated."""
import importlib.util
import json
from pathlib import Path
import stat
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nobby_nsfw_benchmark", ROOT / "scripts" / "benchmark-chat-nsfw.py")
nsfw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nsfw)


def status(model="local/Qwen3.8-27B-Abliterated-MLX-4bit"):
    return {"model": model, "pid": 1234, "online": True,
            "thinking": False, "port": 8000}


def idle():
    return {"ok": True, "system": {"runtimes": {
        k: {"active": False} for k in ("chat", "image", "video")
    }}}


def monkeypatch_transport(monkeypatch, model="local/Qwen3.8-27B-Abliterated-MLX-4bit"):
    monkeypatch.setattr(nsfw.client, "get_json",
                        lambda origin, endpoint: status(model)
                        if endpoint == "/api/status" else idle())


def mock_answer(_origin, _msgs, _tokens, _timeout):
    answer = "Fiktive, einvernehmliche Erwachsene: Testantwort"
    return ({"first_content_ms": 120, "first_transport_ms": 5,
             "total_ms": 180, "output_characters": len(answer)}, answer)


def test_frozen_suite_and_consent_boundaries():
    data, fp = nsfw.suite()
    assert len(fp) == 64
    assert len(data["cases"]) == 8
    assert len({c["id"] for c in data["cases"]}) == 8
    assert set(data["rubric"]) == set(nsfw.AXES)
    assert all(c["kind"] == "review" for c in data["cases"])
    assert {"explicit-adults", "boundary-no", "context-recall", "roleplay-turn"}.issubset(
        {c["id"] for c in data["cases"]})
    assert all(any("erwachsen" in m["content"].casefold()
                   or ("(35)" in m["content"]) or ("(38)" in m["content"])
                   for m in c["messages"])
               for c in data["cases"])


def test_runtime_identity_mismatch_rejected_before_stream(monkeypatch, tmp_path):
    monkeypatch_transport(monkeypatch)
    monkeypatch.setattr(nsfw.client, "agent_stream", lambda *_: pytest.fail("no inference"))
    with pytest.raises(RuntimeError, match="EXPECTED_MODEL_MISMATCH"):
        nsfw.run(nsfw.client.DEFAULT_AGENT, tmp_path / "no-report.json",
                 tmp_path / "no-review.json", "Dark-Scarlett")
    assert not (tmp_path / "no-report.json").exists()


def test_success_report_private_and_no_automatic_quality_score(monkeypatch, tmp_path):
    monkeypatch_transport(monkeypatch)
    calls = []
    def agent(*args):
        calls.append(args)
        return mock_answer(*args)
    monkeypatch.setattr(nsfw.client, "agent_stream", agent)
    report_file = tmp_path / "qwen.json"
    review_file = tmp_path / "qwen-review.json"
    report = nsfw.run(nsfw.client.DEFAULT_AGENT, report_file, review_file, "Qwen3.8")
    assert report["status"] == "complete"
    assert report["runtime"]["model"] == status()["model"]
    assert report["summary"]["review_pending"] == 8
    assert report["summary"]["automatic_quality_score"] is None
    assert len(calls) == 8
    assert all(args[2] == 512 and args[3] == 180 for args in calls)
    raw = report_file.read_text()
    assert "Fiktive, einvernehmliche" not in raw
    assert "Nina" not in raw
    assert "Du antwortest" not in raw
    assert "Fiktive, einvernehmliche" in review_file.read_text()
    assert stat.S_IMODE(report_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(review_file.stat().st_mode) == 0o600
    return report


def test_partial_report_guard_and_noncomparison(monkeypatch, tmp_path):
    monkeypatch_transport(monkeypatch)
    n = 0
    def stream(*args):
        nonlocal n
        n += 1
        if n == 2:
            raise RuntimeError("Agent stream error")
        return mock_answer(*args)
    monkeypatch.setattr(nsfw.client, "agent_stream", stream)
    report = nsfw.run(nsfw.client.DEFAULT_AGENT, tmp_path / "partial.json",
                      tmp_path / "partial-review.json", "Qwen3.8")
    assert report["status"] == "partial"
    assert report["summary"]["review_pending"] == 1
    assert report["error_code"] == "AGENT_STREAM_ERROR"
    assert report["error_phase"] == "case_stream:explicit-adults"
    with pytest.raises(ValueError):
        nsfw.check_report(report, nsfw.suite()[0]["cases"], nsfw.suite()[1])


def full_report(monkeypatch, tmp_path, model, filename):
    monkeypatch_transport(monkeypatch, model)
    monkeypatch.setattr(nsfw.client, "agent_stream", mock_answer)
    return nsfw.run(nsfw.client.DEFAULT_AGENT, tmp_path / filename,
                    tmp_path / (filename + "-review"), model.split("/")[-1].split("-27")[0])


def scores(report):
    return {"schema": 1, "suite_sha256": report["suite_sha256"],
            "model": report["runtime"]["model"],
            "scores": [{"id": row["id"], **{a: 3 for a in nsfw.AXES}}
                       for row in report["results"]]}


def test_compare_requires_two_distinct_runtime_models_and_complete_ratings(monkeypatch, tmp_path):
    a = full_report(monkeypatch, tmp_path, "local/Qwen3.8-27B-Abliterated-MLX-4bit", "a.json")
    b = full_report(monkeypatch, tmp_path,
                    "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp", "b.json")
    grades_a, grades_b = scores(a), scores(b)
    with pytest.raises(ValueError, match="SAME model"):
        nsfw.compare(a, a, grades_a, grades_a)
    grades_b["scores"][1]["deutsch"] = 5
    result = nsfw.compare(a, b, grades_a, grades_b)
    assert result["baseline_model"] != result["candidate_model"]
    assert result["reviewed_cases"] == 8
    assert result["candidate_minus_baseline"]["deutsch"] > 0
    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    grades_b["scores"][0]["dialog"] = None
    with pytest.raises(ValueError):
        nsfw.compare(a, b, grades_a, grades_b)
    grades_b["scores"][0]["dialog"] = True
    with pytest.raises(ValueError):
        nsfw.compare(a, b, grades_a, grades_b)


def test_interactive_local_scores(monkeypatch, tmp_path):
    monkeypatch_transport(monkeypatch)
    monkeypatch.setattr(nsfw.client, "agent_stream", mock_answer)
    report = nsfw.run(nsfw.client.DEFAULT_AGENT, tmp_path / "report.json",
                      tmp_path / "reviews.json", "Qwen3.8")
    class FakeStdin:
        def isatty(self):
            return True
    monkeypatch.setattr(nsfw.sys, "stdin", FakeStdin())
    answers = iter(["4"] * (len(report["results"]) * len(nsfw.AXES)))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    score_file = tmp_path / "scores.json"
    result = nsfw.score(tmp_path / "report.json", tmp_path / "reviews.json", score_file)
    assert len(result["scores"]) == 8
    assert result["scores"][0]["grenzen"] == 4
    assert stat.S_IMODE(score_file.stat().st_mode) == 0o600


def test_no_overwrite_with_private_reports(monkeypatch, tmp_path):
    monkeypatch_transport(monkeypatch)
    monkeypatch.setattr(nsfw.client, "agent_stream", mock_answer)
    output = tmp_path / "report.json"
    review = tmp_path / "review.json"
    nsfw.run(nsfw.client.DEFAULT_AGENT, output, review, "Qwen3.8")
    with pytest.raises(FileExistsError):
        nsfw.run(nsfw.client.DEFAULT_AGENT, output, review, "Qwen3.8")
