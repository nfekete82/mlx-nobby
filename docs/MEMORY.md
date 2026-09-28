# Nobby Memory v1.2

MLX nobby keeps long-term user memory locally in:

```text
~/.config/mlx-web/memory.db
```

The store uses SQLite/WAL and is not committed to Git. Memory embeddings and
consolidation history are stored in the same database and never require a cloud
service.

## What is remembered

Memory remains deliberately conservative. It stores:

- explicit requests such as `Merk dir: ...` / `Remember that ...`
- clear durable preference statements such as `Ich bevorzuge ...`
- recurring-tool/model preferences such as `Für Coding nutze ich ...`
- preferred form of address such as `Nenn mich Nobby`

Ordinary questions and one-off commands are ignored.

`Vergiss ...` / `Forget ...` removes matching memories. Forgetting keeps an
additional lexical safety check so a semantic near-match alone cannot delete an
unrelated memory. If the active memory belongs to a consolidation chain, an
explicit forget also removes its disabled historical variants and the associated
audit snapshots so forgotten text is not retained only as consolidation history.

## Semantic retrieval

Memory v1.1 introduced the existing local embedding service on port `8020`.
With the default setup this is backed by
`mlx-community/Qwen3-Embedding-4B-4bit-DWQ` through mlx-serve.

Retrieval is hybrid:

- Qwen3 cosine similarity is the primary semantic signal.
- Lexical overlap still contributes to ranking.
- Importance, confidence, recency, and pinned status remain ranking signals.
- Low-similarity semantic noise is rejected unless the memory is pinned.
- If the embedding service is unavailable, the original lexical ranking is used
  automatically.

This allows a memory such as `Für Coding nutze ich Qwen3.8-27B.` to match a
later question such as `Welche KI nehme ich zum Programmieren?`, even without
shared keywords.

## Automatic consolidation

Memory v1.2 prevents durable memory from filling up with repeated or outdated
versions of the same preference.

The lifecycle for a new durable statement is now:

1. store the new memory
2. identify replaceable preference slots and likely duplicates
3. choose the newest matching statement as the active primary memory
4. carry forward the strongest metadata such as `pinned`, importance,
   confidence, last-use time, and accumulated use count
5. set absorbed older memories to `enabled=0`
6. record an audit event in `memory_consolidations`
7. only then retrieve memory context for the current model call

No absorbed memory is automatically deleted. Disabled memories remain available
through `GET /api/memory?include_disabled=true` and can be re-enabled through the
existing PATCH endpoint. This preservation applies to consolidation itself; an
explicit `Vergiss ...` request intentionally purges the connected historical
cluster and its audit text.

### Preference slots

Some durable phrasings have an explicit replaceable slot. For example:

```text
Für Coding nutze ich Qwen3.8-27B.
Für Coding nutze ich Devstral.
```

Both map to the same `use:coding` slot, so the newer Devstral statement becomes
the active memory and the older Qwen statement is disabled. Preferred name
statements such as `Nenn mich ...` use the `address:name` slot.

Slot replacement does not require the embedding service, so direct preference
updates still consolidate while port `8020` is unavailable.

### Free-form duplicate detection

Memories without a known slot are consolidated only conservatively. Candidates
must be in the same memory category and satisfy either:

- very high semantic similarity, or
- high semantic similarity plus substantial lexical overlap

If embeddings are unavailable, only very high lexical overlap is accepted.
This deliberately favors leaving two memories separate over accidentally
combining unrelated facts.

Default thresholds can be tuned with:

- `MLX_MEMORY_CONSOLIDATION_SIMILARITY` (default `0.965`)
- `MLX_MEMORY_CONSOLIDATION_SOFT_SIMILARITY` (default `0.92`)
- `MLX_MEMORY_CONSOLIDATION_LEXICAL_SUPPORT` (default `0.60`)
- `MLX_MEMORY_CONSOLIDATION_LEXICAL_FALLBACK` (default `0.82`)

## Lazy embedding backfill

Existing v1/v1.1 databases require no migration command. A
`memory_embeddings` table is created automatically. On semantic retrieval,
missing vectors are generated in batches and stored with:

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

The browser streaming path and ModelProvider agent/coding path both use the same
memory lifecycle, so consolidation happens consistently before context
injection.

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
- `GET /api/memory/consolidation-status`
- `GET /api/memory/consolidations`
- `POST /api/memory/consolidate`

`POST /api/memory/consolidate` accepts an optional `memory_id`. Without one, it
performs a bounded bulk pass over existing enabled memories. This is useful once
after upgrading an older database to v1.2.

`embedding-status` reports whether semantic retrieval is available, the active
embedding model/dimensions, and how many vectors are currently cached.
`consolidation-status` reports audit-event and disabled-memory counts plus active
thresholds.

Manual deletion removes audit snapshots that reference the deleted memory. An
explicit conversational forget goes further and purges the entire connected
consolidation chain.

## Failure behavior

Memory stays optional to the inference path. If the embedding service is down,
retrieval and consolidation fall back to their conservative lexical/slot modes.
If consolidation itself fails, remembering still succeeds. If the local memory
subsystem is unavailable, the surrounding chat integration continues without
memory context rather than failing the chat request.
