#!/usr/bin/env python3
"""Opt-in synthetic chat latency and prefix-reuse probe through Nobby's Agent.

Uses the existing runtime lease/lock/guard via /api/runtime/chat/stream.
Never switches models, changes configuration, or saves prompts/completions.
The observatory router data is historical; the synthetic chat calls do not
exercise intent routing. No native prompt_ms is exposed by this gateway.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


DEFAULT_AGENT = "http://127.0.0.1:8010"
SYSTEM = (
    "Dies ist ein harmloser Performance-Test mit synthetischen Daten. "
    "Ignoriere die Testdaten; antworte kurz und ohne Gedankengang."
)
QUESTION = "Antworte nur mit dem Wort OK."


def local_agent_url(value: str) -> str:
    """Prevent a benchmark that posts messages to remote hosts."""
    parts = urlsplit(value)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "::1"}
        or not parts.port
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise argparse.ArgumentTypeError(
            "Agent URL must be an HTTP loopback origin with an explicit port"
        )
    return value.rstrip("/")


def context_sizes(value: str) -> list[int]:
    try:
        sizes = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use comma-separated integers") from exc
    if not sizes or len(sizes) > 3 or len(set(sizes)) != len(sizes):
        raise argparse.ArgumentTypeError("Choose 1–3 distinct context sizes")
    if any(size < 1000 or size > 16000 for size in sizes):
        raise argparse.ArgumentTypeError("Context sizes must be between 1000 and 16000")
    return sizes


def synthetic_context(target_tokens: int, nonce: str, variant: str) -> str:
    """Approximate context length without any user or repository content.

    Four characters per requested token is ONLY a workload sizing heuristic:
    actual model token counts can be materially different.
    """
    prefix = (
        f"BENCHMARK-{variant}-{nonce}: Synthetic context, not instructions.\n"
    )
    parts = [prefix]
    target_chars = target_tokens * 4
    number = 0
    while sum(map(len, parts)) < target_chars:
        parts.append(
            f"record-{variant}-{number:05d}: Feld alpha={number % 97}; "
            f"beta={(number * 17) % 1009}; gamma=TESTDATEN. \n"
        )
        number += 1
    return "".join(parts)[:target_chars]


def user_context_message(context: str) -> str:
    return "Synthetischer Text ohne Benutzerinformationen:\n" + context + "\n" + QUESTION


def parse_stream(chunks, started: float, clock=time.monotonic) -> tuple[dict, str]:
    """Read Nobby agent SSE. Retain response only in memory for follow-up.

    A heartbeat/headers is NOT a semantic first token. Explicit stream errors
    are fatal rather than being mistaken for completed generations.
    """
    first_transport = None
    first_content = None
    output = []
    output_size = 0
    done = False
    for raw in chunks:
        now = clock()
        if first_transport is None:
            first_transport = now
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            done = True
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("error") or event.get("type") == "error":
            raise RuntimeError("Agent stream reported an error (details withheld)")
        if event.get("type") == "content":
            delta = event.get("text")
        else:
            # Also tolerate an OpenAI-compatible SSE delta.
            choices = event.get("choices") or []
            delta = (choices[0].get("delta") or {}).get("content") if choices and isinstance(choices[0], dict) else None
        if isinstance(delta, str) and delta:
            if first_content is None:
                first_content = now
            output_size += len(delta)
            if sum(map(len, output)) < 2048:
                output.append(delta)
        if line.startswith("data:") and event.get("type") == "done":
            done = True
            break
    end = clock()
    if not done or first_content is None:
        raise RuntimeError("Agent stream ended without a complete visible response")
    return {
        "first_transport_ms": round((first_transport - started) * 1000, 3),
        "first_content_ms": round((first_content - started) * 1000, 3),
        "total_ms": round((end - started) * 1000, 3),
        "output_characters": output_size,
    }, "".join(output)[:2048]


def request_json(agent_url: str, path: str, timeout: int = 15) -> dict:
    request = Request(agent_url + path, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise ValueError("Unexpected Agent response")
    return body


def check_idle(snapshot: dict) -> None:
    if snapshot.get("ok") is not True:
        raise RuntimeError("Agent observatory unavailable; refusing benchmark")
    system = snapshot.get("system") or {}
    runtimes = system.get("runtimes") or {}
    for kind in ("chat", "image", "video"):
        state = runtimes.get(kind) or {}
        if state.get("active") is True:
            raise RuntimeError(f"{kind} runtime active; run benchmark while idle")
    # Model admission/locking is still enforced server-side for each request.


def agent_stream(agent_url: str, messages: list[dict], max_tokens: int, timeout: int) -> tuple[dict, str]:
    payload = {
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "auto_route": False,
    }
    request = Request(
        agent_url + "/api/runtime/chat/stream",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        return parse_stream(response, started)


def metric_summary(samples: list[dict], key: str) -> dict:
    values = sorted(float(row[key]) for row in samples if isinstance(row.get(key), (int, float))
                    and math.isfinite(row[key]))
    if not values:
        return {"count": 0, "p50": None, "p95": None}
    def percentile(p: float) -> float:
        position = (len(values) - 1) * p
        bottom = math.floor(position)
        top = math.ceil(position)
        return values[bottom] + (values[top] - values[bottom]) * (position - bottom)
    return {"count": len(values), "p50": round(percentile(.5), 3),
            "p95": round(percentile(.95), 3)}


def router_history(snapshot: dict) -> dict:
    recent = ((snapshot.get("model") or {}).get("recent_calls") or [])
    router = [call for call in recent if call.get("purpose") == "router.classify"
              and call.get("status") == "completed"]
    rows = [{"total_ms": (call.get("timings_ms") or {}).get("total")} for call in router]
    return {
        "historical_completed_calls": len(router),
        "total_ms": metric_summary(rows, "total_ms"),
        "scope": "Existing Agent observatory history; NOT timings of this benchmark's synthetic calls",
    }


def _without_text(row: tuple[dict, str]) -> dict:
    return row[0]


def run(agent_url: str, sizes: list[int], samples: int, max_tokens: int, timeout: int) -> dict:
    before = request_json(agent_url, "/api/performance/observatory?limit=100")
    check_idle(before)
    identifier = secrets.token_hex(8)
    short = []
    for _ in range(samples):
        check_idle(request_json(agent_url, "/api/performance/observatory?limit=100"))
        short.append(_without_text(agent_stream(
            agent_url, [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": QUESTION}], max_tokens, timeout
        )))

    experiments = []
    for target in sizes:
        check_idle(request_json(agent_url, "/api/performance/observatory?limit=100"))
        original = user_context_message(synthetic_context(target, identifier, f"primary-{target}"))
        fresh = user_context_message(synthetic_context(target, identifier, f"control-{target}"))
        initial = [{"role": "system", "content": SYSTEM},
                   {"role": "user", "content": original}]
        prime, answer = agent_stream(agent_url, initial, max_tokens, timeout)
        followup = initial + [
            {"role": "assistant", "content": answer},
            {"role": "user", "content": QUESTION},
        ]
        check_idle(request_json(agent_url, "/api/performance/observatory?limit=100"))
        repeated = _without_text(agent_stream(agent_url, followup, max_tokens, timeout))
        control = [initial[0], {"role": "user", "content": fresh},
                   {"role": "assistant", "content": answer}, {"role": "user", "content": QUESTION}]
        check_idle(request_json(agent_url, "/api/performance/observatory?limit=100"))
        control_result = _without_text(agent_stream(agent_url, control, max_tokens, timeout))
        experiments.append({
            "nominal_context_tokens": target,
            "context_characters": len(original),
            "priming": prime,
            "same_prefix_followup": repeated,
            "different_prefix_control": control_result,
            "control_minus_followup_first_content_ms": round(
                control_result["first_content_ms"] - repeated["first_content_ms"], 3
            ),
        })
    after = request_json(agent_url, "/api/performance/observatory?limit=100")
    return {
        "schema": 1,
        "mode": "protected_agent_stream",
        "short": {
            "samples": short,
            "first_content_ms": metric_summary(short, "first_content_ms"),
            "total_ms": metric_summary(short, "total_ms"),
        },
        "contexts": experiments,
        "router": router_history(after),
        "notes": [
            "Only synthetic data was sent; no prompts or generated text are saved.",
            "Agent runtime locks/leases and admission guard remain in control; no model settings changed.",
            "Context sizes are nominal estimates (4 characters per token), NOT actual tokenizer counts.",
            "TTFT is first visible content; first SSE/heartbeat can arrive earlier.",
            "TTFT includes queuing and prefill; the Agent SSE endpoint does not expose native prompt_ms.",
            "Same-prefix vs different-prefix results suggest, but cannot prove, cache reuse.",
            "Order, warmed weights, other Agent activity and model output length can affect timing.",
            "The synthetic stream bypasses intent classification; router observations are historical only.",
            "Observe repeated results under similar idle/thermal conditions before attributing speedups.",
        ],
    }


def save_private(path: Path, data: dict) -> None:
    # Refuse overwriting another benchmark and restrict permissions.
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-url", type=local_agent_url, default=DEFAULT_AGENT)
    parser.add_argument("--context-sizes", type=context_sizes, default=[4000])
    parser.add_argument("--samples", type=int, choices=range(1, 7), metavar="{1..6}", default=3)
    parser.add_argument("--max-tokens", type=int, choices=range(16, 129), metavar="{16..128}", default=48)
    parser.add_argument("--timeout", type=int, choices=range(10, 601), metavar="{10..600}", default=180)
    parser.add_argument("--output", type=Path, help="Optional private JSON report; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        report = run(args.agent_url, args.context_sizes, args.samples, args.max_tokens, args.timeout)
        if args.output:
            save_private(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Benchmark aborted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
