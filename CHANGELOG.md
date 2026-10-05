# Changelog

## Unreleased

- Make ad-hoc generated images, videos and Talking Photo outputs temporary by default, keep them only after explicit save/download, delete unsaved browser-session results on close, immediately remove Talking Photo LTX intermediates, and add a 24-hour crash-recovery cleanup while protecting Shorts/project assets and legacy untracked media.

- Wait for LaunchAgent unload completion before reloading changed configuration and restore the previous service if bootstrap fails.

- Add reproducible, pin-bound patching for the managed LTX-MLX runtime.
- Extend the managed LTX low-memory LoRA loader to apply compatible non-transformer adapter targets.

## v1.6.2

- Fix chat stream disconnect cleanup so an abandoned response cannot retain the shared runtime lease and block subsequent chat or gateway requests.

- Preserve read-aloud loading, playback and pause state when the same chat refreshes.

- Preserve Model Runtime technical-detail state during background refreshes.

- Added local real-runtime acceptance checks for chat, speech, image and video generation/playback.

- Added browser end-to-end regression coverage for chat, speech, image and video workflows.

- Fix chat read-aloud loading and playback state, remove competing speech
  handlers, and prevent voice status updates from freezing the UI.

- Validate optional Uncensored video profile availability before queueing jobs,
  show unavailable profiles in the dialog, and preserve launchd adapter settings.

- Simplified the Models settings information hierarchy by removing repeated
  Runtime/storage details and making model summaries context-aware.

- Isolate real browser acceptance history so tests cannot load, migrate or
  modify user chats.

- Make the Vision watchdog regression test deterministic without changing
  runtime deadlines.

- Document the canonical release procedure and provide an automated release gate.

## v1.6.1

- Fixed the web job-queue and cancellation proxies so Queue status and Shorts
  cancellation work through the normal web UI.

- Refreshed the bilingual Help Center and technical documentation for current
  Shorts drafts/rendering and APIs, image workflows, memory, automations, local
  API integrations and runtime tooling; added help, link and route regression
  coverage without changing product behavior.

## v1.6.0

- Added a local OpenAI-compatible inference gateway with `/v1/models`,
  `/v1/chat/completions` and configurable virtual coding/chat/agent model roles.
- Added native SSE streaming, tool-call transport, usage forwarding and client
  cancellation under the existing Runtime Coordinator. External requests remain
  stateless without Nobby chat persistence or memory/RAG/workspace activation.
- Validated Cline 4.1.22 agent turns, file operations and cancellation; documented
  Cline setup and the unauthenticated loopback-only API. Cline executes its tools.

## v1.5.0

- Added the Shorts pre-production editor, draft selection, explicit History/job
  navigation, retry/duplicate/cancel controls and chat draft references. Chat
  planning ends before rendering; production starts explicitly in Studio.
- Fixed pending autosave loss on History, draft/job switches, close and render.
  Saves/navigation are serialized; failed saves preserve edits and block leaving.
- Added German/English editor translations, structured voiceover-duration UI
  errors, safe unknown-error fallbacks and stale selection-response guards.

- Added Shorts-v2 backend plans, normalization, versioned drafts, capabilities,
  scene media APIs and revision/retry proxies while retaining v1 projects.
- Added per-scene TTS, static scene captions, transitions and local music/SFX
  composition with the existing quality profiles and model services.
- Fixed voiceover timing with per-scene FFmpeg compression up to 1.15x and safe
  duration diagnostics beyond that limit; completed videos remain available.
- Fixed retry preflight to require image generation only for missing keyframes,
  validate reused media as regular nonempty files and retain completed TTS after
  a compose failure. Public job/history errors use safe diagnostic messages.

- Expanded the Routing Observatory with separate original/final route columns,
  confidence source, guard/intent diagnostics, and localized guard reasons.
- Fixed portrait routing so instructional questions such as "Wie erstelle ich
  ein Porträt?" remain normal chat while explicit portrait-generation requests
  continue to use the image route.
- Added routing architecture documentation and refreshed the README service
  topology to include the native video dispatcher on port 8060.

- Added reference-image generation with persisted source identity, model-aware
  routing and reference-aware image actions. Regeneration keeps reference paths
  and source metadata private.
- Added canonical image variant batches pinned to the first image's resolved
  model and settings, durable group recovery, selectable 1–6 outputs, and gallery
  selection, download, enhancement, retry and cancellation controls.
- Added Image Pipeline V2 intent routing, model prewarm and telemetry, adaptive
  image runtime settings, a Quality+ pipeline and editable negative prompts.
- Added SDXL scheduler selection and benchmarking with validated Juggernaut
  defaults; preserved prompt semantics, batch settings and native portrait quality.
- Fixed MFLUX compatibility checks, image-service restart recovery, variant
  gallery runtime and stale served-script caching. Completed images survive
  follow-up action failures, with bounded artifact-publication waiting.
