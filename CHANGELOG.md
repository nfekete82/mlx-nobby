# Changelog

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
