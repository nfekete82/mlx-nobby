# Repeated Live Benchmark

Runs 1–5 repetitions (default: five) of up to 20 questions against the actual
local Agent endpoint. Results include median, nearest-rank p95, min/max latency,
per-question cohorts, failure rate, model-call purposes, token counts, lease and
model-lock waits, model setup and upstream duration, plus heuristic warnings. This is **not** a factual
accuracy benchmark: inspect answers and independently verify evidence.

```bash
python -m pytest tests/test_repeated_benchmark.py -q
python -m agent.repeated_benchmark \
  --questions performance-questions.json \
  --repeats 5 \
  --timeout 180 \
  --model-label Qwen3.8-27B-4bit \
  --output-prefix performance-benchmark-v9
```

Files are created locally:
- `performance-benchmark-v9.jsonl`: full responses; potentially sensitive.
- `performance-benchmark-v9-report.json`: metadata and warning flags only.

Output files cannot be overwritten. Requests default to sequential; repeated live
runs may take several minutes and involve real web searches. The endpoint is
restricted to HTTP loopback. A failed run counts as an error rather than a
successful answer. Interpret the median only for completed runs and compare
like-for-like question sets and execution conditions.

Use `--concurrency 2` (maximum four) and a **different output prefix** for a
separate parallel-load cohort. Never compare that cohort's latency directly to
the sequential acceptance target. Both use the existing shared runtime lease,
model locks and RAM guard. A short cohort's nearest-rank p95 is its maximum,
not a statistically stable tail estimate.

The report records UTC start/end, concurrency, repetition count, request timeout,
OS, architecture, Python version and logical CPU count. `--model-label` is an
operator-supplied label, not an automatic assertion of which weights were loaded.
Record the revision, physical memory, actual model role/configuration, memory
pressure and any other concurrent workloads alongside the report. Do not publish
paths, prompts, raw captures or full runtime configurations.

Raw JSONL captures are persisted incrementally, including failed responses. The
summary uses question indexes and omits prompts and article contents. Known token
totals can be incomplete when the upstream server does not expose separate input
and output usage. `upstream_request_ms` includes the native server's response
overhead; it is not a direct Metal-kernel timing. Quality flags identify review
work and cannot establish factual correctness or completeness. Archived captures
use their recorded capture date for temporal checks when available.
