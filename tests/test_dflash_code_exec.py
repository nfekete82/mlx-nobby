"""Offline checks for Docker-isolated generated-code DFlash A/B v3."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import subprocess

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-dflash-code-exec.py"
spec = importlib.util.spec_from_file_location("dflash_code_exec", PATH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_frozen_suite_includes_coding_and_known_failures():
    ids = [t["id"] for t in bench.TASKS]
    assert len(ids) == len(set(ids)) == 9
    assert {t["language"] for t in bench.TASKS} == {"python", "javascript", "php"}
    assert {"py-reverse-slice", "py-book-profit", "js-even-loop", "js-var-closure"} <= set(ids)
    assert len(bench.SUITE_HASH) == 64
    assert bench.SUITE != bench.v2.SUITE
    assert all(t["tests"].count(bench.SENTINEL) == 1 for t in bench.TASKS)


def test_no_host_commands_and_unsafe_docker_permissions():
    for task in bench.TASKS:
        command = bench.sandbox_command(task, "nobby-test")
        joined = " ".join(command)
        assert command[:2] == ["docker", "run"]
        for arg in ["--network=none", "--read-only", "--cap-drop=ALL",
                    "--security-opt=no-new-privileges", "--pull=never",
                    "--pids-limit=64", "--memory=256m", "--cpus=1",
                    "--user=65534:65534"]:
            assert arg in joined
        assert not any(a in command for a in ("--privileged", "-v", "--mount", "-P", "-p"))
        assert command[-len(bench.IMAGES[task["language"]][1]) - 1] == bench.IMAGES[task["language"]][0]


@pytest.mark.parametrize("raw,language,expected,label", [
    ("def f(): return 3", "python", "def f(): return 3", "plain"),
    ("fenced-python", "python", "def f(): pass", "fenced"),
    ("fenced-js", "javascript", "function f() {}", "fenced"),
    ("fenced-php", "php", "function x() {}", "fenced"),
    ("<?php function x() {}", "php", None, "invalid"),
    ("function x() {} ?>", "php", None, "invalid"),
    ("fenced-with-extra", "php", None, "invalid"),
    (None, "python", None, "invalid"),
    ("", "python", None, "invalid"),
])
def test_code_extraction_is_strict(raw, language, expected, label):
    if raw == "fenced-python":
        raw = bench.FENCE + "python\ndef f(): pass\n" + bench.FENCE
    if raw == "fenced-js":
        raw = bench.FENCE + "js\nfunction f() {}\n" + bench.FENCE
    if raw == "fenced-php":
        raw = bench.FENCE + "php\nfunction x() {}\n" + bench.FENCE
    if raw == "fenced-with-extra":
        raw = bench.FENCE + "php\nfunction f() {}\n" + bench.FENCE + "\nExplanation"
    assert bench.normalize_code(raw, language) == (expected, label)


def test_preflight_fails_closed_without_cli_or_images():
    with patch.object(bench.shutil, "which", return_value=None):
        with pytest.raises(RuntimeError, match="CLI missing"):
            bench.docker_preflight()
    proc = SimpleNamespace(returncode=0)
    missing = SimpleNamespace(returncode=1)
    with (patch.object(bench.shutil, "which", return_value="/usr/bin/docker"),
          patch.object(bench.subprocess, "run", side_effect=[proc, missing]) as run):
        with pytest.raises(RuntimeError, match="Missing cached image"):
            bench.docker_preflight()
    assert run.call_count == 2
    assert run.call_args.args[0][:3] == ["docker", "image", "inspect"]


def test_sandbox_stdin_only_and_stdout_not_in_return_value():
    p = SimpleNamespace(returncode=0, stdout="PRIVATE OUTPUT\n" + bench.SENTINEL,
                        stderr="PRIVATE ERROR")
    task = bench.ID_MAP["py-stock"]
    with (patch.object(bench.subprocess, "run", return_value=p) as runner,
          patch.object(bench.time, "perf_counter", side_effect=[1.0, 1.02])):
        result = bench.sandbox_run(task, "def allocate_stock(a,b): return a", 15)
    assert result == {"passed": True, "reason": "pass", "sandbox_ms": 20.0}
    kwargs = runner.call_args.kwargs
    assert "def allocate_stock(a,b): return a" in kwargs["input"]
    assert task["tests"] in kwargs["input"]
    assert kwargs["capture_output"] is True
    assert "PRIVATE OUTPUT" not in str(result)
    assert "PRIVATE ERROR" not in str(result)


def test_sandbox_works_only_on_success_and_marker():
    task = bench.ID_MAP["php-sku"]
    with patch.object(bench.subprocess, "run",
                      return_value=SimpleNamespace(returncode=1, stdout=bench.SENTINEL)):
        assert bench.sandbox_run(task, "function canonicalSku($s) {return $s;}", 15)["passed"] is False
    with patch.object(bench.subprocess, "run",
                      return_value=SimpleNamespace(returncode=0, stdout="no marker")):
        assert bench.sandbox_run(task, "function canonicalSku($s) {return $s;}", 15)["passed"] is False
    with patch.object(bench.subprocess, "run",
                      return_value=SimpleNamespace(returncode=125, stdout="")):
        with pytest.raises(RuntimeError, match="Docker could not start"):
            bench.sandbox_run(task, "function canonicalSku($s) {return $s;}", 15)


def test_timeout_triggers_container_cleanup():
    timeout = subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=4)
    done = SimpleNamespace(returncode=0)
    with patch.object(bench.subprocess, "run", side_effect=[timeout, done]) as run:
        result = bench.sandbox_run(bench.ID_MAP["py-stock"], "def foo(): pass", 4)
    assert result["reason"] == "timeout"
    assert run.call_count == 2
    assert run.call_args.args[0][:3] == ["docker", "rm", "-f"]


def fake_report(mode, repeats=2, failures=()):
    failures = set(failures)
    rows = []
    for rep in range(1, repeats + 1):
        for task in bench.TASKS:
            rows.append({
                "id": task["id"], "language": task["language"], "repeat": rep,
                "passed": (rep, task["id"]) not in failures,
                "finish_reason": "stop", "generation_tps": 40,
            })
    return {
        "schema": 3, "suite": bench.SUITE, "suite_sha256": bench.SUITE_HASH,
        "mode": mode, "model": "/model", "repeats": repeats,
        "docker_timeout": 15, "verified_process_mode": True,
        "results": rows,
    }


def test_comparison_reports_improvements_and_regressions():
    off = fake_report("off", failures={(1, "py-stock")})
    on = fake_report("on", failures={(1, "js-even-loop")})
    out = bench.compare(off, on)
    assert out["quality_delta_correct"] == 0
    assert out["regressed"] == [{"repeat": 1, "id": "js-even-loop"}]
    assert out["new_passes"] == [{"repeat": 1, "id": "py-stock"}]
    assert out["recommendation"] == "inconclusive_or_regression"


def test_zero_success_is_not_a_positive_candidate():
    all_failures = {(rep, task["id"]) for rep in (1, 2) for task in bench.TASKS}
    result = bench.compare(fake_report("off", failures=all_failures),
                           fake_report("on", failures=all_failures))
    assert result["on"]["correct"] == 0
    assert result["regressed"] == []
    assert result["recommendation"] == "inconclusive_or_regression"


def test_comparison_rejects_duplicate_missing_and_unsafe_reports():
    off, on = fake_report("off"), fake_report("on")
    assert bench.compare(off, on)["recommendation"] == "candidate_for_manual_code_review"
    on["results"].append(on["results"][0].copy())
    with pytest.raises(ValueError, match="Missing, duplicate"):
        bench.compare(off, on)
    on = fake_report("on")
    on["suite_sha256"] = "invalid"
    with pytest.raises(ValueError, match="hash"):
        bench.compare(off, on)
    on = fake_report("on")
    on["results"][0]["language"] = "php"
    with pytest.raises(ValueError, match="language"):
        bench.compare(off, on)


def test_run_no_generated_source_persisted_and_process_checked_twice(tmp_path):
    out = tmp_path / "report.json"
    args = SimpleNamespace(mode="on", model="/model", url=bench.v2.ORIGIN,
                           repeats=1, timeout=240, docker_timeout=15, output=out)
    model = "PRIVATE GENERATED SOURCE"
    def fake_request(*_a, **_kw):
        return {
            "content": model, "wall_ms": 300, "generation_tps": 25,
            "completion_tokens": 100, "finish_reason": "stop",
        }
    with (patch.object(bench.v2.legacy, "verify_runtime") as verifier,
          patch.object(bench, "docker_preflight") as preflight,
          patch.object(bench.v2, "request", side_effect=fake_request),
          patch.object(bench, "sandbox_run", return_value={
              "passed": True, "reason": "pass", "sandbox_ms": 20,
          }) as runner, patch.object(bench.httpx, "Client")):
        report = bench.run(args)
    assert verifier.call_count == 2
    preflight.assert_called_once()
    assert runner.call_count == len(bench.TASKS)
    assert report["summary"]["correct"] == len(bench.TASKS)
    saved = out.read_text(encoding="utf-8")
    assert model not in saved
    assert "Verteilt available" not in saved
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="overwrite"):
        bench.v2.write_exclusive(out, {})


def test_run_rejects_unbounded_repetitions(tmp_path):
    args = SimpleNamespace(mode="on", model="/model", url=bench.v2.ORIGIN,
                           repeats=6, timeout=240, docker_timeout=15,
                           output=tmp_path / "x")
    with pytest.raises(ValueError, match="1..5"):
        bench.run(args)
