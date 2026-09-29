# Nobby Memory Manager

The Memory Manager is available under **Settings → Memory** and manages the local long-term memory introduced with Nobby Memory v1.

## Features

- Search all saved memories.
- Filter by active, pinned, or disabled entries.
- Add new memories manually.
- Edit memory text, category, and importance.
- Pin or unpin important memories.
- Enable or disable individual memories without deleting them.
- Permanently delete memories.
- Show the Memory v1.2 consolidation status and number of consolidation events.
- Run a bounded manual **Memory bereinigen / Clean up memory** pass for legacy data.
- Inspect consolidation history, including the old and current memory text, reason, timestamp, and similarity when available.
- Mark absorbed memories with their consolidation reason and show which active memory replaced them.
- Show active memories that have older consolidated variants.
- Restore an absorbed memory explicitly as the current variant. Restoring re-enables and updates that memory through the normal lifecycle, so automatic consolidation may disable the previously current variant.

## Consolidation reasons

The UI maps the Memory v1.2 audit reasons to user-facing labels:

- `slot_replacement` → updated preference / aktualisierte Präferenz.
- `semantic_duplicate` → semantic duplicate / semantisches Duplikat.
- `lexical_duplicate` → duplicate / Duplikat.

Normal consolidation does not delete absorbed memories. They remain disabled in the local store and can be reviewed in the Memory Manager. Explicit conversational forget operations still use the privacy cleanup path documented in `MEMORY.md` and may permanently remove related historical variants and audit records.

## Local API

The UI talks only to the local web backend. The web backend proxies the agent memory API through:

- `GET /api/mlx/memory`
- `POST /api/mlx/memory`
- `PATCH /api/mlx/memory/{memory_id}`
- `DELETE /api/mlx/memory/{memory_id}`
- `GET /api/mlx/memory/context`
- `GET /api/mlx/memory/consolidation-status`
- `GET /api/mlx/memory/consolidations`
- `POST /api/mlx/memory/consolidate`

Memory data and consolidation history remain local in the SQLite database at `~/.config/mlx-web/memory.db`.

## Frontend architecture

The base CRUD manager remains in `frontend/assets/chat/memory-manager.js`. Memory v1.2 consolidation UI is kept in the separate `frontend/assets/chat/memory-manager-consolidation.js` module so the existing manager and the large legacy chat files do not continue growing together.

Both Memory Manager scripts are injected into the existing chat/settings HTML at runtime by the web entrypoint. This avoids coupling the feature to the large static `chat.html` and `chat.js` files while keeping the existing settings router unchanged.
