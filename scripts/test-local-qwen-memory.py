#!/usr/bin/env python3
"""Read-only acceptance of the active local Qwen personal-memory extractor.

No chat files, memory databases, or settings are created or modified.
Only fictional test strings go to the local MLX endpoint (127.0.0.1).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Direct execution (python3 scripts/test-local-qwen-memory.py) sets sys.path[0]
# to scripts/, not the repository root. Resolve only this checkout locally.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import semantic_personal_memory as smart


CASES = [
    {
        "name": "single factual statement",
        "text": "Meine Partnerin ist Architektin.",
        "expected": [("partner", "beruf", "Architektin")],
    },
    {
        "name": "two different personal facts",
        "text": "Ich bin Informatiker und wohne in Musterstadt.",
        "expected": [("ich", "beruf", "Informatiker"), ("ich", "wohnort", "Musterstadt")],
    },
    {
        "name": "two family members",
        "text": "Meine Tochter heißt Leni und mein Sohn heißt Emil.",
        "expected": [("familie.tochter", "name", "Leni"),
                     ("familie.sohn", "name", "Emil")],
    },
    {
        "name": "explicit negation",
        "text": "Ich bin kein Lehrer.",
        "expected": [],
    },
    {
        "name": "hypothetical statement",
        "text": "Wenn ich Architekt wäre, würde ich Häuser bauen.",
        "expected": [],
    },
    {
        "name": "uncertain future",
        "text": "Vielleicht wohne ich nächstes Jahr in Bremen.",
        "expected": [],
    },
    {
        "name": "explicit correction",
        "text": "Ich habe mich vertan: Meine Partnerin ist jetzt Lehrerin.",
        "expected": [("partner", "beruf", "Lehrerin")],
        "correction": True,
    },
    {
        "name": "correction with rejected former value",
        "text": "Ich habe mich vertan: Meine Partnerin ist nicht Architektin, sondern Lehrerin.",
        "expected": [("partner", "beruf", "Lehrerin")],
        "forbidden": ["Architektin"],
        "correction": True,
    },
]


def config_values() -> dict[str, str]:
    path = Path.home() / ".config/mlx-server/config"
    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"')
    return config


def infer(model: str, port: int, text: str, timeout: int) -> str:
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": smart._SYSTEM},
            {"role": "user", "content": json.dumps({"message": text}, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 460,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    return (result["choices"][0]["message"].get("content") or "").strip()


def check(case: dict, facts: list[dict]) -> list[str]:
    observed = {
        (item["subject"], item["field"].split(".", 1)[0], item["value"])
        for item in facts
    }
    expected = set(case["expected"])
    issues = []
    if not expected and facts:
        issues.append("Expected no facts but model/verifier accepted one")
    for item in sorted(expected - observed):
        issues.append(f"Missing grounded fact: {item}")
    for forbidden in case.get("forbidden", []):
        if any(item["value"].casefold() == forbidden.casefold() for item in facts):
            issues.append(f"Forbidden negated fact persisted: {forbidden}")
    if case.get("correction") and any(
        item["subject"] == "partner" and item["field"] == "beruf"
        and item["value"] == "Lehrerin" and item["correction"] is not True
        for item in facts
    ):
        issues.append("Explicit correction lacks correction marker")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="run first 4 cases")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    config = config_values()
    model = config.get("MODEL")
    if not model:
        print("No model selected in ~/.config/mlx-server/config", file=sys.stderr)
        return 2
    port = int(config.get("PORT", "8000"))
    cases = CASES[:4] if args.quick else CASES
    errors = 0
    print(f"Local Qwen acceptance: {len(cases)} fictional cases, model={model}")
    print("Mode: READ-ONLY. No memory/database writes.\n")
    for case in cases:
        try:
            raw = infer(model, port, case["text"], args.timeout)
            facts = smart.parse_facts(raw, case["text"])
            problems = check(case, facts)
        except Exception as exc:
            facts, raw = [], ""
            problems = [f"{type(exc).__name__}: {exc}"]
        print(f"{'FAIL' if problems else 'PASS'} | {case['name']}")
        print("  Verified:", json.dumps(facts, ensure_ascii=False))
        if problems:
            errors += 1
            for problem in problems:
                print("  Issue:", problem)
            print("  Raw local model output:", raw[:2000])
        print()
    print(f"RESULT: {len(cases) - errors}/{len(cases)} passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
