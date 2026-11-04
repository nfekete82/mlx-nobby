# Persistent memory development validation — 2026-11-04

Scope: isolated continuation of draft PR #421, base `8757c8ce`. Production
checkout, original personal data and live service configuration were not
edited. No image/video generation, merge, deployment or service restart was
performed. All test conversations, names, project references and credentials
are synthetic.

## Executed checks

Raw local test logs are outside Git; only non-private summary evidence is included here. All final suites completed with zero failures.

- Complete Python suite: **3,935 passed, 472 subtests passed**, 0 failures, 71.49 seconds. Two existing warnings: Starlette TestClient deprecation and the intentional duplicate ZIP-path fixture.
- Complete JavaScript suite: 408 passed, 0 failed.
- Complete Chromium suite: **124 passed**, 0 failures, 196.89 seconds; one existing Starlette deprecation warning.
- Dedicated knowledge browser coverage: edit/pin/history/delete in German and
  English, multi-fact merge, download, pause, category opt-out, similarity review.
- Translation audit: passed, matching English/German keys.
- Public privacy scan: passed on the complete staged change. The first staged scan rejected a deliberately fake credential-shaped test string; it was replaced with an obvious synthetic placeholder without weakening the credential-rejection assertion.
- Syntax checks: **671 Python, 88 frontend JavaScript, 43 JSON and 15 shell files passed**. Staged whitespace check passed.

Python fixtures isolate home paths, databases and runtime state. Full suites
that open localhost fixture ports run with permission to bind those isolated
ports. No assertions were skipped to make the release gate green.

## Real local model acceptance

Verified selected text model: `Qwen3.8-27B-Uncensored-MLX/6-bit`.
Inference uses the already running Agent's bridge and runtime lock, with no
role switch. Persistence uses temporary SQLite databases and synthetic source
chats. `scripts/test-persistent-memory-local.py` is the reproducible acceptance.

The verified run passed **8/8 checks in 37.49 seconds**:

1. Grounded image-color preference persisted.
2. Source-linked childhood episodes persisted.
3. The preference was retrieved for a different conversation.
4. A German childhood question retrieved the original childhood source.
5. Sandforge project knowledge was retrieved from the synthetic project source.
6. An unrelated Python question did not expose the childhood narrative.
7. `Merk dir das unbedingt` returned a true persisted result.
8. Deletion remained effective after importing the older knowledge snapshot.

These checks verify persisted evidence and retrieval, not an evaluation of
long-form counseling responses, all private historical data or rendered media.
The test does not load or generate an image, inspect actual visual contents,
or claim that historical failed jobs produced files.

## Failed attempts and repairs

- The first full Python run could not collect Office-related tests because the
  pre-existing test environment lacked `python-docx`. Repository-pinned test
  dependencies were installed in an isolated temporary environment; production
  environments were not modified.
- Local HTTP fixture tests initially lacked sandbox permission to bind ports.
  The suites were rerun with permission for their isolated servers.
- An IPv6 security test failed in Starlette 1.6.0's deprecated httpx TestClient
  URL parser before reaching application code. Its request helper now uses
  httpx ASGITransport and still verifies all literal-loopback aliases against
  the real LocalRequestGuard. Its 12 tests and 10 subtests passed separately.
- Early structured tests caught incorrect numeric normalization, an episode
  INSERT placeholder mismatch, missing source-independent deletion masks,
  and a worker queue teardown race. Those defects were repaired and covered.
- A model test harness initially selected the first registry model rather than
  the configured text model. One run reported 8/8 but did not verify the model
  identity, so it is not the release evidence. Subsequent runs exposed invalid
  extraction/HTTP failure with that selection. The harness now reads the
  configured text-model identity and refuses known media checkpoints. No image
  generation endpoint was called.
- With the verified text model, one real run passed 7/8: childhood extraction
  existed but a German childhood query missed its source. Topic aliases and a
  literal autobiographical fallback were added, tested, and the verified
  acceptance then passed 8/8 in 37.49 seconds.

## Release status

Development validation does not authorize production rollout. No merge or
production deployment occurred. Before release, separately review backups,
private archive size/performance, the conservative scope of forgetting when
only ordinal source IDs exist, and subjective response quality with an
explicitly opted-in private dataset. See the architecture and acceptance guide
in [persistent-intelligence-memory.md](../persistent-intelligence-memory.md).
