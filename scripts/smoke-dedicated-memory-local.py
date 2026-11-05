#!/usr/bin/env python3
"""Smoke-test the real dedicated 4B Agent extraction backend on fictional data.

This runs in the CALLING Python process with a NEW temporary SQLite database.
It never reads/writes production memory, never starts a model, and never
reprocesses the user's chat archive. Requires an already running local model
service at 127.0.0.1:8011 and only speaks loopback.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import dedicated_memory_model as mm
from agent import personal_memory as pm
from agent import semantic_personal_memory as smart

FIXTURES = (
    ("technologies", "Ich entwickle mit PHP und JavaScript.", ("PHP", "JavaScript"), False),
    ("profession", "Ich arbeite als Fachinformatiker.", ("Fachinformatiker",), False),
    ("relationship", "In meiner Partnerschaft wünsche ich mir mehr körperliche Nähe.", ("körperliche Nähe",), False),
    ("adult", "Ich mag beim Sex leidenschaftliche Küsse.", ("leidenschaftliche Küsse",), False),
    ("preferences", "Ich bevorzuge kurze und sachliche Antworten.", ("kurze", "sachliche"), False),
    ("not_mine", 'Meine Kollegin sagt: "Ich wohne in Wien."', (), True),
    ("hypothetical", "Wenn ich in Hamburg wohnen würde, hätte ich kürzere Wege.", (), True),
)


def run(port: int, model: str) -> bool:
    timings = []
    passed = 0
    with tempfile.TemporaryDirectory(prefix="mlx-nobby-memory-smoke-") as tmp:
        original = pm.DB_PATH
        scratch_db = Path(tmp) / "isolated-memory.sqlite3"
        pm.DB_PATH = scratch_db
        try:
            if mm.settings()["mode"] != "chat" or scratch_db.exists():
                raise RuntimeError("Test isolation failed before startup")
            cfg = mm.configure({"mode": "dedicated", "model": model, "port": port})
            if cfg["mode"] != "dedicated" or not scratch_db.exists():
                raise RuntimeError("Test config was not stored in private scratch database")
            for case_name, message, expected, negative in FIXTURES:
                messages = smart.extraction_messages(
                    json.dumps({"message": message, "context": ""}, ensure_ascii=False),
                    profile="compact",
                )

                def no_foreground_fallback(_messages):
                    raise AssertionError("Dedicated mode unexpectedly called chat model")

                start = time.monotonic()
                output = mm.extract(messages, no_foreground_fallback)
                duration = time.monotonic() - start
                timings.append(duration)
                structure = smart.decode_output(output)
                facts = smart.parse_facts(output, message)
                if not isinstance(structure.get("episodes"), list):
                    raise ValueError("Invalid episode response")

                values = " ".join(str(item.get("value", "")) for item in facts).casefold()
                if negative:
                    ok = not facts and not structure["episodes"]
                else:
                    ok = all(token.casefold() in values for token in expected)
                passed += int(ok)
                print(f"{case_name:15s} {'OK' if ok else 'MISS':4s} "
                      f"{duration:5.2f}s facts={len(facts)} episodes={len(structure['episodes'])}",
                      flush=True)
            if mm.settings()["mode"] != "dedicated":
                raise RuntimeError("Dedicated configuration was not retained")
            mm.configure({"mode": "chat"})
            if mm.settings()["mode"] != "chat":
                raise RuntimeError("Cannot revert isolated model setting")
        finally:
            pm.DB_PATH = original

    print("SMOKE RESULT:", f"{passed}/{len(FIXTURES)}",
          "median_seconds:", round(statistics.median(timings), 2),
          "isolated_db_deleted:", not scratch_db.exists(), flush=True)
    return passed == len(FIXTURES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--model", type=str, required=True,
                        help="Exact ID of local 4B model on port 8011")
    args = parser.parse_args()
    if args.port != 8011:
        parser.error("Safety: this acceptance script only uses port 8011")
    if not Path(args.model).is_absolute() or not Path(args.model, "config.json").is_file():
        parser.error("Specify an existing absolute local model directory with config.json")
    if not run(args.port, args.model):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
