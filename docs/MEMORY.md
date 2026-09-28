# Nobby Memory v1

MLX nobby keeps long-term user memory locally in:

```text
~/.config/mlx-web/memory.db
```

The store uses SQLite/WAL and is not committed to Git.

## What is remembered

Memory v1 is deliberately conservative. It stores:

- explicit requests such as `Merk dir: ...` / `Remember that ...`
- clear durable preference statements such as `Ich bevorzuge ...`
- recurring-tool/model preferences such as `Für Coding nutze ich ...`
- preferred form of address such as `Nenn mich Nobby`

Ordinary questions and one-off commands are ignored.

`Vergiss ...` / `Forget ...` removes matching memories.

## Retrieval

Before eligible text-model calls, MLX nobby retrieves a small bounded set of
relevant memories. Ranking combines lexical relevance, importance, confidence,
recency and pinned status. Pinned memories remain eligible without keyword
overlap.

Retrieved memories are inserted as a separate system-context block with rules
that treat memory as user data, not system instructions. The current user
message always takes precedence over conflicting old memory.

Strict JSON-only and literal-translation model calls are excluded from memory
injection.

## API

The production agent exposes:

- `GET /api/memory`
- `POST /api/memory`
- `PATCH /api/memory/{memory_id}`
- `DELETE /api/memory/{memory_id}`
- `POST /api/memory/observe`
- `GET /api/memory/context?query=...`

These endpoints are intended for the Memory Manager UI and local diagnostics.

## Failure behavior

Memory is optional to the inference path. If the local database is unavailable,
locked or corrupt, model calls continue without memory context rather than
failing the chat request.
