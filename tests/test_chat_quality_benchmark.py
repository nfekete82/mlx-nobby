"""CPU-only Chat Quality v1 contracts; no live inference in CI."""
import importlib.util
import json
from pathlib import Path
import stat

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark-chat-quality.py"
SPEC = importlib.util.spec_from_file_location("chat_quality_benchmark", SCRIPT)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def status():
    return {"model": "qwen-fixture", "online": True, "thinking": False, "pid": 1234, "port": 8000}


def idle():
    return {"ok": True, "system": {"runtimes": {name: {"active": False}
            for name in ("chat", "image", "video")}}}


def test_frozen_suite_has_objective_and_manual_cases():
    cases, fingerprint = bench.suite()
    assert len(cases) == 48 and len(fingerprint) == 64
    assert len({c["id"] for c in cases}) == 48
    assert sum(c["kind"] == "exact" for c in cases) == 44
    assert sum(c["kind"] == "review" for c in cases) == 4
    assert {"german", "reasoning", "php", "javascript", "sql", "context"}.issubset(
        {c["category"] for c in cases})


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8010", "http://localhost:8010", "http://192.168.0.2:8010",
    "http://example.com:8010", "http://user@127.0.0.1:8010",
    "http://127.0.0.1:8010/x", "http://127.0.0.1:8010/?key=secret",
    "http://127.0.0.1",
])
def test_loopback_only(url):
    with pytest.raises(Exception):
        bench.loopback_origin(url)


def test_strict_answer_format_and_context():
    assert bench.loopback_origin("http://127.0.0.1:8010/") == "http://127.0.0.1:8010"
    assert bench.exact_answer('{"answer":"  GRÜN "}') == "grün"
    for bad in ('{"answer":5}', '{"answer":"yes","more":2}', "42", "{}", "", "[42]"):
        assert bench.exact_answer(bad) is None
    cases, _ = bench.suite()
    case = next(c for c in cases if c["category"] == "context")
    clone = bench.active_messages(case)
    assert clone[-1]["content"].endswith(bench.JSON_INSTRUCTION)
    assert case["messages"][-1]["content"] != clone[-1]["content"]
    manual = next(c for c in cases if c["kind"] == "review")
    assert bench.active_messages(manual) == manual["messages"]


def test_sse_ignores_reasoning_and_heartbeat():
    frames = [
        b": heartbeat\n", b"\n",
        b'data: {"type":"reasoning","text":"hidden"}\n', b"\n",
        b'data: {"type":"content","text":"O"}\n', b"\n",
        b'data: {"type":"content","text":"K"}\n', b"\n",
        b"event: done\n", b"data: {}\n", b"\n",
    ]
    ticks = iter(range(101, 200))
    row, answer = bench.parse_stream(frames, 100, clock=lambda: next(ticks))
    assert answer == "OK"
    assert row["first_content_ms"] > row["first_transport_ms"]
    assert row["output_characters"] == 2
    for bad in (
        [b'data: {"type":"content","text":"partial"}\n', b"\n"],
        [b"event: error\n", b'data: {"error":"private"}\n', b"\n"],
        [b"event: done\n", b"data: {}\n", b"\n"],
        [b" " * (bench.MAX_SSE_BYTES + 1)],
    ):
        with pytest.raises(RuntimeError):
            bench.parse_stream(bad, 0, clock=lambda: 1)


def test_preflight_rejects_busy_or_changed_runtime():
    original = bench.verify_status(status())
    bench.verify_status(status(), original)
    with pytest.raises(RuntimeError):
        bench.verify_status({**status(), "pid": 999}, original)
    with pytest.raises(RuntimeError):
        bench.verify_status({**status(), "online": False})
    bench.check_idle(idle())
    with pytest.raises(RuntimeError):
        bench.check_idle({"ok": True, "system": {"runtimes": {"chat": {"active": False}}}})
    busy = idle()
    busy["system"]["runtimes"]["image"]["active"] = True
    with pytest.raises(RuntimeError):
        bench.check_idle(busy)


def test_full_report_compare_and_privacy(monkeypatch, tmp_path):
    cases, _ = bench.suite()
    calls = []
    def get(_origin, path, *args):
        return status() if path == "/api/status" else idle()
    def stream(_origin, messages, tokens, timeout):
        case = cases[len(calls)]
        calls.append(messages)
        assert tokens == 256 and timeout == 180
        if case["kind"] == "exact":
            assert messages[-1]["content"].endswith(bench.JSON_INSTRUCTION)
            answer = json.dumps({"answer": case["expected"]}, ensure_ascii=False)
        else:
            assert messages[-1]["content"] == case["messages"][-1]["content"]
            answer = "Synthetic manual review response"
        return {"first_content_ms": 20, "first_transport_ms": 5,
                "total_ms": 50, "output_characters": len(answer)}, answer
    monkeypatch.setattr(bench, "get_json", get)
    monkeypatch.setattr(bench, "agent_stream", stream)
    output, review = tmp_path / "baseline.json", tmp_path / "manual.json"
    baseline = bench.run(bench.DEFAULT_AGENT, output, review)
    assert baseline["status"] == "complete"
    assert baseline["summary"]["automatic"]["correct"] == 44
    assert baseline["summary"]["automatic"]["accuracy"] == 1.0
    assert baseline["summary"]["manual_review"]["completed"] == 4
    assert len(calls) == 48
    assert len(json.loads(review.read_text())["cases"]) == 4
    assert "Synthetic manual review response" not in output.read_text()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(review.stat().st_mode) == 0o600
    assert bench.compare(baseline, baseline)["decision"] == "REVIEW"
    candidate = json.loads(json.dumps(baseline))
    candidate["results"][0]["grade"] = "incorrect"
    comparison = bench.compare(baseline, candidate)
    assert comparison["regressed_cases"] == [cases[0]["id"]]
    assert comparison["quality_delta_correct"] == -1
    assert comparison["decision"] == "REGRESSION_REVIEW"
    candidate["results"].pop()
    with pytest.raises(ValueError):
        bench.compare(baseline, candidate)
    candidate = json.loads(json.dumps(baseline))
    candidate["parameters"]["max_tokens"] = 128
    with pytest.raises(ValueError):
        bench.compare(baseline, candidate)
    candidate = json.loads(json.dumps(baseline))
    candidate["suite_sha256"] = "mismatch"
    with pytest.raises(ValueError):
        bench.compare(baseline, candidate)


def test_fail_closed_preserves_existing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(bench, "get_json",
                        lambda _origin, path: status() if path == "/api/status" else idle())
    calls = []
    def fail(*args):
        calls.append(args)
        raise RuntimeError("Private details must not be logged")
    monkeypatch.setattr(bench, "agent_stream", fail)
    existing = tmp_path / "existing.json"
    existing.write_text("KEEP")
    with pytest.raises(FileExistsError):
        bench.run(bench.DEFAULT_AGENT, existing, None)
    assert not calls and existing.read_text() == "KEEP"
    report = bench.run(bench.DEFAULT_AGENT, tmp_path / "partial.json", None)
    assert report["status"] == "partial" and report["error_type"] == "RuntimeError"
    assert report["summary"]["automatic"]["accuracy"] is None
    assert "Private details" not in json.dumps(report)
    with pytest.raises(ValueError):
        bench.compare(report, report)


def test_smoke_not_comparable(monkeypatch, tmp_path):
    monkeypatch.setattr(bench, "get_json",
                        lambda _origin, path: status() if path == "/api/status" else idle())
    monkeypatch.setattr(bench, "agent_stream",
                        lambda *args: ({"first_content_ms": 10, "first_transport_ms": 2,
                                       "total_ms": 20, "output_characters": 15}, '{"answer":"no"}'))
    report = bench.run(bench.DEFAULT_AGENT, tmp_path / "smoke.json", None, smoke=True)
    assert report["smoke"] is True and report["status"] == "partial"
    assert 1 < len(report["results"]) < 48
    assert report["summary"]["automatic"]["accuracy"] is None
    with pytest.raises(ValueError):
        bench.compare(report, report)


def test_owner_only_exclusive_outputs(tmp_path):
    target = tmp_path / "new.json"
    link = tmp_path / "alias.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        bench.fresh_paths([link])
    with pytest.raises(ValueError):
        bench.fresh_paths([target, target])
    bench.write_private(target, {"schema": 1})
    with pytest.raises(FileExistsError):
        bench.write_private(target, {"schema": 2})
    assert json.loads(target.read_text()) == {"schema": 1}
