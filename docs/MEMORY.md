# Nobby Memory v1.1

MLX nobby keeps long-term user memory locally in:

```text
~/.config/mlx-web/memory.db
```

The store uses SQLite/WAL and is not committed to Git. Memory embeddings are
stored in the same database and never require a cloud service.

## What is remembered

Memory remains deliberately conservative. It stores:

- explicit requests such as `Merk dir: ...` / `Remember that ...`
- clear durable preference statements such as `Ich bevorzuge ...`
- recurring-tool/model preferences such as `Für Coding nutze ich ...`
- preferred form of address such as `Nenn mich Nobby`

Ordinary questions and one-off commands are ignored.

`Vergiss ...` / `Forget ...` removes matching memories. Forgetting keeps an
additional lexical safety check so a semantic near-match alone cannot delete an
unrelated memory.

## Semantic retrieval

Memory v1.1 reuses the existing local embedding service on port `8020`. With the
default setup this is backed by `mlx-community/Qwen3-Embedding-4B-4bit-DWQ`
through mlx-serve.

Retrieval is hybrid:

- Qwen3 cosine similarity is the primary semantic signal.
- Lexical overlap still contributes to ranking.
- Importance, confidence, recency, and pinned status remain ranking signals.
- Low-similarity semantic noise is rejected unless the memory is pinned.
- If the embedding service is unavailable, the original v1 lexical ranking is
  used automatically.

This allows a memory such as `Für Coding nutze ich Qwen3.8-27B.` to match a
later question such as `Welche KI nehme ich zum Programmieren?`, even without
shared keywords.

## Lazy embedding backfill

Existing v1 databases require no migration command. A `memory_embeddings` table
is created automatically. On semantic retrieval, missing vectors are generated
in batches and stored with:

- memory ID
- embedding model ID
- vector dimensions
- text content hash
- creation time

Unchanged memories reuse their stored vector. Editing a memory changes its text
hash, so the vector is regenerated on the next semantic retrieval. Changing the
selected embedding model or dimensions similarly causes a lazy re-embedding.

The memory embedding client defaults to the existing `EMBEDDINGS_URL` and can
be overridden independently with `MEMORY_EMBEDDINGS_URL`.

Optional tuning variables:

- `MLX_MEMORY_EMBEDDING_TIMEOUT` (default `12` seconds)
- `MLX_MEMORY_EMBEDDING_BATCH_SIZE` (default `64`, max `128`)
- `MLX_MEMORY_MIN_SEMANTIC_SIMILARITY` (default `0.35`)
- `MLX_MEMORY_EMBEDDING_QUERY_INSTRUCTION`

## Context injection

Before eligible text-model calls, MLX nobby retrieves a small bounded set of
relevant memories and inserts them as a separate system-context block with
rules that treat memory as user data, not system instructions. The current user
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
- `GET /api/memory/embedding-status`

`embedding-status` reports whether semantic retrieval is available, the active
embedding model/dimensions, and how many vectors are currently cached.

## Failure behavior

Memory stays optional to the inference path. If the embedding service is down,
retrieval falls back to lexical mode. If the local memory subsystem itself is
unavailable, the surrounding chat integration continues without memory context
rather than failing the chat request.
