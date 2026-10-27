# Inference optimization 2.0 — 2026-10-27

Local baseline: `4742d9f`, branch `main`. No pull, checkout, reset, model
download or modification of existing user configuration was performed.
Existing untracked LTX work and captures were left untouched.

## Confirmed bottleneck and retained changes

The historical approximately 500 ms router call still exists. Some simple
first-turn questions already bypass it. Other ordinary chat turns perform
**three identical classifications**: action preflight, action execution check,
and the text-stream knowledge-routing check. The measured short-turn median
was 1,534 ms of aggregate router inference before a roughly 200 ms native TTFT.

Two changes are implemented:

1. **Reuse identical classifier inputs within one traced turn.**
   `agent/router_turn_cache.py` holds at most 128 validated raw classifier
   responses, each at most 8 KiB, with a five-second validity window and lazy
   expiry. Keys contain the trace ID and SHA-256 of the exact model, URL,
   messages and generation parameters. Prompts are not retained in keys.
   Missing traces, failures, invalid JSON and oversized responses are not
   reused. `MLX_ROUTER_TURN_REUSE=0` disables reuse. This caches neither tool
   results nor execution authorization: deterministic rules, fresh workspace
   decisions, manager arbitration and permission/execution gates still run.
2. **Allow independently safe questions in verified benign conversations.**
   The existing conservative follow-up path can now accept the same standalone
   informational/creative requests already accepted without history. Every
   visible user turn and assistant response is checked; generation receives the
   full unchanged context. Active/uncertain workspaces, files, unexpected
   metadata, tool/code/source history, changing facts and action requests retain
   existing routing. Acknowledgments such as “OK” cannot authorize this shortcut.
   English file/save/update requests and German save requests are explicitly
   excluded from the allowlist.

No router is globally disabled. Unrecognized standalone requests still classify;
the tested benign conversations require no additional classifier inference.

## Measurement procedure

The actual loaded model was **Qwen3.8-27B-Uncensored, 6-bit**, not a substituted
4-bit checkpoint. Its native process and runtime settings remained unchanged:
MLX 0.32.2 / MLX-VLM 0.6.17, prefill step 1024, continuous batching, maximum two
backend sequences, temperature 0, thinking disabled, output cap 96.

Three synthetic workloads used **59 / 351 / 1,944 actual input tokens** and
identical **38-token answers**. Each variant ran one excluded warm-up and five
measured warm trials. Variants were baseline, classifier reuse alone, and both
changes. Direct native controls also ran five warm trials before/after.

The HTTP benchmark executes the actual frontend request sequence through real
Agent/Web entrypoints and both production routers/middleware stacks. It uses
separate loopback processes, empty temporary homes, a fixed synthetic clock,
empty memory, and the already loaded native models. Model selection is pinned
in the fixture to prevent switches; tool execution is disabled there. This
isolates measurements from private profiles and changing clock tokens without
altering production configuration. Only usage collection is added to native SSE.
Request, actual upstream model-input and answer hashes matched across variants.

An additional installed Chromium test used the real unmodified chat page,
Send button, streaming fetch/parser and DOM renderer. Five warm trials measured
click-to-first-content and the next animation frame containing model text.
External page assets were loaded normally; no mock token stream was substituted.

## End-to-end results

Times are milliseconds; ranges are the minimum–maximum of all five warm trials.
HTTP TTFT excludes DOM rendering and includes preflight, action check and stream.

| Workload | Baseline median [range] | Reuse only | Both median [range] | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Short, 59 tokens | 1,775 [1,773–2,124] | 891 [817–927] | 760 [755–766] | 57.2% |
| Benign history, 351 tokens | 2,653 [2,644–2,908] | 1,332 [1,299–1,384] | 585 [559–615] | 78.0% |
| Benign history, 1,944 tokens | 5,288 [5,235–5,317] | 3,566 [3,517–3,700] | 2,878 [2,832–3,051] | 45.6% |

The second shortcut does not apply to the short, unrecognized first-turn prompt.
Its additional movement between the two candidate runs is runtime/router
variation, not an additional history-fast-path benefit; both make one classifier
call. The medium/long ablation separately demonstrates removal of the remaining
classifier call by the second change.

| Latency component | Short before → after | Medium before → after | Long before → after |
| --- | ---: | ---: | ---: |
| Classifier calls per turn | 3 → 1 | 3 → 0 | 3 → 0 |
| Aggregate router inference | 1,534 → 529 | 2,000 → 0 | 2,196 → 0 |
| Action-check HTTP request | 507 → 6 | 643 → 3 | 713 → 3 |
| Native prefill, server-reported | 138 → 132 | 565 → 505 | 2,951 → 2,779 |
| Agent lease/lock wait | 12.8 → 11.2 | 11.6 → 10.7 | 9.0 → 12.4 |

Per-request residual after router inference, native prefill and measured queue
wait was approximately 69–93 ms at the medians. It combines first-token decode,
HTTP/JSON transport and prompt/dispatch preparation; it is not a measurement of
network time alone. Component medians need not add exactly to an end-to-end median.

Real Chromium, medium workload:

| Browser metric | Baseline median [range] | Both changes median [range] |
| --- | ---: | ---: |
| Click → first semantic stream content | 2,667 [2,501–3,236] | 566 [561–567] |
| Click → frame containing model text | 2,698 [2,532–3,265] | 599 [582–599] |
| Content arrival → renderer frame | 30.4 [28.1–32.9] | 32.3 [20.8–33.7] |

Visible response latency fell **77.8%** in this browser workload. The frontend
rendering itself was not accelerated. These are bounded local comparisons,
not population-wide percentiles or guarantees for all prompts.

## Native inference, tokenization and memory

| Direct native control, median | Short before → after | Medium before → after | Long before → after |
| --- | ---: | ---: | ---: |
| TTFT, ms | 201 → 196 | 600 → 621 | 3,067 → 2,829 |
| Prefill, tokens/s | 444 → 451 | 651 → 622 | 649 → 705 |
| Decode, tokens/s | 23.63 → 23.42 | 23.01 → 23.13 | 22.72 → 23.35 |

No native kernel, batching or sampling optimization is claimed from these
variations. The reproducible improvement is removal of redundant routing work.

A separate CPU-only, local-files-only tokenizer probe matched all three native
input token counts. Five warm chat-template/tokenization trials took medians
**0.10 / 0.32 / 1.51 ms**, with ranges 0.10–0.14 / 0.31–0.34 / 1.42–1.60 ms.
Tokenizer construction was separately approximately 330 ms; installed server
source reuses its model/processor/tokenizer and generation worker. Removing its
tokenizer lock would risk mutable-tokenizer races for negligible demonstrated
benefit. No unnecessary tensor synchronization or transfer was established as
the dominant bottleneck in the repository-owned text path. MLX-Gen image/edit
providers are not this active text-chat backend and were left unchanged.

Native `cache_n` was zero: KV state is used within decode, but cross-request
prefix reuse is inactive. APC, KV quantization and speculative draft/kind remain
disabled. No DFlash2/MTP draft was activated: equivalence and token acceptance
for an official-base draft are not established for this local modified model.
No experimental cache/kernel change was retained without that evidence.

The runtime's cumulative MLX peak reached **25.042 GB** in both baseline and
candidate sequences; peaks were not reset per request. Native guarded controls
observed minimum free-memory estimates of 21% before and 27% after, above the
existing 20% active-workload tripwire. System swap fluctuated with the complete
test/browser sequence and is not attributed to these changes. Final live memory
pressure was normal, 36% estimated free. The classifier cache bounds retained
response bytes to at most 1 MiB plus metadata. The 90% admission limit, load
reserves, runtime leases, cancellation and model/media coordination are unchanged.

## Quality, regression and activation

All synthetic answers were checked to contain exactly the requested numbers;
answer hashes and actual model-input hashes matched before/after, including the
browser comparisons. This is exact parity for the tested workloads, not a
universal model-quality certification.

All **15 representative routing cases** preserved final intent, target and
requires-tools fields: normal chat, benign continuation, coding, active
workspace, local knowledge, public research, weather, file summary/transform,
image/video execution, media advice, diagnostics and acknowledgment. Only
preflight decisions were exercised for tool cases; no real tools or media jobs
were executed. **328 distinct selected Python tests passed** across the routing,
permissions, AgentRuntime, OpenAI tool-call/gateway, streaming/disconnect and
vision groups. Socket-based tests were rerun outside the socket-restricted
sandbox. Existing TestClient/httpx deprecation warnings remain. Syntax and
diff checks passed; no full release matrix was run.

Only the Agent was gracefully restarted after checking queues, native services
and background jobs idle, while holding the existing maintenance lease. Web,
models and all other services remained running. Live requests through the real
web bridge confirmed **one** classifier call for the unrecognized standalone
turn and **zero** for the verified benign conversation. All nine service probes
returned healthy/ready/HTTP 200. The native model process and selected model
were preserved.

Evidence, the isolated harness and the original local baseline archive are in
the already ignored `artifacts/engineering-20261027/inference2/`. Examples:

```sh
test-venv/bin/python artifacts/engineering-20261027/inference2/bench_turn.py \
  --phase review --native
test-venv/bin/python artifacts/engineering-20261027/inference2/bench_turn.py \
  --phase review-browser --browser
```

Choose unused phase labels; the harness refuses to overwrite prior reports.
The first-pass cache-only source and baseline archive remain for ablation.
Rollback is available locally via `.../inference2/activate.py rollback`: it
requires an idle stack and matching candidate hashes, restores only the two
changed production Python files from the `4742d9f` archive, and restarts only
the Agent. It refuses to overwrite later source edits and does not reset Git.

The commit scope is six files: `agent/app.py`, `agent/chat_fast_path.py`,
`agent/router_turn_cache.py`, `tests/test_chat_safe_followups.py`,
`tests/test_router_turn_cache.py`, and this report. No push or release.
