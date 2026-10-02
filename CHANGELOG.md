# Changelog

## Unreleased

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
