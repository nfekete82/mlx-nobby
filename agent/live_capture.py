"""Opt-in HTTP capture for real agent evaluation, not a truth scorer.

POSTs JSON payloads to one explicitly supplied loopback URL. Outputs raw
question/response/latency records, without inventing before/after or reviews.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname not in
            {"localhost", "127.0.0.1", "::1"} or
            parts.username or parts.password or parts.fragment):
        raise ValueError("Only explicit loopback HTTP endpoints are permitted")
    return url


def capture(questions, endpoint, *, timeout=120, transport=None):
    """Capture an explicit local endpoint response for each question."""
    validate_url(endpoint)
    if not isinstance(questions, list) or not questions:
        raise ValueError("At least one question required")
    if len(questions) > 100:
        raise ValueError("At most 100 questions per capture")
    result = []
    for i, question in enumerate(questions, 1):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Every question must be nonempty")
        payload = json.dumps({"message": question}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        begin = time.perf_counter()
        try:
            if transport:
                response = transport(req, timeout)
                body = response
            else:
                with urllib.request.urlopen(req, timeout=timeout) as opened:
                    body = opened.read()
            elapsed = round((time.perf_counter() - begin) * 1000, 2)
            decoded = json.loads(body)
            if not isinstance(decoded, dict):
                raise ValueError("Response must be a JSON object")
            result.append({"id": f"live-{i:03d}", "question": question,
                           "elapsed_ms": elapsed, "response": decoded,
                           "review_status": "pending"})
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            elapsed = round((time.perf_counter() - begin) * 1000, 2)
            result.append({"id": f"live-{i:03d}", "question": question,
                           "elapsed_ms": elapsed, "error": str(exc),
                           "review_status": "error"})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True,
                        help="Local JSON POST agent endpoint accepting {message: question}")
    parser.add_argument("--questions", required=True,
                        help="JSON array of question strings")
    parser.add_argument("--output", required=True, help="Raw JSONL destination")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    results = capture(questions, args.endpoint, timeout=args.timeout)
    output = Path(args.output)
    if output.exists():
        parser.error("Output exists; refusing to overwrite historical evidence")
    with output.open("x", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"attempted": len(results),
                      "ok": sum("response" in row for row in results),
                      "errors": sum("error" in row for row in results),
                      "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
