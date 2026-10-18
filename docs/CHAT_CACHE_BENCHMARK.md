# Chat-cache terminal benchmark

Run a three-turn conversation through the **web backend** (same API path as
the UI) with persistent user/assistant history. Report first-content latency,
total response time, APC exact-hit delta, matched-token delta, and stores per
turn. The benchmark neither restarts the server nor clears the cache.

```bash
cd ~/mlx-web
./scripts/mlx benchmark chat-cache
./scripts/mlx benchmark chat-cache --json-out /tmp/chat-cache-benchmark.json
```

By default the script sends no browser `system_prompt`. For approximate
browser parity, provide the actual session system prompt explicitly:

```bash
./scripts/mlx benchmark chat-cache --system-prompt "..." --chart-suffix
```

The browser's exact session prompt depends on its current settings; this CLI
cannot retrieve it automatically. The browser also supplies extra context
accounting metadata; thus benchmarks are *backend-path*, not byte-for-byte UI
parity. Do not use the tool as proof of browser parity without checking that
prompt and routing are equivalent.

Stats are global and cumulative. Concurrent chats change the deltas. Model
outputs, warm caches, model selection and RAG can cause variability. No claimed
speedup is valid without a controlled comparison. Errors or truncated SSE
streams cause a nonzero exit. Answers are held only in memory for chat history,
not saved in the JSON report.

```bash
./test-venv/bin/python -m pytest -q tests/test_benchmark_chat_cache.py
```
