# Routing Observatory

The local Routing Observatory shows intent, original/final route, confidence,
guard reason, timing and feedback. Prompt previews are redacted; a hash and
character count identify a turn without persisting text or image payloads.
Historical previews are also redacted on read and on the next store write.

## Decision flow

```text
Current instruction + image context
  → shared backend/media_intent.py decision
  → Agent preflight (execution_requested gates media)
  → Web middleware applies the same policy and records a trace
  → Browser selects a media modal only for an authorized route
  → Action endpoint rechecks execution intent
  → existing media pipeline or chat/VLM
```

Text-output requests, questions and withheld execution take precedence over
media guesses. A separate explicit media execution clause remains supported.
Attachments, model names, adult words and classifier confidence never authorize
a job. A failed browser preflight returns to chat. Runtime media tools check the
original user goal, including when a tool query or delegated goal is rewritten.
Non-media semantic routing retains its existing manager and permission gates.

The response includes `intent`, `target`, `execution_requested`, `media_context`,
`confidence`, `reason`, `guard` and `fallback`. Confidence describes the shared
rule's decision, not the probability of an LLM prediction. `original_target`
identifies a route proposed before the web guard; `target` is the final route.

Feedback is stored locally through `/api/routing/decisions/{id}/feedback`.
Incorrect decisions are exposed at `/api/routing/regressions` for regression
review. Retention remains bounded to 500 records. Store errors never block chat.

## Relevant implementation

| Path | Responsibility |
| --- | --- |
| `backend/media_intent.py` | Shared decision and explicit execution contract. |
| `agent/app.py` | Preflight, semantic media gate and action dispatch. |
| `agent/runtime_tools.py`, `agent/run_state.py` | Original user goal gate for media tools. |
| `backend/media_routing_ui.py` | Shared web policy, trace persistence and feedback APIs. |
| `backend/media_prompt_meta_guard.py`, `backend/media_routing_portrait_intent.py` | Compatibility helpers without independent monkey-patched policies. |
| `frontend/assets/chat/generation.js` | Authoritative preflight consumption and chat fallback. |
| `frontend/assets/chat/routing-observatory.js` | Observatory rendering and feedback UI. |
| `frontend/i18n/routing-observatory.json` | German/English reason labels. |
| `tests/test_media_intent.py` | Endpoint matrix, execution authorization and privacy regressions. |
| `tests/test_image_edit.mjs` | Browser modal and failed-preflight regressions. |

See [Routing audit](ROUTING_AUDIT.md) for the root cause, previous ordering and
remaining parser boundaries. Add translated guard reasons with regression tests.
