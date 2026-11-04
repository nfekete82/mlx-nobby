# MLX Nobby — Private personal memory and correction workflow

For the current PR #421 extension, see [Persistent local intelligence memory](persistent-intelligence-memory.md). This document describes the earlier conservative layer.

**This is local, opt-in, and reviewable; it is not model training.** Private
conversations remain in the local authoritative chat store and never belong in
the Git repository. GitHub contains code and synthetic tests only.

## Memory layers

1. **Chats (originals)**: Existing per-chat files under
   `~/.config/mlx-web/chats`, managed by the current chat interface. These
   files already preserve both user and assistant messages.
2. **Searchable chat archive**: Memory 2.0's opt-in, derived SQLite FTS index at
   `~/.config/mlx-web/chat-archive.sqlite3`. It indexes user and assistant
   text and retrieves bounded excerpts by query. It is not a semantic index
   of every raw message.
3. **Structured personal facts**: New independent opt-in SQLite file at
   `~/.config/mlx-web/personal-memory.sqlite3`. Only recognizable,
   user-stated durable facts and explicit private notes are extracted.
   Relationship and health entries can be marked sensitive. Each record
   identifies its person/topic, attribute, value, source chat/message
   ordinal, timestamp and active/superseded state.
4. **Existing Nobby Memory**: `~/.config/mlx-web/memory.db` continues to
   hold preferences learned using existing rules and local embeddings;
   its existing Manager supports editing and deletion.

The language model gets only a few relevant locally retrieved facts and chat
excerpts. It does **not** receive all historical chats on every request.

## How corrections work

- A new statement that differs from the currently active value of the same
  structured attribute creates a **pending conflict**, not an automatic
  overwrite. The old fact stays active until confirmed.
- A clearly stated change such as a rescheduled appointment can be applied
  directly and the previous value stays visible as historical.
- The normal chat context requests a clarifying question when the new user
  statement matches a pending contradiction. With a single pending question,
  explicit phrases such as "Ja, das neue Datum stimmt" or "Nein, das alte
  Datum stimmt" can resolve it in the chat that proposed the conflicting value.
  A confirmation from an unrelated chat cannot resolve that question. This is model-prompt guidance, not a guarantee
  that every model response will contain a clarification.
- All pending conflicts are independently reviewable under
  **Settings → Memory → Private personal memory**: retain previous value,
  use new value, or enter corrected value.

## Reviewing, editing and forgetting

Inside Settings → Memory, two additional sections are present:

- **Local chat memory**: enable/disable full-text indexing; search the archive,
  rebuild after failures, exclude an entire chat from indexing.
- **Private personal memory**: enable/disable fact extraction; search facts,
  show older versions, manually add a fact, edit or delete individual entries,
  review all outstanding contradictions. Source chat and message ordinal remain
visible after editing. Deletion follows renamed attributes through their full
revision lineage.

Memory toggles are intentionally independent. Both are OFF by default. To
activate full local recall, enable both. Switching off either one securely
purges that layer's **derived** data; it does not erase your original chat JSON,
separately stored Memory Manager facts, or older external/off-device backups.
Exclusion and forgetting preferences remain so a later opt-in cannot silently
re-import explicitly deleted facts.
To remove the underlying raw information, delete the source chat using
MLX Nobby's existing chat controls, and handle personal backups separately.

The private SQLite files are owner-readable only (0600). FileVault and
encrypted backups are still important, as a local process running under your
macOS user identity can access files on your behalf.

## Scope / accuracy

The general archived conversations are searchable but not all turned into
facts. The structured extractor is deliberately conservative: it recognizes
selected self-, family-, relationship-, appointment- and preference-patterns,
not arbitrary semantics or sarcasm. Ambiguous relative dates, uncertain
information and names for unrelated appointments are not reliably normalized.
The model still must verify dates and project states from context and should
not claim to know things not explicitly recorded. Do not blindly trust
extracted memories.

No credentials are intentionally extracted into personal fact cards.
Conversations and source notes might nonetheless contain credentials if
entered by the user; avoid storing secrets in chats.

## Native API

All endpoints run only in the local Agent and are also served through the
same-origin /api/mlx/memory/personal proxy:

- GET `/api/personal-memory/status`
- POST `/api/personal-memory/config` with `{"enabled":true|false}`
- POST `/api/personal-memory/rebuild`
- GET `/api/personal-memory/facts?query=...&history=true`
- POST `/api/personal-memory/facts` with subject, field, value, sensitive
- PATCH/DELETE `/api/personal-memory/facts/{id}`
- GET `/api/personal-memory/conflicts`
- POST `/api/personal-memory/conflicts/{id}/resolve`
  with `{"decision":"old"|"new"|"custom","value":"..."}`

## Verification and release

The code is developed in the PR #417 branch. Run all existing CI, Python,
Node and Chromium suites plus the dedicated personal-memory tests:

```bash
python -m pytest -q tests/test_personal_memory.py tests/test_personal_memory_integration.py
python -m pytest -q
node --test tests/*.mjs
python scripts/check-public-privacy.py
python scripts/i18n-audit.py
```

**Do not merge or deploy until PR CI and Mac-based isolated preview tests pass.**
Back up original chats and both memory SQLite databases before any deployment.
Keep the current production web on 8090, Agent on 8010 and Janosch's service
on 8096 untouched while testing. A GitHub merge does not update native
macOS services automatically.
