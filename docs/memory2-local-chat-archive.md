# MLX Nobby Memory 2.0 — local chat archive

This is an **opt-in** extension of the existing Nobby Memory system. It does
not train the language model or upload conversation content to GitHub.

## Data flow

1. The authoritative JSON chat sessions stay in `~/.config/mlx-web/chats`.
2. The native Agent (not the Docker web UI) optionally builds a derived FTS5
   index at `~/.config/mlx-web/chat-archive.sqlite3`. The index is disabled
   by default and no additional database file is created before opt-in.
3. Successful chat writes update only the messages that changed. Chat reset
   replaces the index entries, and chat deletion purges them.
4. Existing Nobby Memory continues to retrieve distilled user facts via the
   local embedding service (port 8020). Memory 2.0 adds short lexical excerpts
   from previously saved chats, within the existing latency budget.
5. The model sees only a few bounded, source-identified excerpts, labeled as
   **untrusted historical data**, not a complete private archive.

## Controls

Visit **Settings → Memory → Lokales Chatgedächtnis 2.0**. Enable indexing to
backfill existing chats, search with a query, rebuild the index if necessary,
or exclude individual chat IDs. Turning it off purges the index (but retains
your original chat JSON files and existing distilled memory.db facts).

Local API endpoints (the normal web proxy forwards to the native Agent):

- `GET /api/mlx/memory/archive/status`
- `POST /api/mlx/memory/archive/config` with `{"enabled":true|false}`
- `POST /api/mlx/memory/archive/rebuild`
- `GET /api/mlx/memory/archive/search?query=Sandforge`
- `POST /api/mlx/memory/archive/exclude/{chat_id}`
- `POST /api/mlx/memory/archive/include/{chat_id}`

## Privacy and safety rules

- The derived SQLite file is created under the current user's home, set to
  mode 0600; no Docker mounts, remote transport, Git files, external APIs or
  telemetry are required.
- No raw conversations are included in tests, source code, commits or CI.
- The existing loopback-only Agent and same-origin web gateway security rules
  apply. FileVault and encrypted macOS backups are still recommended.
- Search results are escaped via DOM `textContent`, never inserted as HTML.
- Deletes/tombstones prevent known removed chats from being intentionally
  reintroduced during rebuild.
- `memory.db` contains separately managed distilled memories; disabling the
  chat archive **does not** delete those facts or the source chat files.
- SQLite or indexing failures do not interrupt the authoritative chat write.
  If the index is unhealthy, it may need a rebuild after the underlying
  problem is fixed. Verify deletion operations and privacy audit before
  production deployment.

## Validation and rollout

Run the dedicated new tests and the existing complete suite and browser
acceptance before merging:

```bash
python -m pytest -q tests/test_chat_archive_memory2.py tests/test_chat_archive_memory2_integration.py
python -m pytest -q
node --test tests/*.mjs
python scripts/check-public-privacy.py
```

Use an isolated 8097 preview first. **Do not** change the currently running
production MLX Nobby (8090), native Agent (8010), or Janosch's port 8096
without a verified backup of original chat files and an approved deployment
plan. No live production upgrade is part of this PR.

## Scope limitation

The archive is FTS5 keyword search rather than embeddings for every raw
message. Hybrid behavior comes from this FTS index plus Nobby Memory's
existing local semantic embeddings. Automatic detailed project summaries and
relationship extraction are future enhancements, not claimed as implemented.
