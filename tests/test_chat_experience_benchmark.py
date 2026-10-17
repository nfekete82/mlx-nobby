"""CPU-only tests for the opt-in Nobby protected streaming benchmark."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-chat-experience.py"
SPEC = importlib.util.spec_from_file_location("chat_experience_bench", SCRIPT)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_loopback_only_and_bounded_workload():
    assert bench.local_agent_url("http://127.0.0.1:8010/") == "http://127.0.0.1:8010"
    assert bench.local_agent_url("http://[::1]:8010") == "http://[::1]:8010"
    for bad in (
        "https://127.0.0.1:8010", "http://localhost:8010",
        "http://192.168.1.3:8010", "http://example.com:8010",
        "http://127.0.0.1:8010/x", "http://127.0.0.1:8010/?token=secret",
        "http://admin@127.0.0.1:8010", "http://127.0.0.1",
    ):
        with pytest.raises(Exception):
            bench.local_agent_url(bad)
    assert bench.context_sizes("4000,8000,16000") == [4000, 8000, 16000]
    for bad in ("", "4000,4000", "900", "17000", "4000,8000,12000,16000", "x"):
        with pytest.raises(Exception):
            bench.context_sizes(bad)


def test_synthetic_context_is_private_and_prefix_stable():
    a = bench.synthetic_context(4000, "nonce", "original")
    b = bench.synthetic_context(4000, "nonce", "original")
    control = bench.synthetic_context(4000, "nonce", "control")
    assert a == b
    assert len(a) == 16000
    assert len(control) == len(a)
    assert a != control
    assert "BENCHMARK-original-nonce" in a


def test_agent_sse_uses_visible_content_not_heartbeat_as_ttft():
    ticks = iter([1.01, 1.015, 1.02, 1.08, 1.09, 1.1])
    lines = [
        b": heartbeat\n", b'data: {"type":"reasoning","text":"hidden"}\n',
        b'data: {"type":"content","text":"O"}\n',
        b'data: {"type":"content","text":"K"}\n',
        b"event: done\n", b"data: {}\n",
    ]
    # One clock tick per raw SSE line, and one on completion.
    ticks = iter([1.01, 1.015, 1.02, 1.08, 1.09, 1.1, 1.11])
    row, text = bench.parse_stream(lines, 1.0, clock=lambda: next(ticks))
    assert text == "OK"
    assert row["first_transport_ms"] == pytest.approx(10)
    assert row["first_content_ms"] == pytest.approx(20)
    assert row["total_ms"] == pytest.approx(110)
    assert row["output_characters"] == 2


def test_stream_errors_and_incomplete_responses_are_not_success():
    with pytest.raises(RuntimeError, match="error"):
        bench.parse_stream([b"event: error\n", b'data: {"error":"secret path"}\n'], 0, clock=lambda: 1)
    with pytest.raises(RuntimeError, match="complete visible response"):
        bench.parse_stream([b'data: {"type":"content","text":"partial"}\n'], 0, clock=lambda: 1)
    with pytest.raises(RuntimeError, match="complete visible response"):
        bench.parse_stream([b"event: done\n", b"data: {}\n"], 0, clock=lambda: 1)


def test_stream_post_uses_agent_runtime_gateway(monkeypatch):
    posted = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def __iter__(self):
            return iter([
                b'data: {"type":"content","text":"OK"}\n',
                b"event: done\n",
                b"data: {}\n",
            ])
    def fake_open(request, timeout):
        posted.append((request.full_url, json.loads(request.data), timeout))
        return Response()
    monkeypatch.setattr(bench, "urlopen", fake_open)
    row, text = bench.agent_stream(
        "http://127.0.0.1:8010", [{"role": "user", "content": "test"}], 32, 40
    )
    assert row["output_characters"] == 2 and text == "OK"
    assert posted[0][0] == "http://127.0.0.1:8010/api/runtime/chat/stream"
    assert posted[0][1]["auto_route"] is False
    assert posted[0][1]["stream"] is True
    assert posted[0][1]["max_tokens"] == 32


def test_runtime_activity_is_refused_and_history_is_separate():
    with pytest.raises(RuntimeError, match="observatory"):
        bench.check_idle({"ok": False})
    for kind in ("chat", "image", "video"):
        with pytest.raises(RuntimeError, match="active"):
            bench.check_idle({"ok": True, "system": {"runtimes": {kind: {"active": True}}}})
    snap = {"model": {"recent_calls": [
        {"purpose": "router.classify", "status": "completed", "timings_ms": {"total": 550}},
        {"purpose": "router.classify", "status": "completed", "timings_ms": {"total": 650}},
        {"purpose": "chat.stream", "status": "completed", "timings_ms": {"total": 900}},
        {"purpose": "router.classify", "status": "failed", "timings_ms": {"total": 200}},
    ]}}
    assert bench.router_history(snap)["total_ms"]["p50"] == 600
    assert bench.router_history(snap)["historical_completed_calls"] == 2


def test_experiment_reuses_same_prefix_and_never_reports_content(monkeypatch):
    calls = []
    snap = {"ok": True, "system": {"runtimes": {"chat": {"active": False}}},
            "model": {"recent_calls": []}}
    monkeypatch.setattr(bench, "request_json", lambda *args, **kwargs: snap)
    def fake_stream(_url, messages, _tokens, _timeout):
        calls.append(messages)
        n = len(calls)
        return ({"first_transport_ms": 1, "first_content_ms": 10 + n,
                 "total_ms": 30 + n, "output_characters": 2}, "OK")
    monkeypatch.setattr(bench, "agent_stream", fake_stream)
    monkeypatch.setattr(bench.secrets, "token_hex", lambda count: "abcdef")
    report = bench.run("http://127.0.0.1:8010", [4000], 1, 48, 30)
    assert len(calls) == 4
    assert len(calls[1]) == 2  # priming
    assert len(calls[2]) == 4  # reuse prior context
    assert calls[2][:2] == calls[1]
    assert calls[2][-2]["content"] == "OK"
    assert calls[3][1] != calls[1][1]  # cold-ish changed prefix control
    assert report["contexts"][0]["control_minus_followup_first_content_ms"] == 1
    serial = json.dumps(report)
    assert "BENCHMARK" not in serial and "abcdef" not in serial
    assert "synthetischen Daten" not in serial
    assert report["router"]["historical_completed_calls"] == 0
    assert report["short"]["first_content_ms"]["count"] == 1


def test_private_report_does_not_overwrite(tmp_path):
    target = tmp_path / "report.json"
    bench.save_private(target, {"schema": 1})
    assert json.loads(target.read_text()) == {"schema": 1}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        bench.save_private(target, {"schema": 2})
