# Hybrid cache semantic response parity (manual release blocker)

All 106 browser E2E tests passed, as did 3206 Python tests
(+433 subtests) and 280 Node tests in `test-medium`.
The five-pair A/B benchmark showed reproducible turn-3 APC hits
ON 5/5 vs OFF 0/5 and median faster first content.

**Why another check?** The existing tests measured answer lengths only.
With `temperature=0`, the OFF and ON variants also generated different
answer lengths on **turn one**, which had **zero exact cache hits in
both variants**. This could be benign numerical / chunk-boundary variation,
but it could also indicate a prefill or cache-state correctness problem.
We cannot assume identical semantics.

## Collect answer text, explicitly opting in

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/test/hybrid-cache-response-parity

./test-venv/bin/python -m pytest -q \
 tests/test_cache_response_parity.py \
 tests/test_benchmark_chat_cache.py \
 tests/test_chat_cache_ab.py \
 tests/test_checkpoint_release_gates.py
./test-venv/bin/python -m py_compile \
 scripts/benchmark-chat-cache.py \
 scripts/benchmark-chat-cache-ab.py

./scripts/mlx benchmark chat-cache-ab \
 --confirm-restarts --pairs 2 --quality-review --capture-answers
```

This runs four three-turn conversations and restarts the model server five
times, including restoration. **Do not run alongside other inference jobs.**
The script attempts to restore the original flag on exit.

Raw answers are saved only with explicit `--capture-answers` in
`/tmp/chat-cache-ab-report-answers/run1-off.json`, `run2-on.json`,
etc. The directory is owner-only mode 0700, and the files are mode 0600.
Do not commit, copy to public issues, or upload files without reviewing
their contents: locally retrieved source material may be present.
A normal A/B summary report contains lengths/similarity but not raw
answer strings.

## Manual review

Compare turn 1 OFF vs ON first: neither run has a valid cache hit on turn
1, so differing answers deserve attention independently of the turn-3
optimization. Then compare turn 2 and turn 3 for:

- Accuracy and completeness about unified Apple Silicon RAM.
- No truncation, duplicated answer sections or unexpected instructions.
- No RAG / tool content promoted to trusted system instructions.
- No unsupported numerical/spec claims about 48 GB.
- No significant omissions or regressions from ON.

The A/B JSON `quality_review.status` remains `PENDING`; textual
identity and similarity scores are *signals, not semantic proof*. If
first-turn output differs, the report highlights it as a warning.
Investigate chunk-boundary semantics, logits equality and speculative
prefill before enabling early checkpoints by default.

Merge after separate manual approval and full regression / security
review; passing cache-hit gates alone does not settle correctness.
