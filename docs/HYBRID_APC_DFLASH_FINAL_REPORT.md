# Hybrid APC + DFlash2 integration and benchmark report

Date: 2026-10-19. Status: **experimental integration candidate; NOT RELEASED**.
The optimization remains opt-in. Do not merge or enable it as a proven faster,
equivalent generation path while the acceptance blockers below remain open.

## Repository and integration

- Repository: `nfekete82/mlx-nobby`.
- Verified remote main at inventory: `b97c1f6b0001032f42ce22b347111a7cfa78b61f`.
- Original local branch: `experiment/hybrid-native-prefill-boundary`,
  `14c585a`. Only pre-existing untracked user reports/captures were present.
- Integration branch: `integration/hybrid-apc-dflash-final`, starting at
  `892bb2b3baa9cdff1b660c8f8284f728ae3d49cb` from
  `origin/experiment/hybrid-native-prefill-256-ab`.
- PRs [283](https://github.com/nfekete82/mlx-nobby/pull/283) through
  [298](https://github.com/nfekete82/mlx-nobby/pull/298), including RC
  [292](https://github.com/nfekete82/mlx-nobby/pull/292), were open at inventory.
  Their changes form a stack already inherited by this branch. No individual
  PR was merged or cherry-picked again. The final draft is an alternative
  integration vehicle, not approval to merge the stack separately.
- Implementation commit: `6a16fa0`; final configuration guards: `ffed119`.
  Draft integration PR
  [299](https://github.com/nfekete82/mlx-nobby/pull/299).
- Pre-existing untracked files, stashes and unrelated worktrees are preserved.
  No installed package changes, dependency upgrades, main force-pushes, branch
  deletions or release-version changes are part of this integration.

## Selected implementation

The source-guarded in-memory adapter applies only to MLX-VLM 0.6.17,
DFlash2, exact APC, one text-only sequence and a semantic hash supplied by
upstream. Batches and multimodal requests keep the upstream speculative path.
A complete cloned cache state is restored only for matching tokens/hash.
The remaining prompt is prefilled and the upstream decoder is retained.
Recurrent SSM state is never reconstructed from KV slices.

The profile remains explicit and experimental. One exact entry and no early
checkpoint remain the defaults. If explicitly enabled, the early checkpoint
now defaults to an existing baseline hybrid prefill boundary. Forced splitting
requires explicit `NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE=0` and is retained
as a diagnostic control. Natural alignment refers to the existing **hybrid**
prefill loop, not proof of equivalence to the unmodified cache-OFF path.
Different step sizes can themselves change numerical computation.

Two slots can retain an early and a final checkpoint, unlike one slot where
the later store evicts the earlier one. The manager chooses the longest exact
prefix, promotes hits and evicts least recently used entries. Two is sufficient for the observed three-turn early+final workload and is a
bounded research capacity, not a demonstrated global optimum or a total-RAM
limit. A one-slot policy favoring only early snapshots could reduce retained
memory but would sacrifice the longer immediate-replay snapshot; it is not
promoted without a separate workload comparison. Increasing capacity beyond
two is neither required by these measurements nor enabled by the launcher.

### Corrections in this integration

1. Limit exact lookup to the current guarded checkpoint. Reject invalid
   offsets, offsets beyond the guard and missing/mismatched layer lists before
   touching cold inputs; lookup errors continue with cold hybrid prefill.
2. Admit snapshot storage only when existing exact tensor payload plus the
   pending clone fits a bounded budget. Default: 1024 MiB; allowed: 64–8192.
   Unknown layouts and store failures skip storage while inference continues.
   Count states under the manager's lock. The single upstream generation
   worker serializes cache mutation; the budget does not introduce a new
   concurrent store path.
3. Log numeric snapshot payload sizes. Upstream `resident_bytes()` sums block
   pool bytes and **omits exact snapshots**, so it cannot establish their RAM
   cost. Conservative admission can skip a replacement that would fit after
   eviction; this deliberately favors memory safety over cache availability.
   Tensor payload excludes the active inference cache, allocator overhead, model weights and other
   services; measure process/Metal/system memory separately.
4. Require the prefill metric source anchor as well as version/source-layout
   guards. Installed MLX-VLM files remain untouched.
5. Hash full outbound client requests before history mutation, and full
   generated answers. Compare all turns, including cache-hit responses.
   These hashes establish client input equality only, not backend enrichment
   or tokenized prompt equality.
6. Validate idle state/live hybrid profile, freeze source hashes for a run,
   check the actual server's prefill step on port 8000, control experiment
   flags and restore originally unset values. Cleanup failure is an error.
   Forced A/B answer capture replays each OFF history into its ON pair.
7. Reject ambiguous alignment flags rather than silently choosing forced
   chunks. Reject non-ASCII and oversized prefill values before shell arithmetic
   or overwriting launch settings. These final invalid-configuration guards were
   added after the frozen series; the measured valid 0/1 and 256/512/1024 paths
   are unchanged. The direct soak uses the final guarded implementation (`ffed119`).
8. Replace telemetry-only release PASS with conservative checks for prompt
   equality, answer parity, cold first turns, repeated latency improvement,
   finite memory metrics and within-run swap. Additional backend/config,
   long-session and RAG/trust review evidence is mandatory.

## Correctness findings

The CPU execution regression runs the actual injected prefill segment with
a stateful cache model. For checkpoint 986, restored prefix 324 and step 256:

| Mode | Forward chunk lengths | Stored state offsets |
| --- | --- | --- |
| no early snapshot | 256, 256, 150 | 986 |
| native early snapshot | 256, 256, 150 | 580, 986 |
| forced early snapshot | 256, 246, 160 | 826, 986 |

Native storage adds no forward pass and snapshots only actual computed state.
Forced storage changes the arithmetic segmentation. This explains why a cold
first response can change even though no cache was restored. Snapshot cloning
is a separate hypothesis tested with the split-only diagnostic. CPU structural
checks cannot prove the numerical quality of real SSM/KV states.

A final real **split-only cold control** used the exact same client request
hash and 256-token step as the first baseline prompt, with forced alignment
and early storage disabled (`EARLY_CHECKPOINT=1`, `ALIGN_NATIVE=0`, `STORE=0`).
It logged one prefill, zero exact hits, zero matched tokens and one ordinary
final store. The early 164-token split was logged, with no early snapshot
store. Its captured answer was exactly equal to the forced-early answer and
unequal to baseline2. This directly reproduces the cold divergence **without
an additional early clone**: the forced split alone is sufficient for this
prompt. All temporary settings and the config hash were restored.

This closes the sampled cold-answer causal question; it does not certify
uncapped answer quality, all warm-cache numerical paths or general RAG safety.

The preliminary hardware run also reproduced cold first-turn equality for
native versus baseline and divergence for forced splitting. That run overlapped
implementation work and is excluded from final performance evidence.

## Final hardware evidence

Hardware verified with sysctl: Apple M5 Max, 48 GiB unified memory
(51,539,607,552 bytes); target Qwen3.8 27B
4-bit, configured DFlash2 draft; installed MLX-VLM 0.6.17. The server health,
hybrid adapter and explicit live prefill argument are checked by the runner.

The frozen-code series at implementation commit `6a16fa0` uses temperature 0, 700 maximum output tokens, three
German Apple-Silicon questions and baseline assistant-history replay. Three
four-arm comparisons at step 256 plus one comparison each at 512 and 1024
were completed. Private raw answers and reports stay outside the repository.
Client request equality and exact answer comparison are recorded per turn.
A hardware timing table will be filled only from completed reports.

Within each trial, all arms replay that trial's baseline. Across different
prefill steps, the baseline is regenerated, so assistant histories can differ;
the 512/1024 trials are exploratory rather than identical-history cross-step
performance comparisons. Arm order is fixed, not randomized.

One 256-step forced-split arm produced an extra `router.classify` model call
within the same chat trace, four stores and a changed final prompt length at
turn 2. This is a browser-pipeline control failure, not evidence that identical
client inputs imply identical model inputs. Its timings/cache deltas are
excluded from controlled performance claims. Router work and global memory
also affect otherwise valid browser latency measurements.

### Step 256: three completed four-arm trials

All three trials used the same 340 / 946 / 1392-token chat prompts in the
uncontaminated baseline/native streams. Every client request hash matched
within its trial. Native and baseline2 server argument hashes matched in all
three trials; source files were frozen and checked within every run.

| Arm | Third-turn cached tokens | Third-turn first content, median | Third-turn total, median | Answer parity versus baseline2 |
| --- | ---: | ---: | ---: | --- |
| baseline1, one slot | 0 / 0 / 0 | 1978 ms | 18130 ms | turns 1–2 equal; cold turn 3 differs |
| baseline2, two slots | 324 / 324 / 324 | 1660 ms | 17710 ms | reference |
| native2, two slots | 580 / 580 / 580 | 1346 ms | 17838 ms | **9/9 answers exactly equal** |

| Pair | baseline2 first content / total | native2 first content / total |
| --- | ---: | ---: |
| 1 | 1623 / 17419 ms | 1339 / 17097 ms |
| 2 | 1660 / 17710 ms | 1346 / 17838 ms |
| 3 | 1749 / 18253 ms | 1413 / 18230 ms |

Native's paired third-turn first-content improvements were 17.50%, 18.92%
and 19.21%. The median latency decreases 18.92%; median total duration instead
increases 0.72%. This demonstrates a sampled first-content improvement, not
an overall throughput or completion-time improvement. Three short, fixed-order
trials do not establish broad production behavior.

Forced early storage changed the cold first answer in **3/3 trials**, while
native matched the reference cold answer in **3/3**. The uncontaminated forced
trials reused 770 tokens, rather than the historical 826: this trial's second
checkpoint is 930, and 930 minus the diagnostic 160-token margin is 770. The
contaminated forced trial instead reported 815 reused tokens and is excluded.
With the actual cold checkpoint 324, the forced split creates 164/160-token
chunks instead of baseline 256/68; native creates no early boundary there.
The answer divergence therefore follows changed prefill computation, not a
previous cache hit. On the sampled warm path, offset 580 is already an
existing 324+256 boundary; restored suffix chunks retain the baseline cadence.

The conservative paired report gate returns **REVIEW**, with 3 OFF / 3 ON
runs, third-turn native hit rate 1.0 and median post-run global swap difference
0.07 GiB. Backend/token identity, complete compute-configuration review,
long-session memory acceptance and RAG/trust review remain unverified by that
report. The gate's OFF/ON names here denote baseline2/native2, not cache OFF.

### Step 512 and 1024: one exploratory trial each

| Step | Arm | Turn-3 reused tokens | First content | Total | Captured parity vs baseline2 |
| --- | --- | ---: | ---: | ---: | --- |
| 512 | baseline1 | 0 | 2188 ms | 18365 ms | 2/3 |
| 512 | baseline2 | 324 | 1818 ms | 18191 ms | 3/3 |
| 512 | early2 | 826 | 1239 ms | 17656 ms | 0/3 |
| 512 | native2 | 324 | 1922 ms | 18410 ms | 3/3 |
| 1024 | baseline1 | 0 | 2141 ms | 18456 ms | 2/3 |
| 1024 | baseline2 | 324 | 1779 ms | 18727 ms | 3/3 |
| 1024 | early2 | 826 | 1172 ms | 18138 ms | 0/3 |
| 1024 | native2 | 324 | 1814 ms | 18904 ms | 3/3 |

Native remains exactly equal to baseline2 for all three captured turns in
both controls. It adds no third-turn cache reuse and no observed latency
benefit here. Together with the three 256 trials, native equals baseline2 in
**15/15 bounded response captures**; forced splitting changes the cold first
response in **5/5** trials. Across steps the generated baseline histories differ,
so these are not clean identical-history comparisons of step size itself.
The adaptive production step is unchanged, and no global 256-step recommendation
is justified by these short trials.

### Snapshot memory and LRU observations

Across the completed series, 84 numeric snapshot admissions and 84 LRU
observations were captured. Maximum single snapshot state payload: 250.125 MiB;
maximum retained exact payload before a store: 490.25 MiB; maximum sum of retained
state plus incoming snapshot: **678 MiB**, under the configured 1024 MiB budget.
No observed budget or entry-capacity violation; maximum exact occupancy: **2**.
These are state-tensor payload measurements, not total RSS or Metal peak memory.
Exact-LRU eviction counts are not exposed by the upstream pool eviction counter.

### Final guarded-code direct Agent soak and fallback

Use the existing `validate-hybrid-correctness.py` synthetic-turn generator and
`benchmark-chat-experience.py` protected `agent_stream` helper. This diagnostic
bypasses browser intent routing while retaining Agent runtime admission/locks.
It used native alignment, two slots, step 256, a 1024 MiB snapshot budget,
temperature zero and 32 output tokens. No profile/config-file edits.

Thirty-three requests ran without an intervening server restart, spanning
three synthetic contexts. Actual backend completion counts were correlated in
request order (35 completions including the later fallback phase):

| Nominal context | Actual prompt-token range over 11 turns | Codeword checks | Exact hits | Stores |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 1855–2203 | 11/11 | 10 | 12 |
| 4000 | 7168–7516 | 11/11 | 0 | 0 |
| 8000 | 14248–14596 | 11/11 | 0 | 0 |

The larger cases correctly skip snapshots: retained smaller-context states
plus the requested clone exceed the 1 GiB budget. The conservative strategy
does not evict those old states speculatively, so it loses cache acceleration
on these larger contexts. This is a measured performance limitation, not proof
that increasing memory/entry limits would be safe or beneficial. Capacity
remains bounded, and generation continues with ordinary cold hybrid prefill.

After that uninterrupted segment, the server was restarted with a **64 MiB**
budget. Both additional synthetic checks passed with **zero stores and zero
hits**, verifying actual budget rejection/fallback on hardware. All 35 checks
passed; real backend outputs were 2 or 4 tokens, below the 32-token cap.
These are complete one-word memory checks, not general factual-quality review.

The full diagnostic, including setup, budget transition and final restoration,
took 413.49 seconds. There were 345 memory samples, no sampler errors and only
normal pressure readings. Peak sampled process RSS: **13.534 GiB**. Kernel
swap was **17.360 → 17.239 GiB**, with no observed increase above the initial
sample. Swap was already allocated before testing; these shared-system values
must not be attributed solely to APC. Process RSS is not a total unified/Metal
memory measurement, and 1-second sampling is not an instantaneous peak proof.

Original launch settings and the exact config-file hash were restored, with
no cleanup errors. The five four-arm trials separately verified restoration
and unchanged installed `generation.py`/`apc.py` source hashes after every run.
The short synthetic soak does not replace hours-long mixed-workload acceptance
or real RAG/prompt-injection review.

This series uses a proven hybrid baseline without early checkpoints, not
cache OFF. It does not establish backend token identity, broad prompt quality,
peak RSS or a long-lived no-restart soak. Browser first-content latency includes
web/Agent overhead. The browser runner itself does not expose reliable generated-token usage.
For the completed third turns, backend `Request completed` logs were joined
to private capture file completion times and exact prompt-token counts. Each
join was unique within one second and differed by only 5.8–10.8 ms for the
256-step trials. These logs report **700 generated tokens, finish_reason=length**
for every third response, including identical native/baseline2 captures.
Median backend decode rates: baseline1 43.3, baseline2 43.6, native2 42.4 tok/s.
These are actual backend counts/rates, not estimates from character length.
The rate difference and fixed arm order do not establish a causal decode effect.

The 700-token cap means response completeness is **NOT VERIFIED**, even when
captured strings match exactly. A full-answer semantic quality pass cannot be
inferred from equality of these bounded outputs.

## Test evidence

- `./scripts/mlx test-medium`: 3255 Python tests and 433 subtests passed;
  280 JavaScript tests passed. One existing Starlette/httpx deprecation warning.
- `./scripts/mlx test-e2e`: 106 browser tests passed on the integration branch.
- Targeted Hybrid/APC/DFlash2, benchmark, RAG, clock, prompt-stage, fallback,
  memory-admission and release-gate suite: 83 tests passed after final changes.
- MLX-VLM 0.6.17 source compatibility: PASS with Metal access.
- All tracked Python files compiled; shell and frontend JavaScript syntax,
  i18n audit and diff whitespace checks: PASS.
- Initial commit CI: macOS tests and Docker validation PASS. Browser CI failed
  in the unchanged English read-aloud/session-refresh test (5 passed, 1 failed
  before stop). All four variants of that test then passed locally. No frontend
  or browser-test source differs from main; the CI failure is recorded rather
  than ignored or repaired with unrelated UI changes.
- Sandbox-only first attempts failed due to unavailable Metal/local sockets;
  they were not counted as passes. Host-access reruns supplied the results above.

The final complete suite passed again after the last configuration guards. Counts above
are current-run results, not the historical counts supplied in the task.
Browser tests use fixtures; passing them is not real-model RAG certification.

## Release decision and remaining gates

**HOLD.** No production-readiness claim, main merge, version bump or tag.
[RELEASING.md](RELEASING.md) requires green final-main acceptance and CI before
tagging and keeps product logic separate from metadata-only release PRs.
Final-commit CI and reviews are tracked on [PR 299](https://github.com/nfekete82/mlx-nobby/pull/299); green CI alone does not clear the evidence hold.

Required evidence before promotion:

- Complete uncapped/adequately sized answer-quality checks; every measured
  third answer reached the 700-token limit.
- Resolve any response divergence under genuinely identical backend/tokenized
  prompts and equal compute configuration; inspect factual quality on real hits.
- Demonstrate repeatable latency improvement in at least three controlled
  pairs for the selected variant. Hits alone and answer lengths do not qualify.
- Complete no-restart, mixed-prompt and long-history sessions with peak
  process/Metal memory, pressure, swap and exact-LRU eviction observations.
- Validate deployed RAG/system-prompt stability and adversarial retrieved
  content. Late RAG remains opt-in; a textual delimiter is not proof of
  prompt-injection resistance. Preserve trusted policy separately from data.
- Verify cache-OFF equivalence separately. A native early snapshot preserving
  hybrid call boundaries does not remove the baseline hybrid guard split.
- Obtain required review/branch-protection approvals and green final-commit CI.

## Documentation and rollback

[README](../README.md) explains activation, prerequisites, memory and limits.
The [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md) is the current source
for reproducible commands, flags, privacy and restoration. Earlier checkpoint,
parity, RC, RAG and prefix-diagnosis documents are marked historical and retain
only their scoped observations. Unreleased notes are in [CHANGELOG](../CHANGELOG.md).

Switch back to the previously configured profile (for example
`./scripts/mlx chat-profile dflash`), restore experiment variables and restart.
Check `chat-profile status`, server health, live prefill arguments and the
launchctl values. No package reinstall is required. Benchmark controllers
restore their own changes; hard termination requires manual verification.
