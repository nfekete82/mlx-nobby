# Repeated Live Benchmark

Runs 1–5 sequential repetitions of up to 20 questions against the actual
local Agent endpoint. Results include median, min/max latency, per-case model
call counts and conservative heuristic warnings. This is **not** a factual
accuracy benchmark: inspect answers and independently verify evidence.

```bash
python -m pytest tests/test_repeated_benchmark.py -q
python -m agent.repeated_benchmark \
  --questions performance-questions.json \
  --repeats 5 \
  --timeout 180 \
  --output-prefix performance-benchmark-v9
```

Files are created locally:
- `performance-benchmark-v9.jsonl`: full responses; potentially sensitive.
- `performance-benchmark-v9-report.json`: metadata and warning flags only.

Output files cannot be overwritten. All calls are sequential; repeated live
runs may take several minutes and involve real web searches. The endpoint is
restricted to HTTP loopback. A failed run counts as an error rather than a
successful answer. Interpret the median only for completed runs and compare
like-for-like question sets and execution conditions.
