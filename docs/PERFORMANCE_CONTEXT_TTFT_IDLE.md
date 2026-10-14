# TTFT Phase: no pre-answer summary model call

## Root cause (October 2026)

With automatic context compaction enabled, the message submission path
in `frontend/assets/chat/generation.js` previously did:

```js
await MLXChatCompact.autoCompactIfNeeded(session);
```

This happened **before routing or the initial streaming fetch**.
For eligible chats above 80k characters, that operation calls the
separate `/api/chat/compact` model endpoint, blocking the first content
until the full prior conversation is summarized. Even when the summary
is subsequently reused, the first long turn pays the entire extra
model invocation. The same issue applied to editing a prior message.

## Change

- Remove `await autoCompactIfNeeded` from the message submission and
  edit/regeneration paths.
- Only after a **successful completed** streaming answer, schedule
  optional summary preparation after a 3-second idle grace interval.
- Recheck that the original chat is current and no generation/switch
  is in progress before starting. A new user turn or chat reset cancels
  the timer and aborts an in-flight browser-side summary request.
- Existing strict cache validation, full-history fallback, unchanged
  visible chat, exclusion of coding/file/media contexts and opt-out
  remain intact.
- The first long reply now uses the **full original history** unless
  a valid summary already exists. Once an idle summary completes,
  the subsequent turn may use reduced input context.
- A client-side AbortController cannot guarantee that an already
  dispatched synchronous server-side model call will stop consuming
  resources instantly; the backend still owns provider/runtime locks.
  That corner case should be confirmed via real local observability.

## Validation

```bash
node --test tests/test_context_preserving_compact.mjs
node --test tests/test_image_edit.mjs tests/test_sse_stream.mjs tests/test_video_job.mjs
```

The focused tests verify that scheduling does not launch a request
before the timer, cancellation prevents dispatch, busy sessions or
disabled auto compact skip work, in-flight abort invalidates the
stale summary, and existing cached summaries and original history
stay correct. Run normal repository CI and browser acceptance as well.

This phase is a **logical blocking-path fix**, not a claimed measured
real-world TTFT speedup. Real measurements on the Mac need at least
one uncached long text conversation; compare time to first
semantic content separately from subsequent cached-summary turns.
Do not equate the short-request native benchmark or the summary
model timing with end-to-end browser TTFT.

Only frontend scripts are changed. No service configuration, MLX
model selection, speculative decoding or RAM safety budgets change.
The rollout only rebuilds/restarts the web container when idle.
