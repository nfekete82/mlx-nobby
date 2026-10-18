# Hybrid APC + DFlash2 benchmark runbook

Use [the current report](HYBRID_APC_DFLASH_FINAL_REPORT.md) for acceptance
status. Historical experiment documents describe earlier branches and are
not release approval.

## Preconditions

Use Apple Silicon with Metal, MLX-VLM 0.6.17, an already cached compatible
DFlash2 target/draft pair and running Agent, web and model services. Run
`./scripts/mlx chat-profile status`. The causal runner checks that the hybrid
adapter is live and the Agent reports no active/queued runtime jobs before
restarting. Run no other chats, image or video jobs during measurements.

These commands interrupt only the chat model server. Each four-arm run
restarts it five times, including restoration. The repository code must stay
unchanged throughout a measurement series. Keep private outputs outside Git.
Before testing, record the current profile, local config hash and launchctl
settings. Environment values in the local config can override launchctl;
the runner rejects a requested step that the live server did not adopt.

## Controlled experiment

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
is not raw model TTFT. This runner does not measure reliable generated
tokens/second; do not derive it from character count. Shared-server cache
counters require exclusive traffic. The source-guarded snapshot budget logs
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

Only set the flags needed for a diagnostic. Both runners restore tracked
launchctl values including values that were originally unset, and restart
with those original settings. Cleanup failures are errors. A hard kill or
power loss cannot run Python `finally`; inspect and restore launchctl settings
manually in that case. Do not run benchmark controllers concurrently.

Raw answer captures are explicitly requested, 0600 files under a 0700
directory. They contain local generated text; do not commit them. Reports
contain numeric metadata and hashes, which should also remain local unless
reviewed. The checked-in report must contain only sanitized measurements.
