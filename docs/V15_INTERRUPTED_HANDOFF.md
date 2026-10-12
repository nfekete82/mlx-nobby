# V15 handoff — 2026-10-11

This note captures the interrupted Codex session without claiming a release.

## What is already reported
- Structured, anchored source evidence, limited model-based extraction/verification, and a deterministic quotation path have been implemented.
- Search failures are classified; repeated lookup outputs have bounded per-run reuse.
- The most recent **reported local** full run: 2,296 Python tests and 422 subtests; 242 JavaScript tests; 78 browser tests; Docker validation passed. These are not fresh CI attestations for any later local edits.
- Earlier CI checks were reported green for a measured intermediate commit.
- The archived V14 comparison contained 25 attempts. The V15 comparison was interrupted after 19 of 25 sequential attempts; parallel tests and the 64-case quality benchmark were not confirmed complete.

## Known open acceptance issues
1. An Apple availability date can be dropped by the legacy numeric evidence gate when the year is only in the document context.
2. Raspberry Pi prices were matched to variants but were not labelled clearly as **historical launch prices**.
3. Extraction and verification calls have been observed to add about 44.6 s for one NASA example; the 45 s median target is not established.
4. Source-backed quotations do not independently prove semantic truth, product availability, or completeness.
5. Live search provider conditions changed between cohorts. Timing comparisons require explicit environment and workload annotations.
6. A paused local Codex session displayed **seven edited, potentially uncommitted files**. They must be inspected and preserved before any checkout, pull, reset, rebase, or remote edits.

## Safe continuation
1. Inspect `git status --short`, `git diff --stat`, `git log -1 --oneline` and check whether local modifications are already committed remotely. Preserve any remaining changes in a separate WIP branch/commit without including secrets or benchmark raw captures.
2. Finish the remaining sequential V15 attempts and the parallel Apple cohort *using the identical frozen implementation*, then run the 64-case quality evaluation. Retain failed attempts.
3. Inspect full answers for Apple, Apple Duo, Raspberry Pi, NASA, and no-evidence prompts. Judge correctness and usefulness separately from transport success.
4. Fix time-context preservation and historical-price labelling using independently sourced fixtures. Re-run targeted and complete tests.
5. Recheck the actual final GitHub CI commit. Include hardware/lease/background-load conditions in the final benchmark report.
6. Produce `docs/V15_FINAL_RELEASE_REPORT.md` with explicit PASS/FAIL per release criterion. Do not mark ready or merge while evidence/quality/performance acceptance is incomplete.

This file is a handoff checklist, not evidence that these tasks have passed.
