# PR #415 persistence validation — 2026-11-04

Base: `b84b799fc26242cf4e5a3070106a9f7c94a930f6`.
PR: https://github.com/nfekete82/mlx-nobby/pull/415.

## Reproduction and fix

The original Node and Chromium/HTTP regression failed because a rejected CAS
write replaced the local conversation whenever it had not changed again during
the request. The rejected payload itself was an unsaved edit.

Every substantive rejected edit now becomes a separately persisted chat. A
SHA-256 ID derived from the source ID and canonical conversation content makes
identical losing tabs converge on one new record, while different versions use
different IDs. Timestamps, streaming timers, object key order and startup settings
normalization do not create duplicate conversations. Each pending draft has its
own randomly keyed browser recovery record, retained until acknowledgement;
another tab replacing the whole-list cache cannot erase that record. Divergent
streaming drafts that initially shared the same content ID remain separately
recoverable. Server deletion tombstones also apply to recovery records.

Additional fixes drain edits after a successful PUT advances the server timestamp,
ignore GET results overtaken by PUTs, preserve offline edits regardless of clock
ordering, and invalidate modern CAS tokens after same-millisecond legacy writes.
The existing CAS validation, per-chat write serialization, server lock and atomic
file replacement remain in place.

## Automated validation

- `node --test tests/*.mjs`: **395 passed**, including 19 multi-tab cases.
- `python -m pytest -q`: **3,801 passed**, **472 subtests passed**.
- Python API regressions include truly parallel guarded PUTs, disk/readback of
  both versions, equal-millisecond CAS, no-op writes and mixed legacy/CAS clients.
- Tracked Python/JSON, frontend JavaScript and shell syntax: passed.
- `python scripts/check-public-privacy.py`: passed.
- `python scripts/i18n-audit.py`: passed.
- `python -m pip check`, Docker Compose validation and preview web build: passed.

An intermediate full Python run had one failure in the unchanged
`test_streaming_chat_is_enriched` memory middleware timing test. Its focused
rerun and subsequent complete suite passed. The original persistence regression
was observed failing before the fix; the new legacy-millisecond regression also
failed before its corresponding fix.

## Isolated HTTP and Chromium acceptance

Reproduce with `python scripts/test-pr415-preview.py` using the CPU test
requirements and an installed Playwright Chromium. The script fixes its target
to `http://127.0.0.1:8097`, uses fresh synthetic chats and a fresh browser context,
and blocks browser requests to other origins. It does not delete chats.

All six checks passed against the real frontend, web proxy and Agent persistence
code, using two or three Chromium tabs sharing localStorage:

1. Edits to separate chats remain durable.
2. Concurrent versions of one chat survive under distinct IDs and after reload.
3. A generating draft survives another tab replacing the cache and a reload.
4. Identical winning/losing content creates no copy.
5. Two identical losing tabs converge on one conflict copy.
6. Three different versions remain stored separately.

Successful real-Agent fixture prefix:
`pr415-bb38a1d2c6f548bf837e1968c01ea138`.
Earlier four-case runs also passed against the existing isolated mock Agent.
Generation is simulated by the controller's generation flag and evolving draft;
no inference model is loaded or called by these persistence checks.

The existing Downloads test was inaccessible due to macOS filesystem privacy;
the committed script above replaces it with repeatable browser/HTTP checks.

## Security and operational review

- Work took place in the PR worktree and branch, never on `main`.
- Preview gateway publishes only loopback port 8097. The web and Agent services
  remain on the existing Docker network with `Internal=true`.
- The validation Agent runs the repository's actual `agent.app` in its own
  container, with **no bind mounts, no volumes and no published ports**. Its HOME,
  runtime state and chat files live only in that container's private `/tmp` tmpfs.
- No production Agent, models, chat files, Docker volumes or chat deletion APIs
  were used. Ports 8090 and 8096 were not contacted or changed. Internal port 8010
  belongs only to the isolated preview Agent; the production Agent was not used.
- Recovery records use the existing browser origin and lightweight chat cache
  representation; no new external transport, HTML rendering sink, arbitrary file
  path, dependency or privileged API is introduced. Malformed journal entries
  are ignored independently. Journal acknowledgements remove only known draft
  keys; deletion tombstones prevent resurrection.
- SHA-256 conversation IDs satisfy the existing server ID validation. New copies
  use `expected_updated=-1`; existing records still require their acknowledged
  CAS version. Identical copy races reconcile to the saved copy instead of
  overwriting it or creating a duplicate.
- Browser storage exhaustion remains a browser persistence limitation; existing
  cache/journal errors are reported and network persistence remains available.
- `main` remained at `9adf61ffefd69f25c67898eafa636713fef82203`.
  PR #415 was not merged and no production deployment was performed.
