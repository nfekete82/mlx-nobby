#!/usr/bin/env python3
"""Local, read-only extraction benchmark. All test chat inputs are synthetic.

No DB writes, no original chat reads, no network except 127.0.0.1.
When comparing, each model is called SEQUENTIALLY to limit memory contention.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Make direct execution (`python scripts/benchmark-memory-model-local.py`) work.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import semantic_personal_memory as smart

CASES = (
    ("partner_name", "Meine Freundin heißt Mira.", ("Mira",), False),
    ("daughter", "Meine Tochter heißt Lina.", ("Lina",), False),
    ("technical_tools", "Ich entwickle beruflich mit PHP und JavaScript.", ("PHP", "JavaScript"), False),
    ("profession", "Ich arbeite als Fachinformatiker.", ("Fachinformatiker",), False),
    ("education", "Ich habe eine Ausbildung zum Elektroniker abgeschlossen.", ("Elektroniker",), False),
    ("birthplace", "Ich bin in Wien geboren.", ("Wien",), False),
    ("current_home", "Ich wohne jetzt in Köln.", ("Köln",), False),
    ("project", "Mein Projekt NebulaBoard verwendet PostgreSQL.", ("NebulaBoard", "PostgreSQL"), False),
    ("hobby", "Ich trainiere dreimal pro Woche mit Kettlebells.", ("Kettlebells",), False),
    ("answer_style", "Ich bevorzuge kurze und sachliche Antworten.", ("kurze", "sachliche"), False),
    ("adult_preference", "Ich mag beim Sex leidenschaftliche Küsse.", ("Küsse",), False),
    ("adult_boundary", "Meine sexuelle Vorliebe ist offene Kommunikation über Wünsche.", ("offene Kommunikation",), False),
    ("adult_relationship", "In meiner Partnerschaft wünsche ich mir mehr körperliche Nähe.", ("körperliche Nähe",), False),
    ("life_event", "2018 habe ich für sechs Monate in Berlin gearbeitet.", ("Berlin",), False),
    ("hypothetical", "Wenn ich in Hamburg wohnen würde, wäre der Arbeitsweg kürzer.", (), True),
    ("quoted_claim", 'Meine Kollegin sagte: "Ich wohne in Prag."', (), True),
    ("question", "Wie heißt eigentlich meine Freundin?", (), True),
    ("task_not_fact", "Erstelle ein Bild von einer Frau mit roten Haaren.", (), True),
)

class BlockRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        return None

OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), BlockRedirects()
)


def inference(port: int, model: str, message: str, timeout: int) -> tuple[str, float, str]:
    messages = smart.extraction_messages(json.dumps({"message": message, "context": ""}, ensure_ascii=False))
    body = json.dumps({
        "model": model, "messages": messages, "temperature": 0,
        "max_tokens": 3000, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.monotonic()
    try:
        with OPENER.open(request, timeout=timeout) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Response too large")
        answer = json.loads(data)
        choice = answer["choices"][0]
        output = choice["message"].get("content") or choice["message"].get("reasoning") or ""
        reason = choice.get("finish_reason") or ""
        if not isinstance(output, str):
            raise ValueError("Output is not text")
        return output, time.monotonic() - started, reason
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, IndexError) as exc:
        # Do not print upstream exception bodies that could contain private prompts.
        return "", time.monotonic() - started, "transport_or_schema_error"


def run(port, model, timeout):
    results = []
    print(f"\n=== MODELL-TEST — Port {port} ===", flush=True)
    for name, prompt, expected, negative in CASES:
        output, elapsed, reason = inference(port, model, prompt, timeout)
        try:
            structure = smart.decode_output(output)
            schema_ok = True
        except (ValueError, TypeError):
            structure, schema_ok = {}, False
        facts = smart.parse_facts(output, prompt) if schema_ok else []
        episodes = structure.get("episodes", [])
        if not isinstance(episodes, list):
            episodes = []
        # The persisted facts must pass the same literal evidence validator
        # used by real history processing. Episode scoring is advisory only.
        values = " ".join(str(f["value"]) for f in facts).casefold()
        required = [token for token in expected if token.casefold() not in values]
        nonempty = bool(facts or episodes)
        passed = schema_ok and reason != "length" and (
            not nonempty if negative else not required
        )
        refusal = not schema_ok and any(word in output.casefold() for word in (
            "cannot", "can't", "sorry", "refuse", "entschuldigung", "kann nicht",
        ))
        results.append({
            "case": name, "ok": passed, "schema_ok": schema_ok,
            "valid_facts": len(facts), "episodes": len(episodes),
            "missing": required, "seconds": round(elapsed, 2),
            "refusal": refusal, "finish": reason,
        })
        print(
            f"{name:22s} {'OK' if passed else 'MISS':4s} "
            f"facts={len(facts):2d} episodes={len(episodes):2d} "
            f"{elapsed:5.1f}s" +
            (f" missing={','.join(required)}" if required else "") +
            (f" finish={reason}" if reason not in ("stop", "") else ""),
            flush=True,
        )
    passed = sum(item["ok"] for item in results)
    valid_schema = sum(item["schema_ok"] for item in results)
    times = [item["seconds"] for item in results]
    summary = {
        "cases": len(results), "passed": passed,
        "valid_schema": valid_schema, "refusals": sum(i["refusal"] for i in results),
        "median_seconds": round(statistics.median(times), 2),
        "total_seconds": round(sum(times), 2),
        "cases_failed": [i["case"] for i in results if not i["ok"]],
    }
    print("\nERGEBNIS:", json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--model", required=True, help="Exact ID from server /v1/models")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--compare-port", type=int)
    parser.add_argument("--compare-model")
    args = parser.parse_args()
    ports = [args.port] + ([args.compare_port] if args.compare_port else [])
    if not all(1024 <= p <= 65535 for p in ports):
        parser.error("Ports must be valid local high ports")
    if not (10 <= args.timeout <= 900):
        parser.error("timeout must be between 10 and 900 seconds")
    if bool(args.compare_port) != bool(args.compare_model):
        parser.error("--compare-port and --compare-model must be provided together")
    run(args.port, args.model, args.timeout)
    if args.compare_port:
        run(args.compare_port, args.compare_model, args.timeout)
    print("\nHinweis: Falsche Ablehnungen oder False Positives brauchen zusätzlich eine"
          " manuelle Qualitätsprüfung. Dieser Test schreibt keine Chats oder Fakten.")


if __name__ == "__main__":
    main()
