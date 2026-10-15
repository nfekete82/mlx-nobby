# Shared runtime lease diagnostics

`runtime_coordinator.runtime_lease` instruments the shared process RLock and
cross-process flock. Chat (including the OpenAI gateway), Agent/Coding, image and
video callers all pass through that function. The provider labels its actual
requested role with a scoped context variable; nested role resolution preserves
the outer owner. Speech and embeddings retain their existing independent model
locks and fresh memory admission checks; diagnostics do not introduce heavy-runtime
serialization for those services.

`lease_state_snapshot()` reads current metadata without invoking memory probes.
`runtime_state_snapshot()` adds the existing diagnostic memory snapshot and the
latest 128 completed lease records across observed processes. Existing snapshot
fields remain available. The performance observatory's runtime snapshot exposes
these additive fields.

Current records contain PID/thread, allowlisted workload, request/acquisition
timestamps, elapsed age and acquisition wait. Recent records contain release time,
monotonic wait/hold durations and `completed`, `cancelled`, `timeout` or `error`
outcomes. `waits_by_workload` aggregates sample counts, total/max waits and outcomes
over this recent window; these are not lifetime counters. Storage is a rolling
128-entry file per process under the coordinator state directory's `history/`
subdirectory. Old process files remain local; no user-data cleanup is performed.

A contending caller reports a workload only when it actually reads an active
central owner record. A short release transition does not erase the last observed
owner. Missing ownership evidence remains `unknown`; an acquisition which never
encountered a held lock reports `none`. This describes an observation during the
wait, not proof that one owner caused the entire wait. PIDs/threads identify local
execution, never users or prompt contents. Arbitrary workload strings are normalized
to `unknown`; history and report fields are allowlisted.

Acquisition remains unbounded by default. An explicit finite, nonnegative
`timeout` limits acquisition; it does not interrupt an executing owner. Cancellation
is checked before acquisition and during waits, including nested calls. Provider
model-lock waits also poll cancellation and release the outer lease. All errors
unwind through the existing context managers. Telemetry I/O failures do not prevent
release. Diagnostic writes are best effort, not a durable billing/audit ledger.

Automatic chat recovery refuses to restart a process with active Agent execution,
including tool work between model calls, or another observed runtime workload.
The web watchdog gives that contention the existing extended runtime-wait budget.
An explicit forced recovery retains its existing semantics. No scheduling priority,
model admission limit, reserve or tool permission is changed.

Regression suites: `test_central_lease_diagnostics.py`,
`test_provider_central_lease.py`, `test_runtime_lock_order.py`,
`test_runtime_reliability.py`, `test_runtime_budget.py` and `test_model_provider.py`.

## Bounded image-admission settling after real model release

Image jobs still use the hard 90% projected unified-memory ceiling and their
existing image load reserve (18 GB by default). When the image handoff has
**actually** unloaded an idle speech/MuseTalk runtime or stopped the chat
server, macOS can take a short time to account for reclaimed pages.

Only when that first post-release memory snapshot would block image admission,
the coordinator waits at most three one-second intervals and takes a **fresh**
memory sample after each. There are no retries without an actual release, no
changes to the 90% hard limit or model reserve, and no inference starts until
the latest snapshot independently clears the original admission check.
Cancellation remains active; a persistently unsafe reading still rejects
the job. `preflight.memory_settle_attempts` records the number of resamples.

The same bounded settling applies when handing **image to video**. The video
coordinator first unloads an idle image model if required, and then frees optional
speech/MuseTalk or chat weights if needed. Only after a confirmed release, and only
if a fresh video-reserve projection would still exceed the 90% ceiling, up to
three one-second fresh samples are allowed. Video's 20 GB default reserve and
the 90% hard cap are unchanged. `preflight.memory_settle_attempts` captures
the same field for image and video. A permanently unsafe or cancellation state
still prevents loading.

This targets transient failures before media model loading after a real
handoff, not general low-memory failures. Unit regression tests cover both
directions, permanent rejection, and zero retries without reclamation.
Apple Silicon real acceptance (`./scripts/mlx test-real`) remains mandatory
before an official release is tagged.
