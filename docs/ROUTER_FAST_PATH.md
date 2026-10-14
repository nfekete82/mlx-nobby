# Router Fast Path (planned v1.12.0)

## Reason for this change

Measured on a local 48 GiB Apple Silicon Mac (2026-10-14), five visible
`router.classify` calls took about 509–772 ms (median 576 ms).
Warm `chat.stream` calls took approximately 718–733 ms (median ~720 ms).
These are per-operation observations, not matched end-to-end A/B results.
No production latency improvement is claimed without further measurements.

## Scope and safety

The existing deterministic routing, media intent checks, file actions and
security/agent gates run first. The new `agent/chat_fast_path.py` allowlist
then handles only a small set of greetings, short evergreen standalone
questions and simple creative-text requests. All other requests use the
existing semantic router. The shortcut:

- Does not read or persist user prompts; its classification is local regex.
- Never executes a tool and only emits `normal_chat`, `requires_tools=false`.
- Rejects attached files, conversation history and active coding workspaces.
- Rejects freshness and external-source markers, personal references,
  project/system terms, file actions, financial queries and media outputs.
- Is skipped if a test or caller injects a semantic or manager classifier.
- Fails closed if the workspace lookup raises a supported error.
- Records routing `method=simple_chat_fast_path` via the existing route
  metadata; other routing methods remain unchanged.

The default is enabled for this *narrow* allowlist. To disable it set
`MLX_CHAT_FAST_PATH_ENABLED=0` in the **Agent process environment**.
Setting it in an unrelated terminal does not alter an already running
LaunchAgent. Reload/restart the Agent only when it is idle, following the
normal Nobby service procedure. Valid off values are `0`, `false`,
`off`, and `no` (case insensitive).

## Validation

Run CPU regressions first:

    ./scripts/mlx test-quick tests/test_chat_fast_path.py

Then run full release regression on the feature branch before promotion:

    ./scripts/mlx test-release

Verify normal chat, coding workspaces, web research, media, file uploads and
real semantic fallback with the same loaded models and unchanged config.
The shortcut should save a single small-router inference only on eligible
requests; the exact latency saved depends on workload and runtime state.

For meaningful end-to-end A/B data, compare the same short, eligible prompts
with the shortcut enabled/disabled in controlled separate sessions. Record
TTFT, total duration, selected route, router invocation count and incorrect
routing. Do not compare the existing 2-token native benchmark to the
different Web streaming prompt as if they were identical requests.

## Version discipline

This feature targets the release *after* v1.11.0. The product's `VERSION`,
README release badge and historical changelog sections remain at v1.11.0
while release PR #208 is pending. Keep this entry in `Unreleased` and bump
to v1.12.0 only in a separate, tested release-metadata PR once v1.11.0 is
published. Runtime library pins (MLX-VLM, MLX-LM, MLX-Audio) are not changed
by this routing feature.
