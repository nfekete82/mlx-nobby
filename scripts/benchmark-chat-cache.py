#!/usr/bin/env python3
"""Three-turn reproducible web-chat APC benchmark (stdlib only)."""
from __future__ import annotations

import argparse
import json
import time
import os
from pathlib import Path
import urllib.request
import urllib.error

QUESTIONS = (
    "Wie funktioniert der Arbeitsspeicher bei Apple-Silicon-Prozessoren?",
    "Welche Vorteile bietet dieser gemeinsame Arbeitsspeicher beim Betrieb lokaler KI-Modelle?",
    "Wie kann ich diese Vorteile auf einem Mac mit 48 GB RAM optimal nutzen?",
)
CHART_SUFFIX = ('\nWhen the user asks for a data analysis or numeric comparison and real numeric data are available, optionally include ONE fenced nobby-chart JSON block after your explanation. Format: {"type":"auto","title":"Short title","unit":"€","data":[{"label":"2025-01","value":12.5},{"label":"2025-02","value":15.2}]}. Values must be finite JSON numbers, not strings. Only use measured or supplied values: never invent numbers, sources or time series. Prefer text when charts do not improve the answer. Use part_of_whole:true only for actual nonnegative parts of a whole. Never place untrusted data in code or HTML.\n')


def read_json(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.load(res)


def cache_stats(url: str) -> dict:
    return read_json(url.rstrip("/") + "/v1/cache/stats")


def counts(stats: dict) -> dict:
    return {key: int(stats.get(key) or 0) for key in
            ("exact_hits", "matched_tokens", "exact_stores")}


def delta(previous: dict, current: dict) -> dict:
    return {key: current[key] - previous[key] for key in previous}


def iter_sse(response):
    """Read SSE blocks, including multiline data and named error events."""
    lines = []
    for raw in response:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if lines:
                yield parse_sse_block(lines)
                lines = []
            continue
        if not line.startswith(":"):
            lines.append(line)
    if lines:
        yield parse_sse_block(lines)


def parse_sse_block(lines):
    event_name = "message"
    data = []
    for line in lines:
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    return event_name, "\n".join(data)


def stream_answer(web_url: str, payload: dict, timeout: int = 900):
    request = urllib.request.Request(
        web_url.rstrip("/") + "/api/chat/stream",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    first_ms = None
    parts = []
    done = False
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for name, data in iter_sse(response):
            if name == "error":
                raise RuntimeError(data[:500])
            if name == "done":
                done = True
                break
            if not data:
                continue
            try:
                item = json.loads(data)
            except json.JSONDecodeError:
                continue
            if item.get("type") == "error" or item.get("error"):
                raise RuntimeError(str(item.get("error") or item)[:500])
            if item.get("type") == "content":
                chunk = item.get("text", "")
                if chunk:
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - start) * 1000)
                    parts.append(chunk)
    total_ms = round((time.perf_counter() - start) * 1000)
    if not done:
        raise RuntimeError("SSE stream ended without done event")
    answer = "".join(parts)
    if not answer.strip():
        raise RuntimeError("No assistant content returned")
    return answer, first_ms, total_ms


def read_diagnostic_lines(path: str, offset: int):
    """Read new complete diagnostic lines only, surviving log truncation."""
    with open(path, "rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        if end < offset:
            offset = 0
        stream.seek(offset)
        raw = stream.read()
    if not raw:
        return end, []
    parts = raw.rsplit(b"\n", 1)
    if len(parts) == 1:
        return offset, []
    complete = parts[0] + b"\n"
    new_offset = offset + len(complete)
    lines = complete.decode("utf-8", errors="replace").splitlines()
    return new_offset, [line for line in lines if "HYBRID_APC_DIAG" in line]


def summarize_diagnostics(lines):
    lookups = [line for line in lines if "stored=False" in line]
    if not lookups:
        return None
    return lookups[-1].split("HYBRID_APC_DIAG ", 1)[-1]


def secure_write_json(filename: str, content: str):
    """Explicit opt-in: save potentially sensitive model text as owner-only."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(filename, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(content)


def load_replay_answers(filename: str):
    """Validate the captured baseline before reusing any assistant replies."""
    with open(filename, encoding="utf-8") as stream:
        data = json.load(stream)
    answers = data.get("answers")
    if not isinstance(answers, list) or len(answers) != len(QUESTIONS):
        raise ValueError("Replay needs exactly three saved benchmark answers")
    for index, (entry, question) in enumerate(zip(answers, QUESTIONS), 1):
        if not isinstance(entry, dict) or entry.get("turn") != index or entry.get("question") != question:
            raise ValueError(f"Replay turn {index} does not match the benchmark question")
        value = entry.get("answer")
        if not isinstance(value, str) or not value.strip() or len(value) > 100000:
            raise ValueError(f"Replay turn {index} has invalid answer text")
    return tuple(entry["answer"] for entry in answers)


def run(args):
    try:
        prior = counts(cache_stats(args.server_url))
        log_offset = None
        if getattr(args, "diagnose", False):
            if not os.path.isfile(args.log_file):
                raise RuntimeError(f"No server log: {args.log_file}")
            log_offset = os.path.getsize(args.log_file)
            print("DIAG: requires NOBBY_HYBRID_CACHE_DIAG=1 in mlx-server", flush=True)
        replay_file = getattr(args, "replay_answers", None)
        replay_answers = load_replay_answers(replay_file) if replay_file else None
        history = []
        rows = []
        captured_answers = []
        for number, question in enumerate(QUESTIONS, 1):
            history.append({"role": "user", "content": question})
            payload = {
                "messages": history,
                "system_prompt": args.system_prompt + (CHART_SUFFIX if args.chart_suffix else ""),
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
            }
            answer, first_ms, total_ms = stream_answer(args.web_url, payload, timeout=args.timeout)
            current = counts(cache_stats(args.server_url))
            diff = delta(prior, current)
            diagnostic = None
            if getattr(args, "diagnose", False):
                log_offset, lines = read_diagnostic_lines(args.log_file, log_offset)
                diagnostic = summarize_diagnostics(lines)
            prior = current
            history.append({"role": "assistant", "content":
                            replay_answers[number - 1] if replay_answers else answer})
            row = {"turn": number, "first_content_ms": first_ms,
                   "total_ms": total_ms, "answer_chars": len(answer),
                   **{"delta_" + k: v for k, v in diff.items()}}
            if getattr(args, "diagnose", False):
                row["hybrid_diagnostic"] = diagnostic
            rows.append(row)
            if getattr(args, "answers_out", None):
                captured_answers.append({"turn": number, "question": question, "answer": answer})
            print(f"Turn {number}: first={first_ms}ms total={total_ms}ms "
                  f"hits+{diff['exact_hits']} matched+{diff['matched_tokens']} "
                  f"stores+{diff['exact_stores']} chars={len(answer)}", flush=True)
            if getattr(args, "diagnose", False):
                print("  HYBRID lookup: " + (diagnostic or "no in-process diagnostic record"), flush=True)
        print("TOTAL hits+", sum(r["delta_exact_hits"] for r in rows),
              "matched+", sum(r["delta_matched_tokens"] for r in rows))
        if getattr(args, "answers_out", None):
            content = json.dumps({"answers": captured_answers}, ensure_ascii=False, indent=2) + "\n"
            secure_write_json(args.answers_out, content)
        if args.json_out:
            from pathlib import Path
            Path(args.json_out).write_text(json.dumps({
                "web_url": args.web_url, "server_url": args.server_url,
                "note": "Cumulative shared-server counters; concurrent chats affect deltas.",
                "history_mode": "fixed_replay" if replay_answers else "generated",
                "turns": rows,
            }, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"BENCHMARK FAILED: {type(exc).__name__}: {exc}", flush=True)
        return 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--web-url", default="http://127.0.0.1:8090")
    p.add_argument("--server-url", default="http://127.0.0.1:8000")
    p.add_argument("--system-prompt", default="", help="Exact browser system prompt, if known")
    p.add_argument("--chart-suffix", action="store_true", help="Append browser chart guidance")
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--max-tokens", type=int, default=700)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--json-out")
    p.add_argument("--answers-out", help="OPT-IN: write raw answers as private 0600 JSON; may contain sensitive content")
    p.add_argument("--replay-answers", help="Use saved baseline assistant replies in subsequent prompts; still measure and capture fresh generated replies")
    p.add_argument("--diagnose", action="store_true", help="Read per-turn hybrid cache lookup reason from server log")
    p.add_argument("--log-file", default=str(Path.home() / ".config/mlx-web/server-error.log"))
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
