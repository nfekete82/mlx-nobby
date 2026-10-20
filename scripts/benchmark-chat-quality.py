#!/usr/bin/env python3
"""Opt-in synthetic chat-quality baseline through Nobby's protected Agent stream.

44 strict answer-keyed cases and 4 manual review cases; no model changes,
configuration writes, prompts/completions in main report or live inference in CI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


SUITE = "mlx-nobby-chat-quality-v1"
SUITE_FILE = Path(__file__).resolve().parents[1] / "benchmarks/chat-quality-v1.json"
DEFAULT_AGENT = "http://127.0.0.1:8010"
JSON_INSTRUCTION = '\nAntworte ausschließlich als gültiges JSON-Objekt {"answer":"..."} mit genau diesem einen String-Feld. Keine Erklärung.'
MAX_SSE_BYTES = 512_000
MAX_ANSWER_CHARS = 8_192


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Avoid proxies and redirects: benchmark messages never go to a remote host.
OPENER = build_opener(ProxyHandler({}), NoRedirect())


def loopback_origin(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "::1"}
            or parts.port is None or parts.username is not None or parts.password is not None
            or parts.path not in {"", "/"} or parts.query or parts.fragment):
        raise argparse.ArgumentTypeError("Use an explicit HTTP loopback Agent origin, e.g. http://127.0.0.1:8010")
    return value.rstrip("/")


def suite() -> tuple[list[dict], str]:
    raw = SUITE_FILE.read_bytes()
    if len(raw) > 100_000:
        raise ValueError("Benchmark dataset is unexpectedly large")
    payload = json.loads(raw)
    cases = payload.get("cases")
    if payload.get("suite") != SUITE or payload.get("schema") != 1 or not isinstance(cases, list):
        raise ValueError("Unexpected dataset")
    if len(cases) != 48 or sum(c.get("kind") == "exact" for c in cases) != 44:
        raise ValueError("Dataset must contain the frozen 44+4 cases")
    ids = set()
    for case in cases:
        ident = case.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,64}", ident) or ident in ids:
            raise ValueError("Duplicate/invalid case ID")
        ids.add(ident)
        if case.get("kind") not in ("exact", "review") or not isinstance(case.get("category"), str):
            raise ValueError("Missing category or grading mode")
        messages = case.get("messages")
        if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict) or messages[-1].get("role") != "user":
            raise ValueError("Invalid conversation history")
        if any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
               or not isinstance(m.get("content"), str) or not m["content"]
               or len(m["content"]) > 5_000 for m in messages):
            raise ValueError("Invalid conversation message")
        if case["kind"] == "exact" and (not isinstance(case.get("expected"), str) or not case["expected"]):
            raise ValueError("Missing reference answer")
        if case["kind"] == "review" and (not isinstance(case.get("review_checks"), list)
                                        or not case["review_checks"] or not all(
                                            isinstance(x, str) and x for x in case["review_checks"])):
            raise ValueError("Missing review criteria")
    return cases, hashlib.sha256(raw).hexdigest()


def get_json(origin: str, path: str, timeout: int = 15) -> dict:
    req = Request(origin + path, headers={"Accept": "application/json"})
    with OPENER.open(req, timeout=timeout) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise RuntimeError("Oversized Agent response")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid Agent JSON")
    return payload


def verify_status(status: dict, original: dict | None = None) -> dict:
    model = status.get("model")
    if status.get("online") is not True or not isinstance(model, str) or not model:
        raise RuntimeError("Chat runtime is not online")
    pid = status.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise RuntimeError("Running model PID could not be verified")
    identity = {"model": model, "pid": pid, "thinking": status.get("thinking"), "port": status.get("port")}
    if original is not None and identity != original:
        raise RuntimeError("Model identity, PID, or runtime settings changed during the benchmark")
    return identity


def check_idle(snapshot: dict) -> None:
    if snapshot.get("ok") is not True or not isinstance(snapshot.get("system"), dict):
        raise RuntimeError("Agent observatory unavailable")
    runtimes = snapshot["system"].get("runtimes")
    if not isinstance(runtimes, dict):
        raise RuntimeError("Runtime activity is unknown")
    for kind in ("chat", "image", "video"):
        state = runtimes.get(kind)
        if not isinstance(state, dict) or state.get("active") is not False:
            raise RuntimeError("Runtime not confirmed idle: " + kind)


def active_messages(case: dict) -> list[dict]:
    messages = [dict(m) for m in case["messages"]]
    if case["kind"] == "exact":
        messages[-1]["content"] += JSON_INSTRUCTION
    return messages


def parse_stream(chunks, started: float, clock=time.monotonic) -> tuple[dict, str]:
    first_transport = None
    first_content = None
    answer = []
    answer_chars = 0
    count_bytes = 0
    block = []
    done = False

    def parse_event(lines: list[str]) -> bool:
        nonlocal first_content, answer_chars
        event_name = "message"
        data = []
        for line in lines:
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        body = "\n".join(data)
        if event_name == "error":
            raise RuntimeError("Agent stream error")
        if event_name == "done" or body == "[DONE]":
            return True
        if not body:
            return False
        try:
            event = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Malformed Agent stream") from exc
        if not isinstance(event, dict) or event.get("error") or event.get("type") == "error":
            raise RuntimeError("Agent stream error")
        chunk = event.get("text") if event.get("type") == "content" else None
        if chunk is None and isinstance(event.get("choices"), list) and event["choices"]:
            choice = event["choices"][0]
            if isinstance(choice, dict) and isinstance(choice.get("delta"), dict):
                chunk = choice["delta"].get("content")
        if isinstance(chunk, str) and chunk:
            if first_content is None:
                first_content = clock()
            answer_chars += len(chunk)
            if answer_chars > MAX_ANSWER_CHARS:
                raise RuntimeError("Model response too long for benchmark")
            answer.append(chunk)
        return event.get("type") == "done"

    for raw in chunks:
        if first_transport is None:
            first_transport = clock()
        raw = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
        count_bytes += len(raw)
        if count_bytes > MAX_SSE_BYTES:
            raise RuntimeError("Agent SSE exceeds size limit")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if block and parse_event(block):
                done = True
                break
            block.clear()
        elif not line.startswith(":"):
            block.append(line)
    if not done and block:
        done = parse_event(block)
    finished = clock()
    if not done or first_content is None or not "".join(answer).strip():
        raise RuntimeError("No complete visible Agent answer")
    return {
        "first_content_ms": round((first_content - started) * 1000, 3),
        "first_transport_ms": round((first_transport - started) * 1000, 3),
        "total_ms": round((finished - started) * 1000, 3),
        "output_characters": answer_chars,
    }, "".join(answer)


def agent_stream(origin: str, messages: list[dict], max_tokens: int, timeout: int) -> tuple[dict, str]:
    payload = {"messages": messages, "temperature": 0, "max_tokens": max_tokens,
               "stream": True, "auto_route": False}
    req = Request(origin + "/api/runtime/chat/stream",
                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                  method="POST")
    started = time.monotonic()
    with OPENER.open(req, timeout=timeout) as response:
        return parse_stream(response, started)


def exact_answer(text: str) -> str | None:
    if not isinstance(text, str) or len(text) > MAX_ANSWER_CHARS:
        return None
    try:
        data = json.loads(text.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or set(data) != {"answer"} or not isinstance(data["answer"], str):
        return None
    return unicodedata.normalize("NFC", data["answer"].strip()).casefold()


def summary(rows: list[dict], cases: list[dict]) -> dict:
    keyed = {r["id"]: r for r in rows}
    exact = [c for c in cases if c["kind"] == "exact"]
    finished = [keyed[c["id"]] for c in exact if c["id"] in keyed]
    correct = sum(r.get("grade") == "correct" for r in finished)
    by_category = {}
    for category in sorted({c["category"] for c in exact}):
        selected = [r for r in finished if r["category"] == category]
        by_category[category] = {
            "correct": sum(r.get("grade") == "correct" for r in selected),
            "completed": len(selected),
            "total": sum(c["category"] == category for c in exact),
        }

    def timing(key):
        values = sorted(r[key] for r in rows if type(r.get(key)) in (int, float)
                        and math.isfinite(r[key]) and r[key] >= 0)
        if not values:
            return {"count": 0, "p50": None, "p95": None}
        def percentile(p):
            n = (len(values) - 1) * p
            lo, hi = math.floor(n), math.ceil(n)
            return round(values[lo] + (values[hi] - values[lo]) * (n - lo), 3)
        return {"count": len(values), "p50": percentile(.5), "p95": percentile(.95)}

    return {
        "automatic": {
            "correct": correct, "completed": len(finished), "total": len(exact),
            "accuracy": round(correct / len(exact), 4) if len(finished) == len(exact) else None,
            "by_category": by_category,
        },
        "manual_review": {
            "completed": sum(r.get("grade") == "review_pending" for r in rows),
            "total": len(cases) - len(exact), "status": "not_automatically_scored",
        },
        "first_content_ms": timing("first_content_ms"),
        "total_ms": timing("total_ms"),
    }


def fresh_paths(paths: list[Path]) -> None:
    if len({str(p.absolute()) for p in paths}) != len(paths):
        raise ValueError("Output files must have distinct paths")
    for p in paths:
        if p.is_symlink() or p.exists():
            raise FileExistsError("Refusing to overwrite a previous report")
        if not p.parent.is_dir():
            raise ValueError("Output directory does not exist")


def write_private(path: Path, data: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2, ensure_ascii=False)
        out.write("\n")


def run(origin: str, output: Path, review_file: Path | None, max_tokens: int = 256,
        timeout: int = 180, smoke: bool = False) -> dict:
    cases, fingerprint = suite()
    fresh_paths([output] + ([review_file] if review_file is not None else []))
    if smoke:
        seen, chosen = set(), []
        for c in cases:
            if c["category"] not in seen:
                seen.add(c["category"])
                chosen.append(c)
    else:
        chosen = cases
    before = verify_status(get_json(origin, "/api/status"))
    check_idle(get_json(origin, "/api/performance/observatory?limit=100"))
    records = []
    reviews = []
    error_type = None
    try:
        for index, case in enumerate(chosen, 1):
            verify_status(get_json(origin, "/api/status"), before)
            check_idle(get_json(origin, "/api/performance/observatory?limit=100"))
            timing, answer = agent_stream(origin, active_messages(case), max_tokens, timeout)
            row = {"id": case["id"], "category": case["category"], "kind": case["kind"], **timing}
            if case["kind"] == "exact":
                value = exact_answer(answer)
                if value is None:
                    row["grade"] = "invalid_format"
                else:
                    expected = unicodedata.normalize("NFC", case["expected"].strip()).casefold()
                    row["grade"] = "correct" if value == expected else "incorrect"
            else:
                row["grade"] = "review_pending"
                if review_file is not None:
                    reviews.append({"id": case["id"], "category": case["category"],
                                    "messages": case["messages"], "review_checks": case["review_checks"],
                                    "answer": answer})
            records.append(row)
            print(f"[{index}/{len(chosen)}] {case['id']}: {row['grade']} | "
                  f"TTFT {timing['first_content_ms']} ms", flush=True)
        verify_status(get_json(origin, "/api/status"), before)
        check_idle(get_json(origin, "/api/performance/observatory?limit=100"))
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        error_type = type(exc).__name__
        print("Benchmark aborted: " + error_type + " (details withheld)", file=sys.stderr)
    complete = error_type is None and not smoke and len(records) == len(cases)
    report = {
        "schema": 1, "suite": SUITE, "suite_sha256": fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if complete else "partial", "smoke": smoke,
        "error_type": error_type, "runtime": before,
        "parameters": {"temperature": 0, "max_tokens": max_tokens, "auto_route": False,
                       "transport": "agent_protected_stream"},
        "summary": summary(records, cases), "results": records,
        "limitations": [
            "Strict exact-answer checks are not general reasoning scores.",
            "Human-review tasks are not automatically scored.",
            "Synthetic source-grounding does not exercise real RAG retrieval.",
            "SSE timing is first visible content, not native generation tokens/s.",
            "No prompts or generated answers are saved in the main report.",
            "Warm caches, ordering and concurrent workloads influence latency.",
        ],
    }
    write_private(output, report)
    if review_file is not None:
        write_private(review_file, {"schema": 1, "suite_sha256": fingerprint,
                                   "status": report["status"], "cases": reviews,
                                   "note": "Generated text is for human review; not automatically scored"})
    return report


def validate_report(report: dict, cases: list[dict], fingerprint: str) -> dict[str, dict]:
    if (report.get("schema") != 1 or report.get("suite") != SUITE
            or report.get("suite_sha256") != fingerprint
            or report.get("status") != "complete" or report.get("smoke") is not False
            or report.get("error_type") is not None):
        raise ValueError("Comparison requires complete same-suite reports")
    rows = report.get("results")
    if not isinstance(rows, list) or len(rows) != len(cases):
        raise ValueError("Missing or unexpected results")
    if [r.get("id") for r in rows if isinstance(r, dict)] != [c["id"] for c in cases]:
        raise ValueError("Case order or IDs differ from frozen suite")
    for case, row in zip(cases, rows):
        if row.get("kind") != case["kind"] or row.get("category") != case["category"]:
            raise ValueError("Wrong grading category")
        allowed = {"correct", "incorrect", "invalid_format"} if case["kind"] == "exact" else {"review_pending"}
        if row.get("grade") not in allowed:
            raise ValueError("Invalid grading outcome")
        if any(type(row.get(key)) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0
               for key in ("first_content_ms", "total_ms")):
            raise ValueError("Invalid timing")
    runtime = report.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("model"), str) or not runtime["model"]:
        raise ValueError("Missing runtime identity")
    return {r["id"]: r for r in rows}


def compare(baseline: dict, candidate: dict) -> dict:
    cases, fingerprint = suite()
    old = validate_report(baseline, cases, fingerprint)
    new = validate_report(candidate, cases, fingerprint)
    if baseline.get("parameters") != candidate.get("parameters"):
        raise ValueError("Benchmark generation parameters differ")
    previous = summary(baseline["results"], cases)
    current = summary(candidate["results"], cases)
    regressed = [c["id"] for c in cases if c["kind"] == "exact"
                 and old[c["id"]]["grade"] == "correct" and new[c["id"]]["grade"] != "correct"]
    improved = [c["id"] for c in cases if c["kind"] == "exact"
                and old[c["id"]]["grade"] != "correct" and new[c["id"]]["grade"] == "correct"]

    def delta(key):
        before, after = previous[key]["p50"], current[key]["p50"]
        return round((after / before - 1) * 100, 2) if before and after is not None else None

    return {
        "schema": 1, "suite": SUITE, "suite_sha256": fingerprint,
        "baseline_model": baseline["runtime"]["model"],
        "candidate_model": candidate["runtime"]["model"],
        "quality_delta_correct": current["automatic"]["correct"] - previous["automatic"]["correct"],
        "newly_correct": improved, "regressed_cases": regressed,
        "baseline_summary": previous, "candidate_summary": current,
        "median_first_content_delta_pct": delta("first_content_ms"),
        "median_total_delta_pct": delta("total_ms"),
        "decision": "REGRESSION_REVIEW" if regressed else "REVIEW",
        "interpretation": "Human review required; synthetic exact tests do not certify production quality.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="Opt-in synthetic suite against already running local Agent")
    p.add_argument("--agent-url", type=loopback_origin, default=DEFAULT_AGENT)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--review-file", type=Path, help="Opt-in 0600 manual-review raw answers")
    p.add_argument("--smoke", action="store_true", help="One case per category; not comparable")
    p.add_argument("--max-tokens", type=int, choices=range(64, 513), metavar="{64..512}", default=256)
    p.add_argument("--timeout", type=int, choices=range(15, 601), metavar="{15..600}", default=180)
    p = sub.add_parser("compare", help="Compare full reports offline")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            report = run(args.agent_url, args.output, args.review_file, args.max_tokens, args.timeout, args.smoke)
            print(json.dumps({"status": report["status"], "summary": report["summary"],
                              "output": str(args.output)}, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "complete" or (args.smoke and report["error_type"] is None) else 1
        if args.baseline.stat().st_size > 2_000_000 or args.candidate.stat().st_size > 2_000_000:
            raise ValueError("Comparison report is too large")
        if args.output:
            fresh_paths([args.output])
        result = compare(json.loads(args.baseline.read_text(encoding="utf-8")),
                         json.loads(args.candidate.read_text(encoding="utf-8")))
        if args.output:
            write_private(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("Chat quality command failed: " + type(exc).__name__ + " (details withheld)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
