# Browser APC prefix diagnostic (opt-in)

The working Agent probe in PR #279 produced two exact APC hits from three
synthetic turns. Real browser chats previously stored checkpoints without
retrieval. The browser path differs: it calls `/api/chat/stream`, sends
`system_prompt` and `context_sources`, and may compact earlier conversation
history before sending it.

This change instruments the **actual browser send boundary**. When disabled,
the diagnostic retains no prior data. When enabled, it compares consecutive
inference payloads in ephemeral tab memory without sending the diagnostic data
to a server. Browser console output includes role/character counts, number of
unchanged previous messages, character prefix length of the first changed
message, and whether system prompt and context sources changed. It does **not**
print source contents, prompts, answers, fingerprints or hashes. Comparisons
are string-based, not model-tokenizer-aware.

## Run

On an idle Mac, build the frontend image from this branch. Keep the hybrid
profile if it is already active; no server restart or profile switch is needed
for the standalone MLX model, but the web container must be rebuilt.

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/diag/browser-apc-prefix
./test-venv/bin/python -m pytest -q tests/test_browser_apc_prefix_diagnostics.py
docker compose up -d --build --no-deps mlx-web
```

Open browser developer tools in the MLX-Nobby tab and enable one tab only:

```js
sessionStorage.setItem('mlx-apc-prefix-diagnostic', '1');
location.reload();
```

Send 3 successive **text-only messages in one session**. Observe the console
lines `[MLX APC prefix diagnostic]`. Independently check exact-hit counters:

```bash
curl -s http://127.0.0.1:8000/v1/cache/stats | python3 -m json.tool
```

Turn off:

```js
sessionStorage.removeItem('mlx-apc-prefix-diagnostic');
location.reload();
```

If `system_prompt_same` is false or `context_sources_same` is false, inspect
the corresponding application feature without recording its content. If prior
history changes unexpectedly, inspect compaction and message serialization.
These metadata comparisons alone cannot establish the root cause. No attempt
is made to relax exact APC matching, disable context features, or overwrite
the real conversation.

Known limits: browser reload resets in-memory comparison; the diagnostic
cannot see server-side Agent/MLX prompt transforms; exact match on message
strings is not necessarily exact match on tokenized chat templates; and
a browser request's last message should normally differ from the prior one.
