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
- Pre-existing untracked files, stashes and unrelated worktrees are preserved.
  No installed package changes, dependency upgrades, main force-pushes, branch
  deletions or release-version changes are part of this integration.

## Selected implementation

The source-guarded in-memory adapter applies only to MLX-VLM 0.6.17,
DFlash2, exact APC, one text-only sequence and a semantic hash supplied by
upstream. Batches and multimodal requests keep the upstream speculative path.
A complete cloned cache state is restored only for matching tokens/hash.
The remaining prompt is prefetched and the upstream decoder is retained.
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
prefix, promotes hits and evicts least recently used entries. Two is a bounded
research capacity, not a demonstrated global optimum or a total-RAM limit.

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
   Tensor payload excludes allocator overhead, model weights and other
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
7. Replace telemetry-only release PASS with conservative checks for prompt
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

The preliminary hardware run also reproduced cold first-turn equality for
native versus baseline and divergence for forced splitting. That run overlapped
implementation work and is excluded from final performance evidence.

## Final hardware evidence

Hardware: Apple Silicon M5 Max, 48 GB unified memory; target Qwen3.8 27B
4-bit, configured DFlash2 draft; installed MLX-VLM 0.6.17. The server health,
hybrid adapter and explicit live prefill argument are checked by the runner.

The frozen-code series uses temperature 0, 700 maximum output tokens, three
German Apple-Silicon questions and baseline assistant-history replay. Three
four-arm comparisons at step 256 plus one comparison each at 512 and 1024
are scheduled. Private raw answers and reports stay outside the repository.
Client request equality and exact answer comparison are recorded per turn.
A hardware timing table will be filled only from completed reports.

**Final-series measurements: PENDING.**

This series uses a proven hybrid baseline without early checkpoints, not
cache OFF. It does not establish backend token identity, broad prompt quality,
peak RSS or a long-lived no-restart soak. Browser first-content latency includes
web/Agent overhead. Reliable generated-token throughput is NOT VERIFIED;
character counts are not token counts.

## Test evidence

- `./scripts/mlx test-medium`: 3244 Python tests and 433 subtests passed;
  280 JavaScript tests passed. One existing Starlette/httpx deprecation warning.
- `./scripts/mlx test-e2e`: 106 browser tests passed on the integration branch.
- Targeted Hybrid/APC/DFlash2, benchmark, RAG, clock, prompt-stage, fallback,
  memory-admission and release-gate suite: 72 tests passed after final changes.
- MLX-VLM 0.6.17 source compatibility: PASS with Metal access.
- Python syntax, Bash syntax and diff whitespace checks: PASS.
- Sandbox-only first attempts failed due to unavailable Metal/local sockets;
  they were not counted as passes. Host-access reruns supplied the results above.

The final complete suite is repeated after freezing the code. Counts above
are current-run results, not the historical counts supplied in the task.
Browser tests use fixtures; passing them is not real-model RAG certification.

## Release decision and remaining gates

**HOLD.** No production-readiness claim, main merge, version bump or tag.
[RELEASING.md](RELEASING.md) requires green final-main acceptance and CI before
tagging and keeps product logic separate from metadata-only release PRs.

Required evidence before promotion:

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
