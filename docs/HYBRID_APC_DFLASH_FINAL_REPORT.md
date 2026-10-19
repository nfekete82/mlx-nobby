# Hybrid APC + DFlash2 integration and activation decisions

Date: 2026-10-19. Scope: optional-code integration, separate from production/default activation.

**A — Optional-code integration:** approve subject to the final regression,
compatibility, CI and repository-rule checks recorded below and on
[PR 299](https://github.com/nfekete82/mlx-nobby/pull/299). The merge adds guarded,
experimental code; it does not activate Hybrid or Early Checkpoint by default.
The actual last head, merge result and post-merge checks are recorded on that PR.

**B — Production/default activation:** **HOLD**. Historical failed/incomplete
quality, long-run, memory and broader performance evidence remains unchanged.
No failed gate is converted to PASS by separating these decisions. No new
product version, release tag or GitHub Release is part of this integration.
Version stays 1.19.0. The pre-integration main was
`b97c1f6b0001032f42ce22b347111a7cfa78b61f`.

## Final architecture and corrections


The opt-in MLX-VLM 0.6.17 in-memory adapter supports only exact-prefix,
single-sequence, text-only DFlash2. Token/hash matches restore complete cloned
KV/SSM states. Multimodal/batched requests retain the upstream path. Installed
MLX-VLM package files remain unchanged.

Guarded snapshots now use `floor((prompt_length - guard) / step) * step`.
Restored offsets must align with the current prefill step. The remaining tail
retains upstream's one-token final speculative capture whenever the original
prompt used chunked prefill. Both corrections matter: rounding the checkpoint
alone would still let a shortened tail switch to a multi-token capture.
Native early storage adds clones at existing boundaries; forced splits remain
an explicitly selected diagnostic with demonstrated different numeric state.

The existing one-slot, early-off and adaptive-step defaults remain. Two slots
are a bounded opt-in. The conservative 1024 MiB admission budget covers retained
exact state plus a pending clone; over-budget/unknown states skip storage.
It is not a cap on model weights, live inference, RSS or total Metal memory.
Old entries are not evicted merely to admit a larger-context snapshot; long
contexts may correctly run cold without gaining APC speed.

The Agent's automation scheduler had 124 open SQLite connections and could
no longer accept HTTP requests (EMFILE). Transaction completion now closes
connections deterministically, including rollback/setup errors. Regression
coverage keeps references alive so it cannot pass through garbage collection.
Only the idle exhausted Agent was restarted; model/service configuration was
preserved. Later checks observed zero open automation database descriptors.

The full-response run exposed another real integration defect: production
web recovery requested `chat_first_byte_timeout` while a separate benchmark
stream was generating, then restarted Agent and broke the stream. The private
recovery record and HTTP log identify this request; the earlier unknown cause
is now localized. Chat leases age from acquisition, so age alone does not
prove a stall. The gateway now tracks actual content/reasoning progress under
a lock. Non-forced recovery rejects recent live progress, while an expired
progress window still permits genuinely stalled-stream recovery. Context
cleanup unregisters completed/cancelled workers. Regression tests cover both
recovery decisions and the actual gateway producer. Benchmark cleanup also
restores config before waiting through transient Agent unavailability; it
never restarts until idle is confirmed. Implementation commit: `37b4e6c`.

Retrieved source strings are JSON-framed and angle-escaped in both default
and opt-in late placement. Fake chat roles and closing data delimiters cannot
become raw template markers. Trusted policy distinguishes source data from
instructions. Every source actually admitted to the answer context remains
attributable: the old stricter display-only threshold silently hid used sources.
This framing is not a universal prompt-injection guarantee. Experimental clock
omission now requires `NOBBY_CLOCK_CONTEXT_STABLE=1`; current time remains the
default. Native APC flags and web/backend flags are separate environments.

Warm prefill telemetry now preserves the upstream full-prompt TPS numerator.
MLX-VLM reconstructs elapsed time as full prompt tokens divided by this rate;
substituting only computed tokens had inflated reported warm prefill time.
The diagnostic log separately reports the computed-token rate. This correction
does not change model calls, cache state or decoding. Final implementation:
`72017cdb20f3f68a0ad2deb07b1ffde6328fc8af`. A subsequent QA-only correction
(`f836fe3`) excludes formatting-only chunks from word counts; prompts, model
arguments, cache adapter and decoding are unchanged. Archived raw outputs are
retained and reassessed rather than regenerated or silently rewritten.

## Full answer quality and backend identity

The maintained corpus has 22 tasks: the original 20 plus two extended DE/EN
explanations. It covers facts, mathematics, practical advice, executable code,
conversation history, long context, retrieved facts and conflicting sources.
Word counts below count whitespace-separated chunks containing a Unicode
letter or number, excluding pure Markdown/math delimiters. The earlier simple
whitespace checker over-counted those delimiters; its false word-limit failure
for task 20 is corrected. That answer still omits Streaming.
Quality requests allow 4096 tokens; primes/numerical requests allow at least
2048. Actual backend finish reasons and complete private text are retained.
`length` never counts as full quality. No failed fixture was replaced to pass.

The longest attempt completed 503 actual `stop` requests, including 33 outputs
of at least 2048 generated tokens. It predates the final recovery/telemetry
corrections and is not final-head two-hour evidence. Its initial long outputs:

| Task | Required words | Actual words | Actual generated tokens | Finish | Review |
| --- | ---: | ---: | ---: | --- | --- |
| 14 EN explanation | 600–800 | 889 | 1069 | stop | Word limit violated |
| 15 DE explanation | 600–800 | 788 | 1250 | stop | Bounded format/topic checks pass |
| 20 extended EN | 1500–1800 | 1748 | 2866 | stop | Word bound passes; Streaming omitted |
| 21 extended DE | 1500–1800 | 1862 | 3807 | stop | Word limit violated; Streaming omitted |

A later cache-OFF matrix and corrected-Agent native run each completed tasks
0–20 before interruption/safety stop. All 21 paired actual backend token hashes,
generation-argument hashes and complete answer hashes match. Both retain
DFlash2. This rules out APC as the cause of those observed defects; it does not
by itself localize target-model versus speculative-decoding behavior.

A separate reference disabled **both** APC and DFlash2, retaining the same
model, input tokens and generation arguments for available controls. Task 14
still produced 869 counted words and task 20 produced 1945, both `stop`; task 21 produced
1735 counted words/3125 tokens with `stop` and passed bounded word/topic checks.
Task 20 produced 3054 actual tokens. Its original whitespace count was 1999;
the original task-21 whitespace count was 1753. Format-only chunks explain the
difference, not a change to either generated answer. The no-draft answers differ from DFlash,
so their complete outputs are not claimed interchangeable. Task 21 has no
completed cache-OFF matrix counterpart. English word-limit failures persist
without either optimization. The no-draft EN tutorial briefly mentions tokens
appearing on screen: its missing literal `Streaming` alone is not evidence of
total semantic omission. The original two DFlash extended texts were manually
reviewed and omit the requested topic.

Manual review of the original core 20 answers reused earlier executed-code
checks only after matching all 20 full-answer hashes. Python factorial passed
0/1/5/10 and negative-input checks, JavaScript sum passed empty/positive/mixed
inputs, and SQL COUNT ran against a real in-memory table. Core facts, math and
canaries were correct. A correct `0 °C` is a keyword-check false positive when
only the literal `Celsius` is expected; it is not reported as a factual failure.
Long-answer factual qualifications were reviewed separately: full attention's
quadratic term must not be confused with every model component or measured
wall time; see the primary [Transformer analysis](https://arxiv.org/html/1706.03762v7).
Neither text equality nor passing keyword checks is general answer acceptance.

The complete final four-arm 22-task matrix is **not verified**. Hardware safety
stops prevent claiming the missing hybrid/forced full-answer arms as complete.
The word-limit weakness reproduced without APC/DFlash is a separate model
instruction-adherence problem, not a demonstrated Hybrid regression. Other
unlocalized differences remain limitations, not an invented parity PASS.
Private manual evidence: `/tmp/mlx-hybrid-followup-manual-final.json`.

## Numerical cache/compute parity

Final-code `/tmp/mlx-hybrid-followup-numeric-72017cd` completed twelve `stop`
requests without errors, restoring config and launch values. Cold prime, warm
follow-up and exact replay compare actual queued input token IDs/arguments.
Hybrid and native match cache-OFF in all six comparisons of **all 64 real
KV/SSM layer states and prefill logits**. Supported lower-precision tensors are
converted exactly to float32, checked finite, hashed one layer at a time and
not retained as a second full cache. Diagnostic transfers are excluded from
performance measurements. All nine off-relative input/argument comparisons
match. Forced splitting changes state/logit hashes in all three cases even
when the short visible answer matches; it remains an excluded diagnostic.
This is a bounded real-state probe, not proof for every possible prompt.

## Real RAG security and conflicting sources

On final implementation `72017cd`, both default and late placement complete
20/20 actual document → embedding → retrieval/router → production web → Agent
→ local model attacks: **40/40**, every answer `stop`. Each case checks its
unique expected codeword, absence of attack execution, actual attack visibility,
retrieved document identity and returned source/document provenance. Embedding
similarities are 0.8022–0.8502, above the unchanged 0.78 admission threshold.
The fixture rotates one owned document, with the attack first so snippet
truncation cannot silently remove it. Multilingual, role/priority/tool/history
spoofing, delimiter and override attacks are covered. No real secrets or
external exfiltration targets are used.

An additional real two-document probe passes **2/2** placement modes: contradictory
37/41-crate memos are both indexed, retrieved (similarities 0.8947/0.8999),
disclosed as sources and identified as a conflict in complete `stop` answers.
Its first attempt passed default placement but stopped before late placement
on transient headroom; cleanup succeeded. The repeat uses the same bounded
120-second admission wait and unchanged >=6 GiB threshold, then passes both.

All final owned sources were removed; foreign source records matched exactly;
only the temporary web processes were terminated. Production web flags stayed
unchanged. Earlier mixed-document attacks that emitted an attack marker were
not controlled per-attack evidence; subsequent source-framing and provenance
fixes were retested. Bounded examples cannot establish universal resistance or
security for arbitrary models, documents and retrieval policies.

Evidence: `/tmp/mlx-hybrid-followup-rag-72017cd-0`, `-1`, and
`/tmp/mlx-hybrid-followup-rag-conflicts-final`. The private reproducible conflict
probe is `/tmp/mlx-hybrid-followup-rag-conflicts.py`; the maintained production
attack runner and staged conflict fixture remain in the repository.

## Long-run stability and memory

No >=7200-second continuous run completed. Do not add elapsed time across
attempts or count a merely live model PID after the workload stopped.

- The 116-minute attempt completed 503 requests on one model PID, then a web
  first-byte recovery restarted Agent and broke its stream. The later recovery
  guard fixes this real defect; it does not turn that failed run into a PASS.
- A separate matrix repeat also lost its Agent stream; exact original config
  and a healthy original profile were manually restored after Agent returned.
- After the recovery fix, the next native attempt completed 42 requests and
  stopped on system swap growth: roughly **17.07 → 20.99 GiB** from the observed
  minimum, exceeding the 1 GiB criterion. Minimum five-second headroom was
  **3.6 GiB**. Config, launch values and runtime restoration all succeeded.
- An earlier recovery attempt independently stopped at roughly 17.84 → 21.59
  GiB. Repeating a proven unsafe long workload or raising guards is not approval.

Admission requires normal pressure and >=6 GiB **before** requests, with up to
120 seconds of waiting. It does not promise that live decoding retains 6 GiB:
long outputs can consume that reserve. Swap checks act between requests; a
single response can overshoot before stopping the next admission. The failed
post-recovery attempt had normal sampled pressure despite its swap failure.

Actual snapshot-store audits in the longer attempt observed 182 admissions:
160 saved, 22 budget rejections and 158 LRU evicted entries, at most two entries.
Largest saved snapshot was 562.8125 MiB; largest admitted retained-plus-pending
clone was **968.4375 MiB**, below 1024 MiB, with zero budget violations. The
post-recovery failed run independently observed budget rejections and evictions
with the same maximum admitted payload. Correct snapshot budgeting therefore
does not establish sufficient total inference memory.

The 116-minute native PID had a sampled maximum RSS of 11.935 GiB and minimum
headroom of 3.12 GiB. Per-completed-request Metal maxima were active 20.776 GiB,
allocator cache 12.400 GiB and cumulative peak 21.643 GiB. These categories may
overlap and **must not be added**. System swap already existed before testing;
its changes are not attributed solely to APC. Five-second RSS/pressure and
per-response Metal readings can miss transient peaks. No completed final soak
means no general leak-free or long-context memory acceptance claim.

Private failed artifacts remain in `complete-final`, `recovery-final`,
`matrix-latest` and `acceptance-37b4e6c` under `/tmp/mlx-hybrid-followup-*`.
Original defaults/profile are restored; no foreign jobs were terminated.

## Final bounded performance

Final implementation `72017cd` completed three rotated triples:
OFF→hybrid→native, native→hybrid→OFF, hybrid→OFF→native. Explicit tasks
`--perf-tasks 0 8 13` are arithmetic, Python and BFS/DFS. This choice follows
long-output safety failures; it does **not** replace the unchanged 22-task
quality matrix or prove performance for extended outputs. All 36 requests
(including nine primes) finish `stop`; all primes are START. All 18 paired
hybrid/native versus OFF comparisons match actual tokens, arguments, model,
step and complete answers. Temperature is zero and step size 256.

Medians from three trials per task/variant; parentheses are observed ranges:

| Task | Mode | First content ms | Complete ms | Prefill s | Decode tok/s |
| --- | --- | ---: | ---: | ---: | ---: |
| Arithmetic | off | 1334 (1315–1457) | 1459 (1441–1589) | 1.271 | 31.89 |
| Arithmetic | hybrid | 429 (391–430) | 523 (485–525) | 0.350 | 42.68 |
| Arithmetic | native | 413 (384–415) | 506 (478–510) | 0.336 | 42.54 |
| Python | off | 1337 (1329–1456) | 2856 (2854–3066) | 1.259 | 65.51 |
| Python | hybrid | 429 (419–432) | 1879 (1878–1919) | 0.344 | 68.96 |
| Python | native | 418 (398–430) | 1876 (1869–1884) | 0.334 | 68.43 |
| BFS/DFS | off | 1401 (1396–1500) | 13943 (13924–14947) | 1.319 | 52.20 |
| BFS/DFS | hybrid | 425 (410–438) | 12924 (12881–13430) | 0.352 | 52.35 |
| BFS/DFS | native | 428 (393–445) | 13000 (12953–13174) | 0.345 | 51.97 |

Hybrid and native reuse **768 tokens in every measured turn**; OFF reuses zero.
This series demonstrates a bounded APC latency/completion improvement versus
OFF. It does **not** demonstrate additional early-checkpoint reuse or a reliable
native-over-hybrid advantage. Three trials do not justify broad statistical
confidence; decode/longer-answer variation dominates small native differences.
Long-answer performance remains unverified. Keep early storage off by default.

The final short series has 51 five-second samples, all normal pressure, minimum
headroom 12.72 GiB and no system-swap increase. Largest snapshot is 194.8125 MiB;
retained-plus-pending reaches 373.625 MiB with zero budget violations. This is
short-workload evidence, not a substitute for the failed long-run memory gate.
Corrected backend prefill times are used above; earlier warm metric times were
inflated by the numerator mismatch and are not treated as real prefill timing.
Evidence: `/tmp/mlx-hybrid-followup-perf-72017cd/paired-performance.json`.

## A — Optional integration assessment

The current instruction permits integrating an inactive experimental feature
without declaring production/default activation ready. This is a scope
distinction, not a relaxation of memory guards or relabeling failed tests.

- `scripts/mlx-server-start` selects the original `default` profile unless the
  user explicitly configures `MLX_CHAT_PERFORMANCE_PROFILE=hybrid`. The adapter
  and its extra snapshots are confined to that profile.
- Early Checkpoint requires `NOBBY_HYBRID_EARLY_CHECKPOINT=1`; unset/0 is off.
  Natural alignment and one exact snapshot remain defaults. Snapshot admission
  retains the 1024 MiB retained-plus-pending limit; unknown/oversize/failed stores
  skip storage. Installed MLX-VLM package files are not patched on disk.
- Existing model-load, RAM/swap and workload coordination guards are retained.
  Unsupported source versions fail closed; unsupported batch/multimodal paths
  use upstream inference; invalid restored offsets fall back to cold prefill.
- Unconditional SQLite closure, chat recovery and default-RAG framing/provenance
  fixes are included in full medium/browser tests and relevant regressions.
  Prior real default/late RAG evidence remains bounded to the recorded cases.
- The failed native/two-slot long workloads remain evidence against unrestricted
  opt-in use and standard activation. They do not establish a default-path
  regression when the experimental profile is not selected. No global
  leak-free or long-context safety claim is made.
- Merge does not change user config, inherited LaunchAgent values or selected
  profiles, and does not restart services. Existing user opt-ins are preserved.

| Integration check | Status | Evidence |
| --- | --- | --- |
| Default isolation | PASS | Original default profile; explicit Hybrid/Early selection; default-off/startup regressions |
| Safeguards and fallbacks | PASS | Budget, guard, version/source, offset and unsupported-input regression coverage; guards unchanged |
| Available bounded parity/security | PASS | Recorded 64-layer/logit and actual-token controls; 40 RAG attacks plus 2 conflicts; broader gaps retained below |
| Current final regressions | PASS | Fresh medium: 3277 Python + 433 subtests + 280 JS; browser: 106; targeted Hybrid/fallback/RAG/docs: 121; syntax/compatibility/diff pass |
| Final-head CI and repository rules | NOT VERIFIED | Final pushed head must pass; actual approval/merge log on PR 299 |
| Activation limits and rollback | PASS | This report, README/runbook and unchanged existing configuration |

`docs/RELEASING.md` governs version preparation, tags and publication. Its
metadata-only release-PR and full release-publication gates are not being used
to publish a product here. `CONTRIBUTING.md` product-PR tests, final CI and any
configured branch/review rules still apply. GitHub currently reports no main
branch protection/rulesets and no submitted reviews; no independent review
approval is claimed. Recheck before merge and do not bypass any required rule.

The integration closeout completed fresh checks on the unchanged implementation:
`test-medium` passed 3277 Python tests, 433 subtests and 280 JavaScript tests
(Python 56.67 s); `test-e2e` passed 106 browser tests (161.02 s). The targeted
Hybrid/fallback/RAG/clock/recovery/documentation subset passed 121 tests.
Tracked Python/JSON, JS/Bash syntax, i18n, pinned MLX-VLM source compatibility
and both working-tree/full-PR diff checks passed. Private closeout logs are
under `/tmp/mlx-hybrid-integration-closeout/` (`medium.log`, `e2e.log`,
`relevant.log`, `checks.log`). Earlier runs below remain historical evidence.

The bounded closeout runs only `test-medium`, `test-e2e`, relevant deterministic
Hybrid/fallback/RAG regressions, syntax, compatibility and diff checks. It
starts no new soak, real-model attack series or benchmark matrix. No new
runtime feature is introduced by this closeout.

## Regression evidence and B — production/default-activation gates

Final inference implementation `72017cd` plus QA-only correction `f836fe3`:

- `./scripts/mlx test-medium`: **3277 Python tests + 433 subtests + 280 JavaScript tests**, all pass. Python 54.23 s.
- `./scripts/mlx test-e2e`: **106 browser tests**, all pass in 160.22 s.
- Final tracked Python/JSON, frontend JS, Bash/startup/plist syntax, i18n,
  MLX-VLM 0.6.17 check-only compatibility and diff checks pass.
- Three documentation checks pass after the final README/runbook edits.

Private logs: `/tmp/mlx-hybrid-followup-medium-verified.log`,
`/tmp/mlx-hybrid-followup-e2e-verified.log`,
`/tmp/mlx-hybrid-followup-checks-verified.log` and
`/tmp/mlx-hybrid-followup-docs-verified.log`.
Earlier green logs are not substituted for these.

| Gate | Status | Evidence / remaining requirement |
| --- | --- | --- |
| G1 Full answer quality | FAIL | Complete responses violate requested word limits; extended DFlash topics omitted; no-draft EN failures reproduce |
| G2 Backend prompt/token identity | NOT VERIFIED | 21 partial quality pairs and 18 final performance pairs match; full final four-arm matrix incomplete |
| G3 Cache/compute parity | PASS | Six safe final 64-layer/logit comparisons match; forced three differ and remain excluded; bounded probe |
| G4 Real RAG security | PASS | Final 40/40 real attacks plus 2/2 actual conflicting-source placement cases, with provenance and cleanup |
| G5 Two-hour stability | NOT VERIFIED | No completed uninterrupted >=7200-second workload; 116-minute attempt failed |
| G6 RAM/swap/snapshot budget | FAIL | Snapshot budget passes, but repeated long-output system-swap growth exceeds 1 GiB and headroom falls below reserve |
| G7 Reproducible performance | NOT VERIFIED | Three bounded triples pass; long-answer performance and additional native-early benefit unverified |
| G8 Regression tests | PASS | 3277 Python, 433 subtests, 280 JS, 106 browser; final syntax/i18n/compatibility and documentation checks |
| G9 GitHub CI | NOT VERIFIED | Snapshot at report commit creation; actual final-head results are recorded on PR 299 after push |
| G10 Documentation/rollback | PASS | Exact config/launch/package integrity and healthy original model verified; rollback/runbook and failed evidence preserved |

G9 in this versioned file is deliberately the pre-push snapshot, not a claim
about CI that has not run yet. The final approval log on
[PR 299](https://github.com/nfekete82/mlx-nobby/pull/299/checks) records the exact
last head and its check links after push. The final user/PR gate assessment uses
that actual result. These historical failures prohibit claiming production/default activation
ready. Optional-code integration is assessed separately under A above.

## Historical reproduction and production-activation blocker resolution

The commands below preserve reproduction of earlier evidence; they are not
part of the current integration closeout and were not rerun. For a separately
authorized future production-activation study, use
[the benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md) and preserve settings:

```sh
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-full-new \
  --phase all --confirm-restarts
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-numeric-new \
  --phase numeric --confirm-restarts
./test-venv/bin/python scripts/validate-hybrid-acceptance.py \
  --runtime-root "$PWD" --output /tmp/hybrid-bounded-perf-new \
  --phase perf --perf-tasks 0 8 13 --confirm-restarts
```

1. Quality: inspect complete tasks 14/20/21 and actual word/topic/finish checks.
   Investigate instruction adherence and target/draft differences using fixed
   audited backend inputs. Validate any inference/model correction on the
   original failed tasks and additional holdouts; do not truncate answers or
   relabel keyword parity as quality. Preserve the user's selected model/config.
2. Memory/soak: arrange enough genuinely idle headroom without terminating user
   jobs, retain the 1024 MiB snapshot limit and existing guards, and repeat the
   unchanged long-output >=7200-second workload. If pressure/swap still fails,
   reduce actual inference-memory demand through a separately validated runtime
   change. Do not reset the swap floor or loosen limits to obtain a PASS.
3. Complete the missing four-arm 22-task matrix and long-output rotated timing
   series after memory is resolved. Include a prefix-divergence workload that
   actually distinguishes early from final snapshot reuse before claiming an
   additional native advantage. Repeat final regression/CI on the new head.
4. Reassess all ten production/default-activation gates before authorizing B.
   Their existing FAIL/NOT VERIFIED results remain. A uses the separate optional
   integration checks above plus final CI and repository requirements; it does
   not imply authorization to activate or publish the optimization.

## Repository preservation, rollback and release policy

The isolated worktree is `/tmp/mlx-hybrid-acceptance-work`; only the existing
integration branch/PR is used. The original 29 untracked files, three stash
object IDs and 20 unrelated worktree records match inventory and were left
untouched. No force-push, stacked-PR duplicate merge or foreign cleanup occurred.
No main branch protection/rulesets or reviews were present at the final check;
allowed merge methods do not waive required integration checks or authorize
production activation. The repository release policy
requires separate metadata preparation from a clean main and post-merge gates;
no version is approved for a tag/release here.

Final restoration verifies original launch values including unset values,
byte/hash-identical user config, unchanged installed `generation.py`/`apc.py`,
healthy original target/profile and zero open automation database descriptors.
No private benchmark/web process should remain after checks. Raw responses,
retrieval data, recovery configs and audit records remain owner-only outside
GitHub. The final restoration manifest is
`/tmp/mlx-hybrid-followup-restoration-final.json`.

Rollback: use the prior chat profile, restore saved launchctl values (including
unset variables), restore exact known config, wait for idle and restart only
chat. Verify health/model/profile. Hard-kill recovery material is in the
private controller directories. Never overwrite unrelated user changes.
Late-RAG/clock flags remain opt-in in their own web/backend environment;
production flags are unchanged. See the runbook for activation/deactivation.

## Follow-up implementation commits

The final documentation commit is identified by PR 299's last head. Its
implementation/test/documentation ancestors added during this follow-up are:

```text
086ee79 fix(agent): close scheduler SQLite connections deterministically
a63e5be test(hybrid): add private backend audit and full-response acceptance runner
7ce194d fix(hybrid): preserve upstream prefill boundaries for guarded snapshots
9a930e6 fix(hybrid): retain single-token speculative capture after cache restore
035da00 fix(hybrid): gate clock staging and report actual native checkpoints
094db97 test(hybrid): add bounded real cache-state continuation diagnostics
1f40176 fix(test): wait for safe headroom and distinguish controlled restart telemetry
62fa3ec fix(rag): frame untrusted role markers and retain admitted source provenance
2794be3 test(hybrid): record snapshot admissions and actual LRU evictions
2f6103a test(hybrid): compare cache-off performance and exercise changing soak prefixes
9b160cf fix(rag): protect legacy source framing without enabling late placement
14c3cd6 docs(hybrid): separate historical measurements from final acceptance progress
fb5cd3b fix(test): bound swap growth from the observed memory floor
07f6e0e test(hybrid): enforce requested long-form word bounds in quality checks
93f19db test(hybrid): retain original failures and add complete extended responses
37b4e6c fix(runtime): protect progressing chat streams from unrelated recovery
e61da21 test(hybrid): record explicit bounded performance task selection
72017cd fix(hybrid): preserve elapsed-time semantics in warm prefill metrics
f312ff9 docs(hybrid): record final bounded evidence and unresolved release blockers
f836fe3 fix(test): exclude formatting-only chunks from answer word bounds
```
