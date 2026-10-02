# Shorts Studio

The agent owns planning, drafts, durable production jobs, revisions and media.
The web backend proxies these contracts. The pre-production editor and History
use them directly; existing Studio scene revisions remain supported.

## Projects and planning

New plans use `schema_version=2`. Version 1 remains readable without a migration,
including the narration-to-caption fallback and the legacy project voiceover.
Version 2 adds independent scene narration/captions, camera and description,
scene voice switches, transitions, music overrides and local SFX. `quality`
selects the existing `fast`, `standard` or `quality` LTX profile. Scene durations
must match that profile and sum exactly to the project duration.

`shorts_normalization.py` repairs optional presentation settings, resolves local
music/SFX availability and returns warning codes. It preserves explicit voice and
quality settings. Draft validation permits unfinished visual prompts; rendering
requires a complete valid production plan. Unknown project fields remain rejected
by the existing strict schema; additive metadata on persisted jobs is preserved.

## Routes

Agent routes use the paths below. The web proxies `/api/shorts/...` as
`/api/mlx/shorts/...`; job-management routes use `/api/mlx/shorts-jobs/...`.

| Method | Agent path | Result |
| --- | --- | --- |
| POST | `/api/shorts/plan` | Plan from `prompt` and `chat_id`, save a draft |
| GET | `/api/shorts/capabilities` | Quality profiles, local music/SFX, transitions |
| GET / POST | `/api/shorts/drafts` | List / create drafts |
| GET / PUT / DELETE | `/api/shorts/drafts/{id}` | Read / save / delete a draft |
| POST | `/api/shorts/drafts/{id}/duplicate` | Copy a draft |
| POST | `/api/shorts/drafts/{id}/plan` | Plan with optional `scene_count` |
| POST | `/api/shorts/drafts/{id}/scenes/{scene_id}/improve` | Improve only the visual prompt |
| GET | `/api/shorts/drafts/{id}/preflight` | Inspect image-provider readiness |
| POST | `/api/shorts/drafts/{id}/render` | Validate and start a job/revision; optional `force_scene_id` |
| POST | `/api/shorts/jobs/{id}/scenes/{scene_id}/revise` | Existing scene revision contract |
| POST | `/api/shorts-jobs/{id}/retry` | New revision of a failed/cancelled job |
| GET | `/api/shorts/jobs/{id}/scenes/{scene_id}/{kind}` | Completed scene `video` or `keyframe` |
| GET | `/api/shorts/library/{kind}/{track}` | Local `music` or `sfx` |

Static draft/capability routes precede the legacy `/{job_id}` download route.
Planning and saving never enqueue image/video jobs. `drafts.json` uses atomic
writes and optimistic versions: PUT requires the current `expected_version`,
otherwise HTTP 409 requests a reload. A corrupt store is never silently replaced.
The existing `jobs.json`, final downloads and grouped revision history remain.

## Production and reuse

Consistency uses existing image keyframes followed by LTX I2V; otherwise the
worker uses T2V. An unavailable compatible image-edit provider falls back to
visual-bible T2I with a warning. GROUP-1 provider compatibility stays authoritative.

Revisions preserve completed media only when its path names an existing regular,
nonempty file. Visual/camera/duration changes invalidate affected scene media;
quality changes invalidate videos, and character-anchor/consistency changes can
invalidate dependent scenes. Narration, captions and audio-only changes preserve
videos. Source jobs remain immutable.

Retry validates media before requesting image readiness. Complete videos need no
Image service or LTX render. A retained keyframe can feed the missing video
without image generation. Missing videos and missing keyframes still require a
compatible generator. A compose retry also retains completed nonempty TTS;
failed/missing/empty TTS is generated again. Retry creates a new job and is not an
idempotent operation. File validation is deliberately inexpensive, without a
full codec probe.

Version-2 TTS runs only for voiced scenes with narration. FFmpeg places those
segments on the scene timeline. `VOICEOVER_DURATION_TOLERANCE_SECONDS` allows
0.05 seconds of measurement/encoding drift; beyond that,
`MAX_VOICEOVER_TIME_COMPRESSION=1.15` permits per-scene `atempo` adjustment.
A 5.4-second recording fits a 5-second scene. Greater compression produces
`VOICEOVER_TOO_LONG`, scene ID/number and actual/allowed durations. Completed
videos remain available. This never rewrites narration, changes global
`voice_speed`, or changes Qwen-TTS/LTX models.

The composer supports local music/SFX, volume/fades and transitions while keeping
the exact project timeline. Version 2 uses scene-timed captions; version 1 retains
the existing word-aligned caption path.

## Diagnostics

Failures expose `error_code`, `error_stage`, scene metadata where relevant,
provider/model, `error_message` and `error_detail_safe`. Known timing failures are
specific; unknown failures use a safe stage message. Raw internal errors stay in
the local job store, while public job/history errors and planner HTTP 502 replies
are sanitized. Existing clients can continue to use the `error` field.


## Browser workflow

Open Shorts Studio to create a draft or select an existing draft or History item.
Chat routes new Shorts requests to the planning API, stores a draft reference in
the assistant message and ends the turn. It does not start image/video production.
The message button reopens that server draft. Selected voice settings are passed
to planning through the existing Studio voice instruction.

The editor separates planning from production: edit title/briefing, style,
quality, narration and visible captions, then plan and explicitly select Render
Short. Expert mode exposes scene order/duration, camera/video prompts, voice and
speed, character/style continuity, transitions and local music/SFX. All fields
use the existing backend schema. Source previews show the previous render until
new production finishes. For source revisions the render endpoint decides image
readiness after comparing reusable media; its draft preflight summary alone does
not block compositor-only edits.

Edits autosave after one second. Saves and navigation are serialized: History,
draft/job switches, closing and rendering flush pending changes before continuing.
A failed save preserves the editor and visibly blocks navigation. Obsolete timer
callbacks cannot save a newly selected draft. Leaving the browser page with
unsaved changes triggers its standard leave-page confirmation. Explicit draft
deletion remains a delete operation.

History offers status/progress, scene counts, elapsed time, previews and explicit
job selection, plus retry, completed-project duplication and active-job cancel.
Selection tokens prevent older fetch/poll/retry/duplicate responses from replacing
a newer selection. Retry opens the new backend revision; duplication creates a
server draft. Legacy scene revisions remain available in the job viewer.

Known `VOICEOVER_TOO_LONG` metadata produces a localized duration message in
German/English. Unknown error texts and HTTP details are never displayed directly;
stage-specific or generic safe messages remain. Editor labels use the shared
`shorts-studio.json` translations. Editor and History panels adapt to narrow
viewports; expert options remain in collapsible sections.
