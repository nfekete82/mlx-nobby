#!/usr/bin/env python3
"""Read-only, opt-in DFlash2 quality A/B benchmark for the active MLX runtime.

Runs frozen German/reasoning/Python/JavaScript *code comprehension* questions,
grades exact canonical answers, plus a long-output speed probe. It NEVER runs
generated code, changes models, restarts services, downloads weights, or logs
the prompt/response texts. Run separately in verified OFF and ON runtime modes.
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
import shlex
import statistics
import subprocess
import sys
import time

import httpx

SUITE = "mlx-nobby-dflash-ab-v1"
DRAFT_MODEL = "z-lab/Qwen3.8-27B-DFlash2"
ORIGIN = "http://127.0.0.1:8000"
FORMAT = '\nAntworte NUR als gültiges JSON-Objekt {"answer":"..."} ohne weitere Felder oder Erklärung.'
# Frozen, authored, answer-keyed public questions. Avoid fuzzy LLM-as-a-judge.
# Coding tasks test language reasoning, NOT execution or code-generation quality.
CASES = (
    ("de-remaining", "german", "Ein Verein besitzt 48 Eintrittskarten. Am Montag verkauft er 13, Dienstag 17 und Mittwoch 8. Wie viele bleiben?", "10"),
    ("de-train", "german", "Ein Zug startet um 14:35 Uhr. Die Fahrzeit beträgt 90 Minuten. Wann kommt er an? Antwort HH:MM.", "16:05"),
    ("de-logic", "german", "Alle roten Boxen sind schwer. Einige schwere Boxen sind rund. Folgt daraus zwingend, dass alle roten Boxen rund sind? Antworte ja oder nein.", "nein"),
    ("de-reading", "german", "Lena gibt Tim ihr Buch. Tim gibt es Eva. Eva legt es in ihren Rucksack. Bei wem ist das Buch nun?", "Eva"),
    ("reason-order", "reasoning", "Anna ist älter als Bernd. Carla ist jünger als Anna, aber älter als Bernd. Wer ist am zweitältesten? Nur Vorname.", "Carla"),
    ("reason-profit", "reasoning", "Ein Händler kauft 24 Bücher für je 7 Euro. Er verkauft 18 für je 11 Euro und die restlichen 6 für je 5 Euro. Wie hoch ist sein Gewinn in Euro? Nur Zahl.", "60"),
    ("reason-handshakes", "reasoning", "Acht Personen schütteln einander jeweils genau einmal die Hand. Wie viele Handschläge sind es insgesamt?", "28"),
    ("reason-combinations", "reasoning", "Vier verschiedene Bücher liegen auf dem Tisch. Wie viele Möglichkeiten gibt es, zwei davon ohne Reihenfolge auszuwählen?", "6"),
    ("reason-sequence", "reasoning", "Ergänze die Folge: 2, 6, 12, 20, 30, ?. Nur Zahl.", "42"),
    ("py-odds", "python", "Was gibt folgender Python-3-Code aus? Nur die ausgegebene Zahl. values=[1,2,3,4,5]; print(sum(x*x for x in values if x%2==1))", "35"),
    ("py-alias", "python", "Was gibt dieser Python-3-Code aus? a=[1,2]; b=a; b += [3]; print(len(a)). Nur Zahl.", "3"),
    ("py-default", "python", "Python-3: def f(x, a=[]): a.append(x); return len(a). Danach: print(f(1)+f(2)). Welche Zahl wird ausgegeben?", "3"),
    ("py-slice", "python", "Python-3: s='nobby'; print(s[1:4][::-1]). Wie lautet die Ausgabe exakt?", "bbo"),
    ("js-loop", "javascript", "JavaScript: let n=0; for (let i=0;i<5;i++) { if (i%2===0) n+=i; } console.log(n); Was wird ausgegeben? Nur Zahl.", "6"),
    ("js-map", "javascript", "JavaScript: const xs=[1,2,3,4]; console.log(xs.filter(x=>x%2===0).map(x=>x*3).join(',')); Was wird ausgegeben? Nur den Text.", "6,12"),
    ("js-var", "javascript", "JavaScript: const arr=[]; for(var i=0;i<3;i++){arr.push(()=>i);} console.log(arr.map(f=>f()).join(',')); Was wird ausgegeben?", "3,3,3"),
    ("js-strict", "javascript", 'JavaScript: console.log(0 === false ? "ja" : "nein"); Wie lautet die Ausgabe?', "nein"),
)
SPEED_PROMPT = (
    "Erkläre KV-Cache, Prefill, Decoding, Speculative Decoding und Unified Memory "
    "bei lokalen KI-Modellen in zehn getrennten Absätzen mit jeweils mindestens "
    "drei vollständigen Sätzen. Beschreibe konkrete Vor- und Nachteile."
)
SUITE_HASH = hashlib.sha256(json.dumps(
    (CASES, SPEED_PROMPT), ensure_ascii=False, separators=(",", ":")
).encode("utf-8")).hexdigest()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="Run frozen tasks with runtime-mode verification")
    run.add_argument("--mode", required=True, choices=("off", "on"))
    run.add_argument("--model", required=True, help="Exact active model path/ID")
    run.add_argument("--url", default=ORIGIN, help="Only http://127.0.0.1:8000 allowed")
    run.add_argument("--repeats", type=int, default=2, choices=(1, 2, 3, 4, 5))
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("--output", type=Path, required=True)
    compare = sub.add_parser("compare", help="Offline A/B comparison from two reports")
    compare.add_argument("--off", type=Path, required=True)
    compare.add_argument("--on", type=Path, required=True)
    compare.add_argument("--output", type=Path)
    return p


def verify_runtime(mode: str, model: str, url: str, output: Path) -> None:
    """Fail closed if the process args do not prove the expected OFF/ON mode."""
    if url.rstrip("/") != ORIGIN or not model.strip():
        raise ValueError("Only the fixed 127.0.0.1:8000 runtime and a nonempty model are supported")
    if output.is_symlink() or output.exists():
        raise ValueError("Refusing to overwrite an existing output path")
    ps = subprocess.run(["ps", "-axo", "command"], text=True, capture_output=True,
                        timeout=8, check=True)
    matches = []
    for line in ps.stdout.splitlines():
        try:
            args = shlex.split(line)
        except ValueError:
            continue
        if "-m" not in args or "mlx_vlm" not in args or "server" not in args:
            continue
        try:
            if args[args.index("--port") + 1] != "8000":
                continue
            if args[args.index("--model") + 1] != model:
                continue
        except (IndexError, ValueError):
            continue
        matches.append(args)
    if len(matches) != 1:
        raise RuntimeError("Cannot uniquely verify the active 8000 MLX-VLM model process")
    args = matches[0]
    draft = args[args.index("--draft-model") + 1] if "--draft-model" in args else None
    if mode == "off" and draft is not None:
        raise RuntimeError("Expected OFF but a --draft-model is active")
    if mode == "on":
        kind = args[args.index("--draft-kind") + 1] if "--draft-kind" in args else None
        if draft != DRAFT_MODEL or kind != "dflash":
            raise RuntimeError("Expected ON with the exact Qwen3.8 DFlash2 drafter")


def answer_from_response(content) -> str | None:
    """Strict JSON contract; no arbitrary code, eval, substring or LLM grading."""
    if not isinstance(content, str) or len(content) > 8192:
        return None
    try:
        parsed = json.loads(content.strip())
    except (ValueError, TypeError):
        return None
    if (not isinstance(parsed, dict) or set(parsed) != {"answer"}
            or not isinstance(parsed["answer"], str)):
        return None
    return parsed["answer"].strip()


def positive_float(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    num = float(value)
    return num if math.isfinite(num) and num > 0 else None


def query(client, model: str, prompt: str, limit: int, timeout: int) -> dict:
    payload = {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "max_tokens": limit, "stream": False,
    }
    start = time.perf_counter()
    response = client.post("/v1/chat/completions", json=payload, timeout=timeout)
    wall_ms = round((time.perf_counter() - start) * 1000, 3)
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("Unusually large model response")
    body = response.json()
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Invalid model response: choices")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise ValueError("Invalid model response: message")
    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        raise ValueError("Invalid model response: usage")
    timing = body.get("timings") or {}
    if not isinstance(timing, dict):
        timing = {}
    tokens = usage.get("completion_tokens")
    generation_ms = positive_float(timing.get("predicted_ms"))
    tps = round(tokens * 1000 / generation_ms, 3) if (
        type(tokens) is int and tokens > 0 and generation_ms is not None
    ) else None
    return {
        "answer": answer_from_response(message.get("content")),
        "wall_ms": wall_ms,
        "generation_tps": tps,
        "completion_tokens": tokens if type(tokens) is int and tokens >= 0 else None,
        "finish_reason": choices[0].get("finish_reason"),
    }


def median(values) -> float | None:
    clean = [value for value in values if positive_float(value) is not None]
    return round(statistics.median(clean), 3) if clean else None


def summarize(records: list[dict]) -> dict:
    graded = [row for row in records if row.get("graded")]
    groups = {}
    for category in ("german", "reasoning", "python", "javascript"):
        selected = [r for r in graded if r["category"] == category]
        groups[category] = {
            "correct": sum(r["correct"] for r in selected),
            "total": len(selected),
        }
    correct = sum(r["correct"] for r in graded)
    speed = [r for r in records if not r.get("graded")]
    return {
        "quality": {
            "correct": correct, "total": len(graded),
            "accuracy": round(correct / len(graded), 4) if graded else None,
            "by_category": groups,
        },
        "speed_probe": {
            "count": len(speed),
            "median_wall_ms": median([r["wall_ms"] for r in speed]),
            "median_generation_tps": median([r["generation_tps"] for r in speed]),
            "median_completion_tokens": median([r["completion_tokens"] for r in speed]),
            "hit_token_cap": sum(r.get("finish_reason") == "length" for r in speed),
        },
    }


def run(args) -> dict:
    if not 1 <= args.repeats <= 5 or not 5 <= args.timeout <= 600:
        raise ValueError("Invalid bounded repeats/timeout")
    verify_runtime(args.mode, args.model, args.url, args.output)
    records = []
    with httpx.Client(base_url=ORIGIN, trust_env=False) as client:
        for rep in range(1, args.repeats + 1):
            for case_id, category, question, expected in CASES:
                result = query(client, args.model, question + FORMAT, 128, args.timeout)
                records.append({
                    "id": case_id, "category": category, "repeat": rep,
                    "graded": True, "correct": result.pop("answer") == expected,
                    **result,
                })
                print(f"{args.mode} {rep}/{args.repeats} {case_id}: "
                      f"{'OK' if records[-1]['correct'] else 'FAIL'}", file=sys.stderr)
            result = query(client, args.model, SPEED_PROMPT, 384, args.timeout)
            result.pop("answer")
            records.append({
                "id": "long-speed", "category": "speed", "repeat": rep,
                "graded": False, **result,
            })
            print(f"{args.mode} {rep}/{args.repeats} speed: "
                  f"{result['generation_tps']} tokens/s", file=sys.stderr)
    report = {
        "schema": 1, "suite": SUITE, "suite_sha256": SUITE_HASH,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode, "model": args.model, "repeats": args.repeats,
        "verified_process_mode": True, "summary": summarize(records),
        "results": records,
        "limitations": [
            "Exact-answer coding comprehension, NOT generated-code execution or code-generation quality.",
            "Small authored benchmark, not a general intelligence or safety evaluation.",
            "One short and one long prompt workload; acceptance rate not measured.",
            "Mode checked once before run; do not change runtime while tests run.",
            "No prompts, completions, local paths (other than model identifier), or generated code saved.",
            "Sampling and thermal state may vary. Run only on an idle machine.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive 0600 report creation; never overwrite a previous measurement.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return report


def compare(off: dict, on: dict) -> dict:
    for report, mode in ((off, "off"), (on, "on")):
        if (report.get("suite") != SUITE or report.get("suite_sha256") != SUITE_HASH
                or report.get("mode") != mode or not report.get("verified_process_mode")):
            raise ValueError("Wrong suite/hash/mode or unverified runtime in input report")
    if off.get("model") != on.get("model") or off.get("repeats") != on.get("repeats"):
        raise ValueError("A/B comparisons must use the same model and repetitions")
    off_rows = {(r["repeat"], r["id"]): r for r in off["results"]}
    on_rows = {(r["repeat"], r["id"]): r for r in on["results"]}
    expected_keys = {(repeat, case[0]) for repeat in range(1, off["repeats"] + 1)
                     for case in CASES} | {
                         (repeat, "long-speed") for repeat in range(1, off["repeats"] + 1)
                     }
    if set(off_rows) != expected_keys or set(on_rows) != expected_keys:
        raise ValueError("Missing, duplicate or unexpected A/B tasks")
    off_summary = summarize(list(off_rows.values()))
    on_summary = summarize(list(on_rows.values()))
    before = off_summary["speed_probe"]["median_generation_tps"]
    after = on_summary["speed_probe"]["median_generation_tps"]
    speed_gain = round((after / before - 1) * 100, 2) if before and after else None
    regressions = sorted(
        {"id": case_id, "repeat": repeat}
        for repeat, case_id in expected_keys
        if case_id != "long-speed" and off_rows[repeat, case_id]["correct"]
        and not on_rows[repeat, case_id]["correct"]
    , key=lambda r: (r["repeat"], r["id"]))
    # Passing this tiny suite cannot establish model-wide parity.
    quality_ok = on_summary["quality"]["correct"] >= off_summary["quality"]["correct"] and not regressions
    recommendation = (
        "candidate_for_broader_review" if quality_ok and speed_gain is not None and speed_gain >= 10
        else "inconclusive_or_regression"
    )
    return {
        "schema": 1, "suite": SUITE, "model": off["model"], "repeats": off["repeats"],
        "off": off_summary, "on": on_summary,
        "speed_gain_pct": speed_gain,
        "quality_delta_correct": (on_summary["quality"]["correct"]
                                  - off_summary["quality"]["correct"]),
        "cases_regressed": regressions,
        "recommendation": recommendation,
        "interpretation": "Candidate only, never automatic configuration/quality approval.",
    }


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "run":
            summary = run(args)["summary"]
            print(json.dumps({"mode": args.mode, "summary": summary}, ensure_ascii=False, indent=2))
        else:
            off = json.loads(args.off.read_text(encoding="utf-8"))
            on = json.loads(args.on.read_text(encoding="utf-8"))
            result = compare(off, on)
            encoded = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                if args.output.is_symlink() or args.output.exists():
                    raise ValueError("Refusing to overwrite comparison output")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
                args.output.chmod(0o600)
            print(encoded)
        return 0
    except (ValueError, RuntimeError, OSError, httpx.HTTPError, KeyError, TypeError) as exc:
        print(f"Benchmark failed (runtime unchanged): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
