# Hybrid APC + DFlash2 final acceptance

Date: 2026-10-19. Status: **IN PROGRESS — NOT RELEASED**.
PR [299](https://github.com/nfekete82/mlx-nobby/pull/299) remains Draft.
No merge, version change, tag or GitHub Release is authorized until all gates
below have actual final-code evidence.

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

Retrieved source strings are JSON-framed and angle-escaped in both default
and opt-in late placement. Fake chat roles and closing data delimiters cannot
become raw template markers. Trusted policy distinguishes source data from
instructions. Every source actually admitted to the answer context remains
attributable: the old stricter display-only threshold silently hid used sources.
This framing is not a universal prompt-injection guarantee. Experimental clock
omission now requires `NOBBY_CLOCK_CONTEXT_STABLE=1`; current time remains the
default. Native APC flags and web/backend flags are separate environments.

## Evidence collected in this follow-up

Historical capped measurements and earlier CI are archived in
[initial evidence](HYBRID_APC_DFLASH_INITIAL_EVIDENCE.md). Their 580/324-token
comparison predates the final checkpoint corrections and is not a measurement
of the current implementation. The current runbook is
[the benchmark procedure](HYBRID_APC_DFLASH_BENCHMARK.md).

### Numerical control

A completed preflight compared a cold prime, warm follow-up and exact replay
with actual queued token-ID and generation-argument hashes. Hybrid and native
matched cache-OFF for all six comparisons of all 64 real KV/SSM layer states
and prefill logits. Forced splitting differed in all three state/logit cases,
even where the short visible answer stayed the same. Conversion from supported
lower precision floats to float32 is exact; tensors are processed one layer at
a time, without retaining another entire cache. These transfers are excluded
from performance claims. A final-code numerical repeat remains scheduled.

### RAG security

An initial mixed-document end-to-end probe returned an attack marker, but did
not identify which source caused it. It is not a controlled per-attack result.
Framing was hardened and the fixture now rotates exactly one document, uses a
unique synthetic expected codeword per case, verifies real embedding retrieval,
checks that the attack survives snippet truncation, and requires source provenance.
No real secrets, external targets or foreign source modifications are used.

The controlled late-placement preflight completed 20/20 actual document ->
embedding -> router -> production web -> Agent -> local model cases, with all
expected codewords, no attack markers and all expected sources returned.
Similarities were 0.8022–0.8503, above the unchanged 0.78 context threshold.
Its uniquely owned source was removed; foreign source records matched exactly.
The final shared framing helper is being checked in both placement modes.
Coverage includes role spoofing, override commands, multilingual instructions,
false history, fake tool outputs, priority claims and closing-delimiter attacks.
Bounded examples do not establish safety for arbitrary documents/models.

### Full quality, long run and performance

Pending completion of the frozen final-code run. Twenty fixed tasks cover
arithmetic, facts, DE/EN, coding, planning, long explanations, known conversation
history, long context and staged RAG facts/conflicts. Target allowances are
4096 tokens (at least 2048 for primes/numerical checks). Only actual `stop`
responses count as complete; `length` is never a completeness PASS.

A native uninterrupted >=7200-second workload will record normal-pressure/
headroom admission, five-second RSS/kernel-swap samples, per-response Metal
memory, real snapshot sizes, LRU occupancy/evictions, actual finish reasons,
prefill/decode metrics and full private answers. Admission waits up to 120
seconds while retaining >=6 GiB headroom and <=1 GiB swap growth. Wait time
is reported separately from post-admission response timing.

Prior attempts stopped conservatively on transient headroom below 6 GiB;
those are not two-hour PASS results. A deliberately interrupted early matrix
also exposed a cleanup timing race: cleanup now waits for its request to finish
before restarting, and exact original settings were manually verified/restored.
No failed/interrupted run is silently relabeled as a successful run.

Three final performance pairs include cache-OFF, hybrid without early storage
and native storage, with rotated arm order and identical backend inputs.
First content and complete response duration are assessed separately.

## Release gates

Only PASS, FAIL or NOT VERIFIED are used. Pending work is NOT VERIFIED.

| Gate | Status | Required final evidence |
| --- | --- | --- |
| G1 Full answer quality | NOT VERIFIED | 20-task full-output final comparison and review |
| G2 Backend prompt/token identity | NOT VERIFIED | Actual backend token/argument hashes in final matrix |
| G3 Cache/compute parity | NOT VERIFIED | Final numerical repeat and full-response comparison |
| G4 Real RAG security | NOT VERIFIED | Controlled final default + late model series and trust review |
| G5 Two-hour stability | NOT VERIFIED | >=7200 seconds, same native server PID, no restart |
| G6 RAM/swap/snapshot budget | NOT VERIFIED | Final continuous samples and actual cache-store audit |
| G7 Reproducible performance | NOT VERIFIED | Three controlled rotated pairs, complete answer evidence |
| G8 Regression tests | NOT VERIFIED | Final code medium/E2E/syntax/i18n/compatibility |
| G9 GitHub CI | NOT VERIFIED | Required jobs on the actual final PR head |
| G10 Documentation/rollback | NOT VERIFIED | Final report, runbook and verified restoration |

## Repository, artifacts and rollback

Work proceeds on the existing integration branch through an isolated worktree;
all pre-existing untracked files, stashes and unrelated worktrees are preserved.
Remote main was `b97c1f6b0001032f42ce22b347111a7cfa78b61f` at inventory.
No branch protection/rulesets were configured, but that does not waive gates.
No duplicate integration of stacked PRs 283–298 is performed.

Private artifact families under `/tmp/mlx-hybrid-followup-*` contain 0600
reports/answers in 0700 directories. Nothing containing raw answers or user
configuration is committed or pushed. The controller records source hashes,
including installed generation/APC sources, and stops on drift. Original
config and installed sources still matched the earlier inventory manifest.

Runbooks describe flags and activation. Roll back to the prior chat profile,
restore tracked launchctl values (including originally unset values), restart
only idle chat and verify health/profile/model. The controllers restore exact
config text and compare launch settings. Hard-kill recovery uses the private
`original-config`/initial-state files; never restore foreign changes blindly.
RAG acceptance removes only its uniquely identified test source and terminates
only its temporary web process. Production web flags remain unchanged.

Current version: 1.19.0. No version/tag/release is part of this product PR.
