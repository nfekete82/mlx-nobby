# Hybrid APC + DFlash2 benchmark runbook

Use [the current report](HYBRID_APC_DFLASH_FINAL_REPORT.md) for acceptance
status. Historical experiment documents describe earlier branches and are
not release approval.

## Integration versus standard activation

Optional/default-inactive code integration is assessed separately from
production/default activation in the current report. The integration closeout
runs deterministic regressions and final CI only. It does not rerun the lengthy
commands below, raise guards or claim their failed/incomplete results passed.
Hybrid requires explicit profile selection; Early remains off unless explicitly
enabled. Roll back to the saved profile (standard: `mlx chat-profile default`),
restore saved environment values and verify health while idle. Merge does not
change existing config, LaunchAgents or services.

## Preconditions

Use Apple Silicon with Metal, MLX-VLM 0.6.17, an already cached compatible
DFlash2 target/draft pair and running Agent, web and model services. Run
`./scripts/mlx chat-profile status`. The causal runner checks that the hybrid
adapter is live and the Agent reports no active/queued runtime jobs before
restarting. Run no other chats, image or video jobs during measurements.

These commands interrupt only the chat model server. Each four-arm run
restarts it five times, including restoration. Measured source code must stay
unchanged throughout a measurement series. Keep Agent and model services
running throughout the soak; a service restart or broken stream invalidates
the continuous-run result. Preserve the failed report and start a fresh run
rather than adding elapsed time from interrupted attempts. Keep private outputs
outside Git.
Before testing, record the current profile, local config hash and launchctl
settings. Environment values in the local config can override launchctl;
the runner rejects a requested step that the live server did not adopt.

## Controlled experiment

For current full-response acceptance (explicitly restarts idle chat and takes
at least two hours), use:

```sh
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-acceptance-new \
  --phase all --confirm-restarts
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-numeric-new \
  --phase numeric --confirm-restarts
./test-venv/bin/python scripts/validate-hybrid-rag-e2e.py \
  --output /tmp/hybrid-rag-new --python "$PWD/test-venv/bin/python" \
  --late-context 1 --confirm-source-test
# Repeat with a new output directory and --late-context 0 for default placement.
```

Output directories must not already exist. `all` runs the native quality/RAG
fixtures and an uninterrupted >=7200-second mixed workload, then cache-OFF,
hybrid, native and forced controls over 22 fixed-history tasks, followed by
three rotated performance triples (cache-OFF, hybrid and native). The original
20 tasks remain intact; two extended explanations exercise complete outputs
above 2048 generated tokens. Complete answer capture uses a 4096-token
allowance; check the actual backend finish reason. A `length` response fails
the completeness requirement regardless of matching text. Priming/numerical
requests allow at least 2048 tokens. Actual answers may correctly use fewer.

For an explicitly narrower, complete-response performance series when extended
outputs cannot safely run, select and record three task indices:

```sh
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-short-perf-new \
  --phase perf --perf-tasks 0 8 13 --confirm-restarts
```

The default performance tasks remain 0/20/21. Explicit shorter selection changes
only performance requests; it never replaces or passes the 22-task quality
matrix or the soak. Interpret its results only for those selected workloads.
Final measurements on `72017cd` used 0/8/13 after long-output swap failures;
see the report for medians, ranges, missing native benefit and release blockers.

Token/config fingerprints come from the actual queued backend input, not the
browser payload. Numerical diagnostics hash all 64 real layer states and
prefill logits, one layer at a time after exact float32 conversion of supported
lower precision values. These diagnostic CPU transfers are excluded from timing
claims. Ordinary audit does not transfer caches. All raw answers, audit records,
recovery config and reports are owner-only and must stay outside GitHub.

Before each request admission requires normal pressure, >=6 GiB headroom
and <=1 GiB kernel swap growth above the observed running minimum. It waits up
to 120 seconds for safe headroom, records those waits, and
stops on persistent shortage; it never lowers the threshold. Per-request timing
starts after admission, so report admission delays separately. Five-second RSS
and pressure samples are not instantaneous peak measurements. Metal metrics
are captured on each completed backend generation. Live generation can consume
the pre-admission reserve; the final long-output attempts did so and failed the
swap criterion. Between-request guards do not prevent a single response from
overshooting the limit. Keep failed evidence and do not loosen thresholds.
Warm `prefill_tok_s` retains upstream effective full-prompt TPS so the server
can reconstruct true elapsed time; diagnostic log rate counts only newly
computed tokens. Decode throughput and complete wall time are separate metrics.
Cleanup restores exact config before a bounded wait through temporary Agent
unavailability and restarts only after confirming idle. A failed automatic
restoration requires explicit verification/recovery, never a success claim.

RAG E2E creates one uniquely owned synthetic knowledge source through the real
Agent, uses the already available embedding model, and starts a temporary
production web backend on an allocated loopback port. It removes only its own
source and verifies other source records afterwards. Production web/container
flags remain unchanged. Isolated FTS/model fixtures remain a separate, narrower
layer. Neither layer proves resistance to all attacks or all retrieval policies.

The older short controller below remains useful as a diagnostic, with a
700-token cap; its historical 580/324-token results precede the final guarded
checkpoint correction and must not be represented as current measurements.

```sh
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only
python3 scripts/benchmark-chat-cache-causal.py \
  --confirm-restarts --compare-native --fixed-history \
  --capture-answers --diagnose --prefill-step 256 \
  --output /tmp/hybrid-256-pair1.json
```

Repeat at least three times with different output filenames, and repeat at
512 and 1024 where natural boundaries exist. Each run uses temperature zero,
700 maximum output tokens and identical client prompts/history replayed from
its `baseline1` capture. The cases are:

| Arm | Exact slots | Early snapshot | Boundaries |
| --- | ---: | --- | --- |
| baseline1 | 1 | disabled | baseline hybrid |
| baseline2 | 2 | disabled | baseline hybrid |
| early2 | 2 | enabled | forced diagnostic split |
| native2 | 2 | enabled | existing baseline hybrid boundaries |

This baseline is hybrid without early checkpoints, **not cache OFF**. Compare
DFlash2 without APC separately using the profile comparator, but do not treat
its independently generated conversation as an identical-history control:

```sh
./scripts/mlx chat-profile compare --include-hybrid
```

`--compare-slots` adds the split-only control (same forced forward boundaries,
no early snapshot). This separates the effect of changing the arithmetic
path from snapshot storage itself. The older `benchmark-chat-cache-ab.py`
is a forced-split diagnostic using two exact slots. With answer capture it
replays each OFF history for its paired ON run; without capture it cannot
establish prompt equality and cannot satisfy the release gates.

## Evidence and limits

Compare every turn's `request_sha256` and `answer_sha256`, not answer lengths.
The first turn must have zero hits. Equal client request hashes do not prove
equal backend enrichment, token IDs or semantic hash; verify these separately
before release. Neither textual similarity nor a longer answer establishes
semantic quality. Review cache-hit responses for facts, completeness,
instruction adherence and RAG grounding.

Record first-content latency, total duration, actual cached tokens and
per-run configuration. Browser first-content includes web/Agent overhead and
is not raw model TTFT. This runner does not directly measure reliable generated
tokens/second; do not derive it from character count. Backend completion logs
can supply actual generated-token counts, decode rates and finish reasons only
when uniquely correlated to the captured request. Check `finish_reason=length`:
equality at a token cap does not certify completeness of the answer. Shared-server cache
counters require exclusive traffic. Browser routing may itself make a
`router.classify` model call in the same trace; this can alter APC counters,
LRU state and backend inputs even with equal client hashes. Exclude such
non-comparable arms rather than treating their global deltas as chat-only
hits. Upstream's pool eviction counter also does not count exact-LRU pops. The source-guarded snapshot budget logs
numeric payload sizes in `HYBRID_APC_MEMORY`; `resident_bytes` omits exact
snapshots. The causal report includes process RSS before/after where available;
these are not peak-RSS measurements. Agent swap/pressure samples may be cached.

A release additionally requires repeated mixed-prompt and long-conversation
runs **without restarting the server**, peak memory/pressure sampling, eviction
and invalidation checks, safe fallbacks, RAG injection tests and backend token
identity. A short restarted probe does not satisfy those requirements.
`checkpoint_release_gates.evaluate` requires complete paired evidence and
explicitly reviewed backend/configuration, long-session and trust-boundary
results. Missing evidence produces REVIEW, never PASS.

## Configuration and cleanup

| Variable | Default | Purpose |
| --- | --- | --- |
| `NOBBY_HYBRID_EARLY_CHECKPOINT` | disabled | optional second checkpoint |
| `NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE` | `1` | natural boundaries; explicit `0` is forced-split research |
| `NOBBY_HYBRID_EARLY_CHECKPOINT_STORE` | `1` | `0` keeps the split but skips early storage |
| `NOBBY_HYBRID_EXACT_CACHE_ENTRIES` | `1` | hybrid profile accepts only 1 or 2 |
| `NOBBY_HYBRID_CACHE_MAX_MIB` | `1024` | retained exact tensor payload plus pending clone; 64–8192 |
| `MLX_PREFILL_STEP_SIZE` | adaptive | 128–4096; runner verifies the live process argument |
| `NOBBY_HYBRID_CACHE_DIAG` | disabled | numeric prefix/LRU diagnostics |
| `MLX_PROMPT_STAGE_DIAG` | disabled | backend system-prefix stage diagnostics |
| `NOBBY_RAG_LATE_CONTEXT` | disabled | experimental late untrusted RAG placement |
| `NOBBY_CLOCK_CONTEXT_ALWAYS` | disabled | restore unconditional live clock injection |
| `NOBBY_CLOCK_CONTEXT_STABLE` | disabled | opt in to experimental per-turn clock omission |
| `NOBBY_HYBRID_AUDIT_FILE` | unset | private backend token/argument/Metal audit JSONL; owner-only directory |
| `NOBBY_HYBRID_AUDIT_STATE` | disabled | extra numerical cache/logit diagnostic; exclude from timing |

`NOBBY_RAG_LATE_CONTEXT`, `MLX_PROMPT_STAGE_DIAG` and
`NOBBY_CLOCK_CONTEXT_ALWAYS` and `NOBBY_CLOCK_CONTEXT_STABLE` belong to the web backend/container environment,
not the native MLX LaunchAgent. Configure/recreate that backend explicitly if
changing them. The native benchmark controllers do not change those backend
settings; keep them fixed and verify their deployed behavior separately.

Only set the flags needed for a diagnostic. Both runners restore tracked
launchctl values including values that were originally unset, and restart
with those original settings. Cleanup failures are errors. A hard kill or
power loss cannot run Python `finally`; inspect and restore launchctl settings
manually in that case. Do not run benchmark controllers concurrently.

Raw answer captures are explicitly requested, 0600 files under a 0700
directory. They contain local generated text; do not commit them. Reports
contain numeric metadata and hashes, which should also remain local unless
reviewed. The checked-in report must contain only sanitized measurements.
