# Permanent chat retention — explicit Settings deletion only

This is a non-destructive migration for the authoritative local chat store.

## Contract

- Chat records are saved to host-side JSON, not GitHub. No automatic chat TTL or
  chat-history deletion.
- Ordinary chat appends are persisted by the existing client/server write path.
  New saves wait for disk flush before acknowledging. This is not a guarantee
  against data loss from a failed request, sudden power loss before a request,
  an unavailable Agent, disk failure, or loss of the computer.
- Before an accepted edit, reset-like replacement, removal of messages or
  rollback of assistant text, a private **full previous chat revision** is
  retained under `~/.config/mlx-web/chats/.revisions/<chat_id>/<uuid>.json`.
  Revisions are not removed by the optional test-artifact maintenance job.
- The sidebar no longer offers delete actions. Chat clearing in navigation is
  non-destructive and opens Settings instead.
- Only **Settings → Chat → Daten dauerhaft löschen** contains actions for
  deleting one chat or the complete history. The user must type
  `LÖSCHEN` (or `DELETE`) and accept an additional confirmation.
- Server endpoints `DELETE /api/chats`, `DELETE /api/chats/{id}` and
  `POST /api/chats/{id}/reset` all require an exact-scope, one-use,
  90-second approval token. The web proxy forwards rather than bypasses it.
- An authorized deletion still removes the affected indexed derived chat
  memories; separately saved legacy memories and independently maintained
  backups have separate lifetimes. The user controls whether to erase any
  data. This is intentionally not an automatic full memory wipe.

## Scope and safety limitations

The one-time approval is a protection against accidental deletion and ordinary
non-Settings UI/API calls, **not authentication** for a hostile process with
access to the local Agent. The existing local request guard remains in force.

The existing chat frontend saves changes via asynchronous requests. A network
failure or crashed browser *before a save completes* can still lose unsent text.
A truly zero-loss journal would require per-keystroke local durable storage and
a separate reviewed recovery flow, neither of which is claimed here.

The local revision store is not a replacement for offline/off-device backup. A
malfunctioning disk, accidental deletion of the `~/.config/mlx-web` directory or
physical loss can destroy both. Keep verified private backups; never commit
personal chats to GitHub.

PR #421 adds separately reviewed persistent memory/episodes. This change does
not silently merge, deploy or activate it. Coordinate the new knowledge deletion
policies with the durable Settings approval prior to PR #421 release.

## Tests

```bash
python3 -m pytest -q tests/test_chat_retention.py tests/test_delete_all_chats.py \
    tests/test_personal_memory_integration.py tests/test_image_variants.py
node --test tests/*.mjs
python3 scripts/check-public-privacy.py
python3 scripts/i18n-audit.py
```

Test on a private, isolated host or temporary HOME, not against the live Agent.
Never copy backed-up chat JSON into a live deleted-chat-ID store without first
reviewing tombstones and controlling writers.
