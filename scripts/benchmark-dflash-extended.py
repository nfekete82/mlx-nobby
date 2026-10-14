#!/usr/bin/env python3
"""DFlash2 A/B v2: format diagnostics, practical coding checks, long outputs.

Opt-in and read-only: this script never changes the runtime or executes model
generated code. Reports contain only metrics and keyed correctness, never
prompts, completions, generated code, or raw model responses.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

import httpx

LEGACY_PATH = Path(__file__).with_name("benchmark-dflash-quality.py")
spec = importlib.util.spec_from_file_location("dflash_quality_v1", LEGACY_PATH)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

SUITE = "mlx-nobby-dflash-ab-v2"
ORIGIN = legacy.ORIGIN
FORMAT = legacy.FORMAT
# Public, answer-keyed multiple-choice code review, not executing or grading
# generated applications. Deliberately covers PHP + SQL in addition to v1.
CODING_CASES = (
    ("php-pdo", "php",
     "PHP 8.3: $email kommt aus einer HTTP-Anfrage. Welche Variante verhindert SQL-Injection? "
     "A) $pdo->prepare('SELECT id FROM users WHERE email = ?')->execute([$email]); "
     "B) $pdo->query(\"SELECT id FROM users WHERE email = '$email'\"); "
     "C) $pdo->exec('SELECT id FROM users WHERE email = ' . $email); "
     "Antworte nur A, B oder C.", "A"),
    ("php-coalesce", "php",
     "PHP 8: $qty=0; echo $qty ?? 5; Was wird ausgegeben? "
     "A) 5 B) 0 C) null. Antworte nur A, B oder C.", "B"),
    ("js-abort", "javascript",
     "Browser-JavaScript: Welche Option verbindet fetch korrekt mit AbortController? "
     "A) fetch(url,{abort:controller}) "
     "B) fetch(url,{signal:controller.signal}) "
     "C) fetch(url,{cancel:controller.cancel}). "
     "Antworte nur A, B oder C.", "B"),
    ("js-parallel", "javascript",
     "JavaScript: const jobs=ids.map(async id=>await load(id)); "
     "Wie wartet man auf alle Resultate und erhält ein Array? "
     "A) await Promise.all(jobs) "
     "B) await jobs "
     "C) jobs.then(). Antworte nur A, B oder C.", "A"),
    ("js-dom", "javascript",
     "JavaScript: Fremder Text aus einer API soll als reiner Text in ein HTML-Element. "
     "Welche Zuweisung verhindert HTML-Interpretation? "
     "A) el.innerHTML = input "
     "B) el.textContent = input "
     "C) el.insertAdjacentHTML('beforeend', input). "
     "Antworte nur A, B oder C.", "B"),
    ("py-default-fix", "python",
     "Python 3: Eine Funktion soll pro Aufruf eine neue Liste nutzen. "
     "Welche Signatur ist geeignet? "
     "A) def f(items=[]): ... "
     "B) def f(items={}): ... "
     "C) def f(items=None): items = [] if items is None else items; ... "
     "Antworte nur A, B oder C.", "C"),
    ("py-async", "python",
     "Python 3 asyncio: tasks enthält mehrere Coroutines. "
     "Welche Zeile wartet auf alle und liefert ihre Resultate? "
     "A) asyncio.gather(*tasks) "
     "B) await asyncio.gather(*tasks) "
     "C) await tasks. Antworte nur A, B oder C.", "B"),
    ("sql-parameter", "sql",
     "Eine MySQL-Anwendung fragt nach einem Benutzernamen. "
     "Welche SQL-Bedingung eignet sich für einen gebundenen Parameter? "
     "A) WHERE username = ? "
     "B) WHERE username = ' + input + ' "
     "C) WHERE username LIKE '%' + input + '%'. "
     "Antworte nur A, B oder C.", "A"),
)
CASES = legacy.CASES + CODING_CASES

# A single response is intentionally NOT evaluated as 'correct code'.
# Duration and token counts only; a human must review generated programs.
SPEED_CASES = (
    ("long-explanation", 1024,
     "Erkläre in deutscher Sprache die Unterschiede zwischen Prefill, KV-Cache, "
     "Decoding, Speculative Decoding und Unified Memory bei lokalen MLX-Modellen. "
     "Gehe in zehn ausführlichen Abschnitten auf Beispiele, Grenzen, Fehlermodi "
     "und einen sicheren Benchmark-Vergleich ein."),
    ("long-php-code", 1536,
     "Erstelle ein zusammenhängendes PHP-8.3-Beispiel für eine MySQL-Bestell-API "
     "mit PDO, prepared statements, Validierung, Transaktion, Idempotency-Key, "
     "Fehlerbehandlung und kommentierten Tests. Gib echten ausführbaren Beispielcode "
     "mit kurzer Erklärung. Keine externen Abhängigkeiten."),
    ("long-js-code", 1536,
     "Schreibe ein vollständiges JavaScript-ES2022-Beispiel für eine Browser-Suche "
     "mit Debounce, AbortController, Schutz gegen veraltete Responses, zugänglicher "
     "Statusausgabe und Tests für Race Conditions. Erläutere die relevanten Fehlerfälle."),
)
SUITE_HASH = hashlib.sha256(json.dumps(
    (CASES, SPEED_CASES), ensure_ascii=False, separators=(",", ":")
).encode("utf-8")).hexdigest()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="Run the v2 battery on an independently set ON/OFF runtime")
    run.add_argument("--mode", choices=("off", "on"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--url", default=ORIGIN)
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--timeout", type=int, default=240)
    run.add_argument("--output", required=True, type=Path)
    compare = sub.add_parser("compare", help="Compare offline v2 reports")
    compare.add_argument("--off", required=True, type=Path)
    compare.add_argument("--on", required=True, type=Path)
    diagnose = sub.add_parser("diagnose", help="Print raw output for four PUBLIC failing v1 questions")
    diagnose.add_argument("--mode", choices=("off", "on"), required=True)
    diagnose.add_argument("--model", required=True)
    diagnose.add_argument("--url", default=ORIGIN)
    diagnose.add_argument("--timeout", type=int, default=120)
    return p


def classify(content, expected):
    """Strict JSON vs exact-value answer; no substring/LLM-based grading."""
    if not isinstance(content, str) or len(content) > 65536:
        return {"correct": False, "content_correct": False, "format_valid": False,
                "format": "invalid"}
    stripped = content.strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
        value_ok = parsed["answer"].strip() == expected
        valid = set(parsed) == {"answer"}
        return {"correct": valid and value_ok, "content_correct": value_ok,
                "format_valid": valid, "format": "strict_json" if valid else "extra_json_fields"}
    if stripped == expected:
        return {"correct": False, "content_correct": True,
                "format_valid": False, "format": "plain_answer"}
    return {"correct": False, "content_correct": False,
            "format_valid": False, "format": "invalid_or_verbose"}


def positive_number(value):
    if type(value) not in (int, float):
        return None
    x = float(value)
    return x if math.isfinite(x) and x > 0 else None


def request(client, model, prompt, max_tokens, timeout):
    start = time.perf_counter()
    response = client.post("/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "max_tokens": max_tokens, "stream": False,
    }, timeout=timeout)
    wall_ms = round((time.perf_counter() - start) * 1000, 3)
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("Unexpectedly large response")
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"]:
        raise ValueError("Invalid model response")
    choice = body["choices"][0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ValueError("Invalid choice/message")
    usage = body.get("usage") or {}
    timings = body.get("timings") or {}
    if not isinstance(usage, dict) or not isinstance(timings, dict):
        raise ValueError("Invalid usage/timings")
    tokens = usage.get("completion_tokens")
    tokens = tokens if type(tokens) is int and tokens >= 0 else None
    predicted_ms = positive_number(timings.get("predicted_ms"))
    return {
        "content": choice["message"].get("content"),
        "wall_ms": wall_ms,
        "generation_tps": round(tokens * 1000 / predicted_ms, 3)
                          if tokens is not None and predicted_ms else None,
        "completion_tokens": tokens,
        "finish_reason": choice.get("finish_reason"),
    }


def median(values):
    # Percentage gains may legitimately be negative or zero. Do NOT discard
    # slower ON samples, or the comparison will be biased in DFlash's favor.
    values = [float(v) for v in values
              if type(v) in (int, float) and math.isfinite(float(v))]
    return round(statistics.median(values), 3) if values else None


def summarize(rows):
    graded = [r for r in rows if r["graded"]]
    quality = {
        "correct": sum(r["correct"] for r in graded),
        "content_correct": sum(r["content_correct"] for r in graded),
        "format_valid": sum(r["format_valid"] for r in graded),
        "total": len(graded),
        "by_category": {},
        "failed_ids": sorted(set(r["id"] for r in graded if not r["correct"])),
    }
    for category in sorted(set(item[1] for item in CASES)):
        rr = [r for r in graded if r["category"] == category]
        quality["by_category"][category] = {
            "correct": sum(r["correct"] for r in rr),
            "content_correct": sum(r["content_correct"] for r in rr),
            "format_valid": sum(r["format_valid"] for r in rr),
            "total": len(rr),
        }
    probes = {}
    for speed_id, limit, _ in SPEED_CASES:
        rr = [r for r in rows if r["id"] == speed_id and not r["graded"]]
        probes[speed_id] = {
            "count": len(rr), "token_limit": limit,
            "median_generation_tps": median([r["generation_tps"] for r in rr]),
            "median_wall_ms": median([r["wall_ms"] for r in rr]),
            "median_completion_tokens": median([r["completion_tokens"] for r in rr]),
            "hit_token_cap": sum(r["finish_reason"] == "length" for r in rr),
        }
    return {"quality": quality, "speed_probes": probes}


def write_exclusive(path, payload):
    if path.is_symlink() or path.exists():
        raise ValueError("Refusing to overwrite an existing report")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def run(args):
    if not 1 <= args.repeats <= 10 or not 5 <= args.timeout <= 900:
        raise ValueError("Repeats must be 1..10 and timeout 5..900 seconds")
    legacy.verify_runtime(args.mode, args.model, args.url, args.output)
    rows = []
    with httpx.Client(base_url=ORIGIN, trust_env=False) as client:
        for rep in range(1, args.repeats + 1):
            for case_id, category, question, expected in CASES:
                result = request(client, args.model, question + FORMAT, 128, args.timeout)
                judgement = classify(result.pop("content"), expected)
                rows.append({"id": case_id, "category": category, "repeat": rep,
                             "graded": True, **judgement, **result})
                print(f"{args.mode} {rep}/{args.repeats} {case_id}: "
                      f"{'OK' if judgement['correct'] else judgement['format'] + '/FAIL'}",
                      file=sys.stderr)
            for speed_id, limit, prompt in SPEED_CASES:
                result = request(client, args.model, prompt, limit, args.timeout)
                result.pop("content")
                rows.append({"id": speed_id, "category": "speed", "repeat": rep,
                             "graded": False, **result})
                print(f"{args.mode} {rep}/{args.repeats} {speed_id}: "
                      f"{result['generation_tps']} tok/s, "
                      f"{result['completion_tokens']} tokens", file=sys.stderr)
    # Validate the selected process a second time before any report is published.
    legacy.verify_runtime(args.mode, args.model, args.url, args.output)
    report = {
        "schema": 2, "suite": SUITE, "suite_sha256": SUITE_HASH,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode, "model": args.model, "repeats": args.repeats,
        "verified_process_mode": True, "results": rows, "summary": summarize(rows),
        "limitations": [
            "Exact-answer code review is not program generation or execution testing.",
            "Long coding output is ungraded; correctness requires separate human or sandbox review.",
            "No generated code, prompts or full responses are saved.",
            "Only server-provided predicted_ms and completion_tokens estimate generation throughput.",
            "Process arguments checked before/after, not continuously during the run.",
            "Hardware heat, concurrent jobs and truncated outputs affect timings.",
        ],
    }
    write_exclusive(args.output, report)
    return report


def indexed(report):
    repeats = report["repeats"]
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Invalid repetition count")
    expected = {(rep, item[0]) for rep in range(1, repeats + 1)
                for item in CASES + SPEED_CASES}
    rows = report["results"]
    keys = [(row["repeat"], row["id"]) for row in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("Missing, duplicate or unexpected A/B tasks")
    return dict(zip(keys, rows))


def compare(off, on):
    for report, mode in ((off, "off"), (on, "on")):
        if (report.get("schema") != 2 or report.get("suite") != SUITE
                or report.get("suite_sha256") != SUITE_HASH
                or report.get("mode") != mode or report.get("verified_process_mode") is not True):
            raise ValueError("Wrong suite/schema/hash/mode or unverified runtime")
    if off["model"] != on["model"] or off["repeats"] != on["repeats"]:
        raise ValueError("A/B runs must use the same model and repeats")
    left, right = indexed(off), indexed(on)
    before, after = summarize(list(left.values())), summarize(list(right.values()))
    strict_regressions = []
    content_regressions = []
    for (rep, case_id), a in left.items():
        b = right[rep, case_id]
        if not a["graded"]:
            continue
        if a["correct"] and not b["correct"]:
            strict_regressions.append({"repeat": rep, "id": case_id})
        if a["content_correct"] and not b["content_correct"]:
            content_regressions.append({"repeat": rep, "id": case_id})
    # Paired, comparable-length speed samples only. Divergent token lengths do
    # not create misleading wins. This does not infer draft acceptance rates.
    profiles = {}
    usable_gains = []
    for speed_id, _limit, _prompt in SPEED_CASES:
        gains = []
        skipped = 0
        for rep in range(1, off["repeats"] + 1):
            a, b = left[rep, speed_id], right[rep, speed_id]
            ta, tb = a.get("completion_tokens"), b.get("completion_tokens")
            sa, sb = positive_number(a.get("generation_tps")), positive_number(b.get("generation_tps"))
            if (not sa or not sb or type(ta) is not int or type(tb) is not int
                    or min(ta, tb) < 128 or abs(ta - tb) / max(ta, tb) > 0.15):
                skipped += 1
                continue
            gains.append((sb / sa - 1) * 100)
        gain = median(gains) if gains else None
        profiles[speed_id] = {"paired_samples": len(gains),
                              "skipped_noncomparable": skipped,
                              "median_gain_pct": gain}
        if gain is not None:
            usable_gains.append(gain)
    overall_speed_gain = median(usable_gains)
    candidate = (not strict_regressions and not content_regressions
                 and after["quality"]["correct"] >= before["quality"]["correct"]
                 and after["quality"]["content_correct"] >= before["quality"]["content_correct"]
                 and len(usable_gains) >= 2
                 and overall_speed_gain is not None and overall_speed_gain >= 10)
    return {
        "schema": 2, "suite": SUITE, "model": off["model"], "repeats": off["repeats"],
        "off": before, "on": after,
        "quality_delta_correct": after["quality"]["correct"] - before["quality"]["correct"],
        "content_delta_correct": after["quality"]["content_correct"] - before["quality"]["content_correct"],
        "cases_regressed": sorted(strict_regressions, key=lambda r: (r["repeat"], r["id"])),
        "content_regressed": sorted(content_regressions, key=lambda r: (r["repeat"], r["id"])),
        "speed_profiles": profiles, "speed_gain_pct": overall_speed_gain,
        "recommendation": ("candidate_for_broader_review" if candidate
                           else "inconclusive_or_regression"),
        "interpretation": "Candidate only; never automatic model/config/quality approval.",
    }


def diagnose(args):
    if not 5 <= args.timeout <= 900:
        raise ValueError("Invalid timeout")
    # The local stdout is explicitly requested and is not saved by this tool.
    legacy.verify_runtime(args.mode, args.model, args.url, Path("/tmp/nobby-dflash-v2-diagnostic-never-written.json"))
    failures = {"reason-profit", "py-slice", "js-loop", "js-var"}
    with httpx.Client(base_url=ORIGIN, trust_env=False) as client:
        for case_id, _, question, expected in legacy.CASES:
            if case_id not in failures:
                continue
            result = request(client, args.model, question + FORMAT, 128, args.timeout)
            raw = result.pop("content")
            judgement = classify(raw, expected)
            print(json.dumps({
                "id": case_id, "expected": expected, "model_response": raw,
                "judgement": judgement, "finish_reason": result["finish_reason"],
            }, ensure_ascii=False))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "run":
            result = run(args)["summary"]
        elif args.action == "compare":
            result = compare(json.loads(args.off.read_text(encoding="utf-8")),
                             json.loads(args.on.read_text(encoding="utf-8")))
        else:
            return diagnose(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, RuntimeError, KeyError, OSError, httpx.HTTPError) as e:
        print(f"DFlash benchmark v2 failed (runtime unchanged): {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
