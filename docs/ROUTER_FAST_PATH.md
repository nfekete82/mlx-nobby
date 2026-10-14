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

## Guarded follow-up extension (stacked PR)

The browser passes up to eight previous messages as `{"role":"user"|"assistant","content":"..."}`
pairs, not authoritative prior routing decisions. For that reason, the
extension remains intentionally narrow:

- Accept only exact, short **explanatory** follow-ups: for example,
  "Kannst du das einfacher erklären?" and "Kannst du ein Beispiel dazu geben?".
- Require a correctly ordered, complete user/assistant transcript with
  2–8 previous messages. Unknown roles, partial turns, extra metadata and
  empty assistant replies are rejected.
- Require the *first* previous user turn to pass the original safe standalone
  allowlist; every subsequent previous user turn must itself match the narrow
  explanation-only continuation pattern.
- Reject conversation replies containing obvious tool/agent markers, fenced
  code or external links. The assistant's text is not a verified routing
  certificate, so this is a **conservative heuristic**, never a permission
  to execute tools.
- Require **no** file context and **no** active coding workspace; the global
  `MLX_CHAT_FAST_PATH_ENABLED=0` opt-out still disables the shortcut.
- Report `method=simple_chat_followup_fast_path` only for admitted turns.
  Every uncertain follow-up returns to the existing semantic router.

These additional safeguards deliberately make the feature **ineligible** in
many real histories. This is preferable to incorrectly skipping research,
files, or agent checks. A future extension would need trusted server-side
routing provenance and a measured miss/false-positive rate, not simply looser
regular expressions.

Local unit validation for this extension:

    MLX_TEST_PYTHON="$HOME/mlx-web-release-check/test-venv/bin/python" \
      ./scripts/mlx test-quick tests/test_chat_safe_followups.py

The original 2026-10-14 five-run A/B test measured **routing only** for the
standalone prompt "Nenne die zwei Farben Rot und Blau in einem Satz." Its
median fell from 544.1ms to 0.7ms, saving 543.4ms. That does not establish
the impact or route accuracy of this follow-up extension. Run a new matched
A/B study with the same benign conversational history before merging.

## Version discipline

This feature targets the release *after* v1.11.0. The product's `VERSION`,
README release badge and historical changelog sections remain at v1.11.0
while release PR #208 is pending. Keep this entry in `Unreleased` and bump
to v1.12.0 only in a separate, tested release-metadata PR once v1.11.0 is
published. Runtime library pins (MLX-VLM, MLX-LM, MLX-Audio) are not changed
by this routing feature.
