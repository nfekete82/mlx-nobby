# Changelog

## Unreleased

## v1.7.0

- Add local Talking Photo generation with managed MuseTalk-Mac, local TTS and lip sync, including clipboard image paste and robust handling of portrait dimensions.

- Add natural Talking Photo motion by combining LTX 2.5 image-to-video movement with MuseTalk lip sync for subtle head, eye, shoulder and upper-body animation.

- Add Shorts cast voice assignments and ordered multi-speaker dialogue with per-speaker voice synthesis and scene speaker identity.

- Make ad-hoc generated images, videos and Talking Photo outputs temporary by default. Explicit save/download keeps media; unsaved browser-session results are removed automatically, Talking Photo intermediates are deleted immediately, and a 24-hour recovery cleanup removes abandoned temporary assets while protecting Shorts/project assets and legacy media.

- Improve managed MuseTalk installation and startup recovery, including virtual-environment weight downloads, required model modules, demo media setup and resilient LaunchAgent bootstrap behavior.

- Improve the managed LTX runtime with reproducible pin-bound patching, compatible low-memory LoRA targets and safer LaunchAgent reload/recovery.

- Make Performance Observatory formatting tests deterministic across system locales.

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

- Added Agent Task Mode, persistent workspace mode and git-style task diff
  comparison. Improved empty chat drafts and reorganized settings navigation.
- Added Model Scout discovery, tuning markers and filters, local A/B benchmarks,
  and model comparison/adoption workflows with lazy frontend loading.
- Added persistent local automations, restart recovery and a notification inbox
  for completed or failed automation runs.
- Added confirmed deletion of all chat history with chat-scoped media cancellation,
  artifact/cache cleanup and protection against late saves and stale server sync.
- Added one shared click/tap image-preview dialog for attachments, generated images
  and galleries, including keyboard controls and focus return; removed automatic
  gallery hover enlargement and improved sidebar navigation and SVG icons.

- Added passive chat/vision/media routing observations, centralized conservative
  media intent and confidence guards. Prompt-writing requests stay in chat,
  cancellation falls back to chat, and content constraints remain distinct from
  execution bans.
- Added Performance Observatory V2 and improved chat/video runtime handoffs,
  workspace polling and runtime-lock contention. Vision streaming tolerates long
  prefill and reports empty responses; read-aloud handles stalled TTS safely.
- Added a warm native LTX 2.5 MLX video worker, promoted Q4 to the default backend,
  and added an optional uncensored profile; removed the experimental Wan backend.
- Improved LTX cumulative progress, heartbeat and benchmark output, with
  cold/warm/cold isolation, macOS system/thermal telemetry and a reference baseline.
- Repaired CI validation and tightened workflow triggers; enabled automatic
  cleanup of merged pull-request branches.

## v1.4.1

- Reduced chat persistence pressure by coalescing burst saves while keeping the
  leading write immediate and flushing pending state when the page is hidden or
  unloaded.
- Reduced frontend DOM churn by coalescing high-frequency content renders into
  one browser animation-frame render while keeping normal UI renders immediate.
- Improved System Health performance by probing local services concurrently and
  sharing near-simultaneous health reads through a short-lived defensive cache.
- Reduced durable media-queue writes by ignoring unchanged native poll results
  and throttling progress-only persistence while keeping status, errors, native
  IDs, results, cancellation, and terminal transitions immediately durable.
- Added focused regression tests for chat performance coalescing, System Health
  caching, and media-queue persistence behavior.

## v1.4.0

- Added persistent local memory with semantic retrieval, consolidation,
  lifecycle handling, privacy cleanup, a Memory Manager, and a Context
  Inspector for debugging retrieved memories.
- Added System Health & Self-Healing with live service status, restart controls,
  stuck media-job detection, conservative retry/recovery, and copyable
  diagnostics.
- Improved image generation workflows with reliable queued-job recovery,
  regenerate actions, selectable 1–6 image outputs, grouped variant galleries,
  per-variant selection/download/enhancement actions, and localized controls.
- Improved speech/read-aloud reliability, media progress handling, frontend
  recovery, and several streaming/queue regressions discovered during local use.
- Added a central VERSION file, `/api/version`, build revision reporting, and
  version display in the System Health interface.

## v1.3.0

- Added the Shorts/Media Composer pipeline with planning, agent routing, local
  TTS, music-aware FFmpeg composition, video orchestration, progress UI, and
  end-to-end test coverage.
- Added Shorts Studio v2 scene editing with durable revisions, selectable voice
  and speaking speed, reusable scene media, and targeted scene regeneration.
- Added visual consistency mode for newly planned multi-scene Shorts: persisted
  visual bibles, Qwen Image keyframes, LTX image-to-video handoff, adjustable
  character/style continuity, and a first-scene character anchor that uses the
  local Qwen Image Edit model when available while retaining a safe keyframe
  generation fallback.
- Added word-timed animated Shorts captions: the generated voiceover is aligned
  locally with Whisper word timestamps, compact phrase cards highlight the
  currently spoken word, alignment metadata is cached per durable Shorts job,
  and scene-timed subtitles remain an automatic fallback when alignment is not
  available.

## v1.2.1

- Fixed internationalization for media generation quality dialogs, runtime
  status labels, and video generation progress.
- Updated media UI tests for the localized English-default interface.
- Restored the GitHub Actions translation and JSON validation pipeline.

## v1.2.0

- Added Qwen Image 2.1 generation through MLX-Serve, including LoRA support,
  improved prompt routing, model-aware image quality profiles, and automatic
  native render sizing.
- Added local LTX 2.5 text-to-video and image-to-video generation with preview,
  selectable image/video formats, duration-aware controls, and LTX-specific
  quality profiles.
- Added a runtime coordinator for chat, image, and video workloads, including
  automatic image-to-video handoff and restoration of shared runtime resources.
- Added router-based media preflight so the generation modal and selected
  options follow the resolved image, image-edit, video, or chat target.
- Migrated RAG embeddings to Qwen3 Embeddings through the shared MLX-Serve
  runtime.
- Improved generation progress, cancellation and reload recovery, image-to-video
  workflows, modal behavior, routing reliability, and local runtime controls.

## v1.1.0

- Central AgentRuntime with ModelProvider, ToolRegistry, PermissionEngine, and a RunContext that binds workspaces and selected resources to each run.
- Approval and resume for controlled tool calls; central chat routing to the runtime.
- Runtime tools for workspace files and coding, controlled shell and Git operations, web research, vision, images, and documents.
- Role-based model selection for chat, agent, coding, vision, image, and embeddings, with BGE-M3 as a compatible embedding role.
- Local MLX end-to-end validation completed for the release scope.
