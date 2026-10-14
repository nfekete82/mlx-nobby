#!/usr/bin/env python3
"""Opt-in DFlash2 code-generation A/B; generated code runs ONLY in Docker."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

import httpx

V2_PATH = Path(__file__).with_name("benchmark-dflash-extended.py")
spec = importlib.util.spec_from_file_location("dflash_ab_v2", V2_PATH)
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)
SUITE = "mlx-nobby-dflash-code-exec-ab-v3"
SENTINEL = "__NOBBY_DFLASH_PASS_8A7C__"
FENCE = chr(96) * 3
IMAGES = {
    "python": ("python:3.12-alpine", ("python", "-I", "-B", "-")),
    "javascript": ("node:22-alpine", ("node", "-")),
    "php": ("php:8.3-cli-alpine", ("php",)),
}
TASKS = (
    {
        "id": "py-stock", "language": "python",
        "prompt": (
            "Schreibe Python 3.12: def allocate_stock(orders, available): "
            "orders ist eine Liste nichtnegativer Ganzzahlen. Verteilt available "
            "Einheiten der Reihe nach (FIFO), jede Bestellung bekommt maximal "
            "ihre geforderte Menge. Gib eine gleich lange Liste zugeteilter "
            "Ganzzahlen zurueck. Veraendere die Eingaben nicht. "
            "Nur ausfuehrbarer Python-Code, kein Markdown."
        ),
        "tests": """
assert allocate_stock([4, 3, 7], 10) == [4, 3, 3]
assert allocate_stock([], 10) == []
assert allocate_stock([0, 5, 0], 3) == [0, 3, 0]
assert allocate_stock([1, 2, 3], 4) == [1, 2, 1]
assert allocate_stock([3, 3], 0) == [0, 0]
assert allocate_stock([2, 4], 20) == [2, 4]
assert allocate_stock([9], 2) == [2]
print("__NOBBY_DFLASH_PASS_8A7C__")
""",
    },
    {
        "id": "py-money", "language": "python",
        "prompt": (
            "Schreibe Python 3.12: def total_cents(lines): "
            "lines ist eine Liste von 2-Tupeln (unit_price_cents, quantity), "
            "beide nichtnegative ganze Zahlen. Liefere die Summe aller "
            "Einzelpreise mal Anzahl als Integer in Cent. Keine Float-Rechnung "
            "und keine Aenderung der Eingaben. Nur Python-Code, kein Markdown."
        ),
        "tests": """
assert total_cents([]) == 0
assert total_cents([(199, 3), (50, 2)]) == 697
assert total_cents([(0, 8), (42, 0)]) == 0
assert total_cents([(1, 100000), (300, 2)]) == 100600
assert total_cents([(999, 1)]) == 999
assert type(total_cents([(1, 2)])) is int
print("__NOBBY_DFLASH_PASS_8A7C__")
""",
    },
    {
        "id": "js-even-loop", "language": "javascript",
        "prompt": (
            "Schreibe Node-22-JavaScript: function sumEvenIndices(n) "
            "summiert alle geraden ganzen Zahlen i mit 0 <= i < n und gibt "
            "die Summe zurueck. n ist eine nichtnegative ganze Zahl. "
            "Nutze eine Schleife. Nur JavaScript-Code, kein Markdown."
        ),
        "tests": """
const __nobbyAssert = require("node:assert/strict");
for (const [n, expected] of [
  [0, 0], [1, 0], [2, 0], [3, 2],
  [5, 6], [10, 20], [11, 30], [101, 2550]
]) __nobbyAssert.equal(sumEvenIndices(n), expected);
console.log("__NOBBY_DFLASH_PASS_8A7C__");
""",
    },
    {
        "id": "js-var-closure", "language": "javascript",
        "prompt": (
            "Schreibe Node-22-JavaScript: function makeVarClosures(n) "
            "gibt ein Array von n Funktionen zurueck. Jede dieser Funktionen "
            "muss bei spaeterem Aufruf den ENDWERT eines gemeinsam genutzten "
            "var-Schleifenzaehlers liefern, also n (nicht ihren Index). "
            "n ist eine nichtnegative ganze Zahl. Nur JavaScript-Code, kein Markdown."
        ),
        "tests": """
const __nobbyAssert = require("node:assert/strict");
for (const n of [0, 1, 3, 5]) {
  const fns = makeVarClosures(n);
  __nobbyAssert.equal(fns.length, n);
  __nobbyAssert.deepEqual(fns.map(f => f()), Array(n).fill(n));
  __nobbyAssert.ok(fns.every(f => typeof f === "function"));
}
console.log("__NOBBY_DFLASH_PASS_8A7C__");
""",
    },
    {
        "id": "js-cart", "language": "javascript",
        "prompt": (
            "Schreibe Node-22-JavaScript: function cartTotalCents(lines) "
            "nimmt ein Array mit Objekten {unitCents: Integer, quantity: Integer} "
            "(beide nichtnegativ) und liefert die Summe aus Preis mal Anzahl "
            "als Integer. Veraendere die Eingabe nicht. "
            "Nur JavaScript-Code, kein Markdown."
        ),
        "tests": """
const __nobbyAssert = require("node:assert/strict");
const lines = [{unitCents: 199, quantity: 2}, {unitCents: 50, quantity: 3}];
__nobbyAssert.equal(cartTotalCents(lines), 548);
__nobbyAssert.equal(cartTotalCents([]), 0);
__nobbyAssert.equal(cartTotalCents([{unitCents: 0, quantity: 8}]), 0);
__nobbyAssert.equal(cartTotalCents([{unitCents: 100, quantity: 0}]), 0);
__nobbyAssert.equal(cartTotalCents([{unitCents: 3, quantity: 10000}]), 30000);
__nobbyAssert.deepEqual(lines, [{unitCents: 199, quantity: 2}, {unitCents: 50, quantity: 3}]);
console.log("__NOBBY_DFLASH_PASS_8A7C__");
""",
    },
    {
        "id": "php-discount", "language": "php",
        "prompt": (
            "Schreibe PHP 8.3: function discountTotalCents(array $items, int $discountBps): int. "
            "$items ist eine Liste von Arrays mit keys 'unitCents' und 'quantity', "
            "jeweils nichtnegative Integer. Berechne subtotal in Cent; "
            "$discountBps liegt zwischen 0 und 10000. Rabattiere die GESAMTSUMME "
            "und runde einmal ab: intdiv(subtotal * (10000 - discountBps), 10000). "
            "Keine Float-Rechnung. NUR PHP-Funktionscode, "
            "OHNE PHP-Tags und ohne Markdown."
        ),
        "tests": """
function __nobbyCheck($actual, $expected): void {
    if ($actual !== $expected) { throw new RuntimeException('test failed'); }
}
__nobbyCheck(discountTotalCents([], 1000), 0);
__nobbyCheck(discountTotalCents([['unitCents' => 999, 'quantity' => 3]], 1000), 2697);
__nobbyCheck(discountTotalCents([['unitCents' => 101, 'quantity' => 1]], 3333), 67);
__nobbyCheck(discountTotalCents([['unitCents' => 50, 'quantity' => 2]], 0), 100);
__nobbyCheck(discountTotalCents([['unitCents' => 99, 'quantity' => 3]], 10000), 0);
__nobbyCheck(discountTotalCents([['unitCents' => 1, 'quantity' => 10]], 5000), 5);
echo "__NOBBY_DFLASH_PASS_8A7C__\n";
""",
    },
    {
        "id": "php-sku", "language": "php",
        "prompt": (
            "Schreibe PHP 8.3: function canonicalSku(string $value): string. "
            "ASCII-Eingaben. Ersetze jede zusammenhaengende Folge von Zeichen, "
            "die NICHT ASCII-Buchstabe A-Z/a-z oder Ziffer 0-9 sind, durch "
            "einen Bindestrich. Entferne fuehrende/nachfolgende Bindestriche "
            "und wandle ASCII-Buchstaben in Grossbuchstaben um. "
            "Nur PHP-Funktionscode, OHNE PHP-Tags und ohne Markdown."
        ),
        "tests": """
function __nobbyCheck($actual, $expected): void {
    if ($actual !== $expected) { throw new RuntimeException('test failed'); }
}
__nobbyCheck(canonicalSku('  ab-- 12  '), 'AB-12');
__nobbyCheck(canonicalSku('SKU_007'), 'SKU-007');
__nobbyCheck(canonicalSku(''), '');
__nobbyCheck(canonicalSku('@#'), '');
__nobbyCheck(canonicalSku('a b_c.d'), 'A-B-C-D');
__nobbyCheck(canonicalSku('--x--Y--'), 'X-Y');
echo "__NOBBY_DFLASH_PASS_8A7C__\n";
""",
    },
)
SUITE_HASH = hashlib.sha256(json.dumps(
    (TASKS, IMAGES), ensure_ascii=False, separators=(",", ":")
).encode("utf-8")).hexdigest()
ID_MAP = {case["id"]: case for case in TASKS}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="Generate and test code on verified ON/OFF runtime")
    run.add_argument("--mode", choices=("off", "on"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--url", default=v2.ORIGIN)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--timeout", type=int, default=240)
    run.add_argument("--docker-timeout", type=int, default=15)
    run.add_argument("--output", type=Path, required=True)
    comp = sub.add_parser("compare", help="Compare two v3 reports offline")
    comp.add_argument("--off", type=Path, required=True)
    comp.add_argument("--on", type=Path, required=True)
    return p


def normalize_code(raw, language):
    """Accept only plain code or a single complete fenced code block."""
    if not isinstance(raw, str) or not 1 <= len(raw) <= 24000:
        return None, "invalid"
    raw = raw.strip()
    label = "plain"
    if raw.startswith(FENCE):
        pattern = re.escape(FENCE) + r"(?:python|py|javascript|js|php)?[ \t]*\n(.*?)\n" + re.escape(FENCE)
        match = re.fullmatch(pattern, raw, re.DOTALL | re.IGNORECASE)
        if not match:
            return None, "invalid"
        raw = match.group(1).strip()
        label = "fenced"
    if not raw or len(raw) > 24000:
        return None, "invalid"
    if language == "php" and ("<?php" in raw.lower() or "?>" in raw):
        return None, "invalid"
    return raw, label


def docker_preflight():
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI missing; no host execution fallback")
    try:
        p = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Docker daemon unavailable") from exc
    if p.returncode != 0:
        raise RuntimeError("Docker daemon unavailable")
    for image, _args in IMAGES.values():
        try:
            p = subprocess.run(["docker", "image", "inspect", image],
                               capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Docker image inspection failed") from exc
        if p.returncode != 0:
            raise RuntimeError(f"Missing cached image {image}; no automatic pull")


def sandbox_command(task, name):
    image, command = IMAGES[task["language"]]
    return ["docker", "run", "--rm", "--name", name, "--pull=never",
            "--network=none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=64", "--memory=256m", "--memory-swap=256m",
            "--cpus=1", "--user=65534:65534",
            "--ulimit", "nofile=128:128", "-i", image, *command]


def sandbox_run(task, code, timeout):
    """No host code execution; code and assertions pass by stdin only."""
    if not 4 <= timeout <= 60:
        raise ValueError("Docker timeout must be 4..60 seconds")
    prefix = "<?php\n" if task["language"] == "php" else ""
    program = prefix + code + "\n\n" + task["tests"]
    name = "nobby-dflash-sandbox-" + uuid.uuid4().hex[:16]
    start = time.perf_counter()
    try:
        p = subprocess.run(sandbox_command(task, name), input=program,
                           text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        cleanup = subprocess.run(["docker", "rm", "-f", name],
                                 capture_output=True, timeout=10, check=False)
        if cleanup.returncode != 0 and b"No such container" not in (
            cleanup.stderr if isinstance(cleanup.stderr, bytes)
            else str(cleanup.stderr).encode("utf-8")
        ):
            raise RuntimeError("Timed-out sandbox could not be cleaned up")
        return {"passed": False, "reason": "timeout",
                "sandbox_ms": round((time.perf_counter() - start) * 1000, 3)}
    except OSError as exc:
        raise RuntimeError("Docker invocation failed") from exc
    elapsed = round((time.perf_counter() - start) * 1000, 3)
    passed = p.returncode == 0 and p.stdout.strip().endswith(SENTINEL)
    return {"passed": passed, "reason": "pass" if passed else "tests_or_compile_failed",
            "sandbox_ms": elapsed}


def summary(records):
    out = {"correct": sum(r["passed"] for r in records), "total": len(records),
           "hit_token_cap": sum(r["finish_reason"] == "length" for r in records),
           "by_language": {}, "by_task": {}}
    for language in IMAGES:
        chosen = [r for r in records if r["language"] == language]
        out["by_language"][language] = {
            "correct": sum(r["passed"] for r in chosen), "total": len(chosen)}
    for task in TASKS:
        chosen = [r for r in records if r["id"] == task["id"]]
        out["by_task"][task["id"]] = {
            "correct": sum(r["passed"] for r in chosen), "total": len(chosen),
            "median_generation_tps": v2.median([r["generation_tps"] for r in chosen])}
    return out


def run(args):
    if (type(args.repeats) is not int or not 1 <= args.repeats <= 5
            or not 5 <= args.timeout <= 900 or not 4 <= args.docker_timeout <= 60):
        raise ValueError("Invalid repeats (1..5) or timeout settings")
    v2.legacy.verify_runtime(args.mode, args.model, args.url, args.output)
    docker_preflight()
    records = []
    with httpx.Client(base_url=v2.ORIGIN, trust_env=False) as client:
        for rep in range(1, args.repeats + 1):
            for task in TASKS:
                response = v2.request(client, args.model, task["prompt"], 1400, args.timeout)
                code, fmt = normalize_code(response.pop("content"), task["language"])
                result = (sandbox_run(task, code, args.docker_timeout) if code is not None
                          else {"passed": False, "reason": "non_code_response",
                                "sandbox_ms": None})
                records.append({
                    "id": task["id"], "language": task["language"],
                    "repeat": rep, "passed": result["passed"],
                    "failure_kind": result["reason"], "code_format": fmt,
                    "sandbox_ms": result["sandbox_ms"], **response})
                print(f"{args.mode} {rep}/{args.repeats} {task['id']}: "
                      f"{'PASS' if result['passed'] else 'FAIL'} ({result['reason']})",
                      file=sys.stderr)
    v2.legacy.verify_runtime(args.mode, args.model, args.url, args.output)
    report = {
        "schema": 3, "suite": SUITE, "suite_sha256": SUITE_HASH,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode, "model": args.model, "repeats": args.repeats,
        "docker_timeout": args.docker_timeout,
        "verified_process_mode": True, "results": records,
        "summary": summary(records),
        "limitations": [
            "Generated code only executes in locked-down Docker, never on the Mac host.",
            "Docker isolation reduces risk but cannot guarantee absolute containment.",
            "Only pass/fail and timing metrics persisted; generated source never stored.",
            "Limited hidden unit tests are not full production code verification.",
            "Model response may truncate at 1400 completion tokens.",
            "Sequential ON/OFF order may be thermally biased.",
            "No runtime changes or automatic quality approval.",
        ],
    }
    v2.write_exclusive(args.output, report)
    return report


def keyed(report):
    repeats = report["repeats"]
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("Invalid repeats")
    rows = report["results"]
    keys = [(row["repeat"], row["id"]) for row in rows]
    expected = {(rep, task["id"]) for rep in range(1, repeats + 1) for task in TASKS}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("Missing, duplicate or unexpected code tasks")
    for row in rows:
        if row.get("language") != ID_MAP[row["id"]]["language"] or type(row.get("passed")) is not bool:
            raise ValueError("Invalid task language or outcome")
    return dict(zip(keys, rows))


def compare(off, on):
    for report, mode in ((off, "off"), (on, "on")):
        if (report.get("schema") != 3 or report.get("suite") != SUITE
                or report.get("suite_sha256") != SUITE_HASH
                or report.get("mode") != mode or report.get("verified_process_mode") is not True):
            raise ValueError("Wrong schema, suite, hash, mode or unverified runtime")
    if (off["model"] != on["model"] or off["repeats"] != on["repeats"]
            or off["docker_timeout"] != on["docker_timeout"]):
        raise ValueError("A/B model, repeats and sandbox timeout must match")
    a, b = keyed(off), keyed(on)
    off_summary, on_summary = summary(list(a.values())), summary(list(b.values()))
    regressions = sorted(
        ({"repeat": rep, "id": case_id}
         for (rep, case_id), before in a.items()
         if before["passed"] and not b[rep, case_id]["passed"]),
        key=lambda x: (x["repeat"], x["id"]))
    new_passes = sorted(
        ({"repeat": rep, "id": case_id}
         for (rep, case_id), before in a.items()
         if not before["passed"] and b[rep, case_id]["passed"]),
        key=lambda x: (x["repeat"], x["id"]))
    return {
        "schema": 3, "suite": SUITE, "model": off["model"], "repeats": off["repeats"],
        "off": off_summary, "on": on_summary,
        "quality_delta_correct": on_summary["correct"] - off_summary["correct"],
        "regressed": regressions, "new_passes": new_passes,
        "recommendation": (
            "candidate_for_manual_code_review"
            if not regressions and on_summary["correct"] >= off_summary["correct"]
            else "inconclusive_or_regression"),
        "interpretation": "Narrow executable-code smoke tests; no automatic approval.",
    }


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = (run(args)["summary"] if args.action == "run"
                  else compare(json.loads(args.off.read_text(encoding="utf-8")),
                               json.loads(args.on.read_text(encoding="utf-8"))))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, httpx.HTTPError) as exc:
        print(f"DFlash code A/B failed (runtime unchanged): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
