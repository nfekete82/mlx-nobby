# Memory Context Inspector

Memory 3 adds **Diagnose all memory stores**, a local POST-based preview of
the actual fast chat-context assembly across personal facts, structured
knowledge, archive and legacy notes. It shows rewritten terms, candidates,
selected sources, budgets and pause/failure reasons; it does not execute an
answer model. The original legacy scoring inspector below remains available.
See [Memory 3](MEMORY_3.md#dashboard-and-diagnosis).

The Memory Context Inspector is a read-only developer tool under **Settings → Memory**. It explains which long-term memories Nobby would inject for a specific user message without changing memory usage counters.

## What it shows

- Retrieval mode: hybrid semantic + lexical search, or lexical fallback.
- Selected memories in ranking order.
- Total retrieval score.
- Semantic similarity when embeddings are available.
- Lexical overlap.
- Importance, confidence, recency, and pinned bonus.
- The exact memory context block that would be injected into the model prompt.

The inspector uses the same thresholds and scoring weights as the production memory retrieval path. It is intentionally outside the normal chat request path so diagnostics cannot add latency to chat.

## Local API

The agent exposes:

- `GET /api/memory/inspect?query=...&limit=6`

The web backend proxies it through:

- `GET /api/mlx/memory/inspect?query=...&limit=6`

The limit is bounded to the normal Memory maximum of 12.

## Side effects

The inspector is read only. Unlike normal retrieval, it does not update `last_used_at` or `use_count`. It does not create, edit, enable, disable, consolidate, or delete memories.

The frontend implementation lives in `frontend/assets/chat/memory-context-inspector.js` and is injected alongside the existing Memory Manager modules instead of being added to the large legacy chat files.
