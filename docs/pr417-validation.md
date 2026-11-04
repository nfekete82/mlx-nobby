# PR #417 review and validation — 2026-11-04

Starting revision: `51987c7cb63139415a117a9057c40a67985fe050`.
The current main (`ad0dd782`) was integrated in the dedicated PR worktree;
the existing production/main checkout was not modified during development.

## Findings corrected

- The personal-memory checkbox registered a DOM label as its change handler;
  the real UI could not opt in. A behavioral Node DOM test now catches this.
- Opt-out racing extraction could repopulate disabled private storage. Writers
  and readers recheck opt-in while holding the store lock.
- Fact editing discarded chat/message provenance. Renaming an attribute then
  deleting it left old sensitive revisions behind. Source metadata and a
  migrated revision lineage now survive edits; deletion purges the whole chain.
- Generic confirmations could resolve a question from an unrelated chat.
  Source chat identity is preserved through frontend, reliable-stream request,
  web forwarding and Agent middleware; confirmation is scoped to that chat.
- Newest-first chat backfills established newer statements before older ones.
  Backfills now process source timestamps in ascending order and retain a
  proposed conflicting value for review.
- Exclusion removed searchable archive results but left deleted words in FTS5
  posting lists. Exclusion/chat deletion rebuilds and compacts the derived index;
  a synthetic byte-level regression verifies the deleted token is absent.
- Turning personal memory off removed forgetting/exclusion preferences, allowing
  deleted facts to reappear after a later opt-in. Those preferences now survive;
  private fact values, history and pending questions are still purged.
- The memory middleware could enrich/mutate a request before the app's inner
  origin guard rejected it. It now applies the shared local request guard before
  touching memory; a native-stack regression verifies rejected requests have no
  enrichment side effects.
- Private SQLite connections now close deterministically, including exception
  paths. Databases are created with mode 0600 before SQLite opens them.

All initial finding regressions were observed failing before their respective
fixes. Existing tests pinning an older generation-script cache revision were
updated with the new revision. The full browser suite also caught a missing
`chat_id` field in the reliable-stream request wrapper; that forwarding path is
now covered by a dedicated regression.

## Validation

- Complete Python suite: **3,844 passed; 472 subtests passed**.
- Complete Node suite: **400 passed**.
- Complete isolated Chromium suite: **120 passed**.
- Focused real-Agent/Chromium memory acceptance: **6/6 passed**, no page errors.
- Public privacy scan, translation audit, dependency consistency, syntax checks
  and isolated Docker image builds are required before pushing the candidate.
- Final-head GitHub Tests (macOS/Python/Node, Docker, privacy) and Browser
  acceptance must both pass before merge. The merged main revision is checked
  again before deployment. Both complete workflows also run on a push to this
  dedicated release branch, so a stalled GitHub PR merge-ref calculation cannot
  prevent final-head CI from running. No checks or assertions are skipped.

Commands:

```sh
python -m pytest -q
node --test tests/*.mjs
python -m pytest --e2e tests/e2e -q -x
python scripts/check-public-privacy.py
python scripts/i18n-audit.py
python scripts/test-pr417-preview.py
```

Tests use invented fixtures and fresh temporary HOME/data directories. No real
personal information, production chats, database backups or private manifests
belong in this repository or GitHub.

## Real-Agent preview

The dedicated Docker preview publishes only loopback port 8098. Its web and
actual `agent.entrypoint` containers have no mounts or published ports and run
on an internal Docker network. The Agent's HOME, databases and chats are private
tmpfs fixtures. The gateway's only bind mount is its fixed proxy source code.

The focused test uses actual frontend controllers, browser DOM, HTTP web proxy,
Agent routes and SQLite stores, with all browser requests restricted to 8098:

1. Default off: saved chats create neither personal facts nor archive content.
2. UI opt-in: existing synthetic chats backfill with source chat/message ordinal
   and a correctly ordered pending contradiction.
3. Actual enrichment creates a clarification instruction; unrelated chat replies
   cannot resolve it, and a confirmation in the originating chat can. A rejected
   foreign-origin native stream request cannot mutate or confirm memory.
4. UI edit preserves provenance; UI delete removes renamed history and rebuild
   cannot resurrect it.
5. Archive search, exclusion, rebuild, inclusion and source-chat deletion obey
   the source lifecycle without deleting chats merely to exclude them.
6. UI opt-out removes derived content, preserves source chats, and both private
   databases pass SQLite integrity checks with mode 0600.

The preview gateway needed PATCH forwarding for the edit check, and the test now
waits for bounded startup readiness before asserting behavior. These preview
infrastructure failures were corrected and the complete focused test repeated.
No inference model is used: the real memory enrichment function and its
clarification instructions are inspected against the isolated Agent's stores.

## Backup, deployment and rollback gate

`scripts/backup-local-state.py` backs up all chat files and SQLite databases
under the application's native data roots, with optional external data roots.
Application writers must be quiesced first. SQLite's backup API includes
committed WAL pages; stale WAL/SHM files are not copied beside the snapshot.
Source fingerprints detect changes or added files during capture.

Backup verification checks SHA-256 hashes, restores files to a fresh temporary
directory, runs SQLite integrity checks and compares schema fingerprints and
per-table row counts. Synthetic tests cover WAL, external data, tampering,
changing sources and rejection of backup destinations inside Git worktrees.
Private backups are created outside Git with owner-only directory/file modes.

Operational sequence after all tests and CI pass:

1. Confirm no active generation, agent run or queued job; record current image,
   native Agent configuration and the untouched 8096 container identity.
2. Stage immutable release code and the exact tested web image; prepare code
   rollback using the original image and native Agent plist.
3. Stop web/Agent and relevant database writers; snapshot chats, all native
   SQLite stores and existing web-volume data, then verify the backup/restore.
4. Start the native Agent and 8090 web using the merged revision. Keep original
   service settings and data locations; leave new memory stores opted out.
5. Check build identity, UI assets, API health, privacy defaults and native
   runtime health. Recheck the 8096 container identity without contacting it.
6. Keep the verified private backup and original image/plist available. Code
   rollback does not blindly overwrite chats or databases created after release.

Deployment results and private backup locations are recorded only in the local
completion report and user-facing delivery, not in public repository artifacts.
