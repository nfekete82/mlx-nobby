# Routing Observatory

MLX Nobby routes normal chat, media generation, agent work, research and other
specialized requests through the local routing stack. The Routing Observatory
makes that decision visible without changing the router itself.

## Decision flow

```text
Browser prompt
  → POST /api/mlx/chat/actions/route
  → local router / agent classification
  → conservative media guard
  → confidence guard
  → final route returned to the chat UI
  → local observability trace
```

The router result is preserved as `original_target`. Guard layers may change the
final `target` when a media classification is too weak or when the prompt is
better interpreted as a normal question.

Examples:

```text
"Erstelle ein fotorealistisches Porträt ..."
  original: image → final: image

"Wie erstelle ich ein gutes Porträt ...?"
  original: image → final: chat
  reason: instructional_portrait_question
```

The guard intentionally runs after the router so false-positive media routes can
be corrected without weakening explicit generation requests.

## Trace fields

Each recorded decision contains the fields needed to explain the route:

| Field | Meaning |
| --- | --- |
| `original_target` | Route returned before the local guard policy. |
| `target` | Final route used by the UI. |
| `confidence` | Router-provided or locally derived confidence from 0 to 1. |
| `confidence_source` | `router`, `heuristic`, or `unavailable`. |
| `reason` | Decision or guard reason. |
| `intent` | Normalized intent label used for diagnostics. |
| `guarded` | Whether the final route differs from the original route. |
| `duration_ms` | Routing duration when available. |
| `prompt_preview` | Normalized, truncated prompt preview for local diagnosis. |
| `prompt_sha256` | SHA-256 hash used to correlate a prompt without storing a second full copy. |
| `prompt_chars` | Original prompt length. |

The observability layer does not add a separate complete raw-prompt field. It
stores the truncated preview, hash and metadata in the local routing store.

## Local storage

Routing decisions are stored in:

```text
~/.config/mlx-web/routing-observatory.json
```

The store retains a bounded list of recent decisions. Observability failures are
non-blocking and must never prevent a chat or media route from completing.

## UI

The Routing Observatory is shown under **Settings → Functions** and displays:

- prompt preview;
- original route;
- final route;
- confidence and confidence source;
- guard/decision reason, intent and routing duration;
- feedback controls.

Guarded rows are highlighted so corrections such as `image → chat` are visible
immediately.

## Feedback and regressions

A decision can be marked **Correct** or **Wrong**. Wrong decisions require the
expected target and are marked as regression candidates in the same local store.
This provides concrete examples for future router/guard tests without silently
changing routing behavior from UI feedback alone.

Web endpoints:

```text
GET  /api/routing/decisions
POST /api/routing/decisions/{decision_id}/feedback
GET  /api/routing/regressions
```

## Guard policy

The media guard is deliberately conservative:

1. explicit media creation requests stay on their media route;
2. dedicated visual prompts with strong visual cues may stay on `image`;
3. long chat-like text can be demoted from accidental media classifications;
4. Shorts require an explicit creation instruction;
5. low-confidence active media routes fall back to chat;
6. medium-confidence media routes require explicit intent or a dedicated media prompt;
7. high confidence is normally preserved unless a more specific conservative guard has already corrected the route;
8. instructional portrait questions such as `Wie erstelle ich ...?` are treated as chat even when creation vocabulary appears inside the question.

The portrait intent runtime extends the image-intent vocabulary but also excludes
instructional/question forms so words such as `erstelle` inside a question are
not mistaken for an imperative generation command.

## Relevant implementation

| Path | Responsibility |
| --- | --- |
| `backend/media_routing_ui.py` | Guard policy, confidence handling, trace persistence and API endpoints. |
| `backend/media_routing_portrait_intent.py` | Portrait generation intent and instructional-question protection. |
| `frontend/assets/chat/routing-observatory.js` | Observatory rendering and feedback UI. |
| `frontend/assets/chat/routing-observatory.css` | Diagnostic table and guard styling. |
| `frontend/i18n/routing-observatory.json` | German/English labels and reason text. |
| `tests/test_routing_observatory.py` | Backend confidence/trace/feedback behavior. |
| `tests/test_media_routing_portrait_intent.py` | Portrait routing regressions. |
| `tests/test_routing_observatory_ui.mjs` | Observatory UI contract. |

When a new guard reason is introduced, add its translation and a regression test
at the same time. This keeps the runtime behavior and the diagnostic UI in sync.
