# Shorts Studio

## User workflow

1. Describe the Short in chat: topic, duration, style and platform.
2. Nobby plans scenes, saves a server draft and ends the chat turn. **Planning
   does not produce images or videos.**
3. Open that draft from its chat message, or create/select a draft in Studio.
4. Review briefing, scenes, narration and visible captions. Plan again if needed.
5. Optionally open Expert Settings for camera, continuity, voice, transitions,
   local music and SFX.
6. Select **Render Short** to start production.
7. Follow the selected job in History. Open/download the completed video.
   Failed/cancelled jobs offer Retry; completed projects offer Duplicate;
   active jobs display Cancel (see the web limitation below).

## Draft lifecycle

Drafts persist atomically in `~/.config/mlx-web/shorts/drafts.json`. Each has
`id`, `kind=shorts_draft`, `project`, `chat_id`, `source_job_id`, `created_at`,
`updated_at`, `version` and `warnings`. New drafts start at version 1; every save
increments it. PUT requires the current `expected_version`; omitted/stale values
produce 409. Reload before saving again. Updates retain the original chat/source.
Plan and Improve read a version then save against it, so concurrent edits can
also produce 409. Render reads the stored draft; it has no version argument.

Create without a project supplies a version-2 default project. A
`source_job_id` must identify a completed job and allows later rendering as a
new project revision. Duplicate retains that source link and creates a new ID.
Draft deletion leaves production history/media intact. Corrupt draft data is
not silently replaced with an empty store.

Version 1 remains readable with narration-to-caption fallback and legacy global
voiceover. Version 2 separates narration/captions and adds scene description,
camera, voice switches, transitions, music overrides and SFX. Projects reject
unknown fields. Draft validation allows unfinished visual prompts/timelines;
production requires unique scene IDs, nonempty video prompts, profile-supported
scene durations and an exact sum to project duration.

## Production lifecycle

The agent owns jobs and `shorts/jobs.json`; the web proxies its APIs. Jobs move
through `queued`, `running`, `video_completed`, `tts_completed` and then
`completed`, or terminate as `failed`/`cancelled`. Phase/progress and child image,
video, TTS and compose state describe the current stage. Startup resumes active
jobs without a cancellation request. This differs from browser reload recovery,
which merely reselects/polls a server job.

Consistency mode creates image keyframes and LTX I2V; otherwise scenes use T2V.
A compatible generator is required for missing keyframes. If character edit
support is unavailable, visual-bible T2I is used with `character_anchor_fallback`.
The capability/readiness checks inspect enabled, available models; they do not
install or download them. `fast`, `standard`, `quality` use the existing LTX
profiles; fetch capabilities rather than hardcoding allowed durations.

## Retry and revisions

Render, scene revision and Retry create new jobs; none is idempotent. Source
jobs remain unchanged. `parent_job_id` links revisions; History groups this
chain and returns the latest revision per root, with `revision_count`.
There is no dedicated revision-group route: fetch a selected job and its parent
IDs when the full chain is needed.

Retry is restricted to failed/cancelled jobs. Duplicate in History creates a
draft from a completed job; it does not render immediately. Cancel uses the
agent unified job queue route, not a Shorts-specific `/cancel` route.
A terminal job cannot be cancelled (409). **Known web limitation:** History/Queue
buttons request `/api/system/job-queue/shorts/{job_id}/cancel`, but the current
web entrypoint does not install that proxy and returns 404. The queue list proxy
is missing too. This documentation change does not repair product routes; use
the local agent API for cancellation until that separate bug is fixed.

## Media reuse

Only completed, existing regular nonempty files are reused; no codec probe is
performed. Visual/camera/duration changes invalidate affected media, quality
changes invalidate videos, and consistency/character-anchor changes can
invalidate dependent scenes. Narration, captions and audio-only edits preserve
video. `force_scene_id` requests regeneration of the chosen scene.

Retry checks retained media before image readiness: completed videos need no
image generation or LTX rendering; retained keyframes can feed missing video.
Compose retry also retains valid completed TTS. Missing/failed/empty media is
regenerated. A draft's preflight does not include source-media reuse; render
makes the final readiness decision after comparing the source project.

## Voiceover / captions

Version-2 TTS runs only for voiced scenes with narration and is placed on the
scene timeline. There is 0.05 s measurement/encoding tolerance and at most 1.15×
per-scene `atempo` compression. Longer recordings produce `VOICEOVER_TOO_LONG`
with scene ID/number and actual/allowed durations; shorten narration or adjust
voice speed. This does not rewrite narration or change global voice speed.
Completed videos remain reusable. V2 uses scene-timed captions; V1 retains
word-aligned captions.

## Music / SFX / transitions

Only local library tracks are used. Capabilities lists music/SFX and supported
transitions: `cut`, `fade`, `fadeblack`, `fadewhite`, `flash`. Scene overrides,
volume, fades, offsets and voice ducking keep the exact project timeline.
Optional presentation/audio settings are normalized with warning codes; explicit
voice and quality choices are preserved. Enabled SFX requires a track at render.

## Error handling

Public status/history exposes safe errors: `error_code`, `error_stage`, scene
metadata where applicable, provider/model, `error_message`, `error_detail_safe`.
The legacy `error` field remains. Internal details stay in the local store;
planner failures return a safe 502. Browser UI displays known localized timing
messages or safe stage/generic errors, not arbitrary HTTP/exception text.

## API reference

Routes below are the installed public contracts. Each method is listed
separately for automated route coverage. Path placeholders use actual router
names. All paths are relative to their service (agent normally 8010; web 8090).

| Method | Agent path | Web path | Request → response | Success agent / web |
| --- | --- | --- | --- | --- |
| POST | `/api/shorts/plan` | `/api/mlx/shorts/plan` | Briefing → `{draft}` | 201 / 201 |
| GET | `/api/shorts/capabilities` | `/api/mlx/shorts/capabilities` | None → `{qualities, music, sfx, transitions}` | 200 / 200 |
| GET | `/api/shorts/drafts` | `/api/mlx/shorts/drafts` | None → `{drafts}` (newest updated first) | 200 / 200 |
| POST | `/api/shorts/drafts` | `/api/mlx/shorts/drafts` | DraftWrite → `{draft}` | 201 / 201 |
| GET | `/api/shorts/drafts/{draft_id}` | `/api/mlx/shorts/drafts/{draft_id}` | None → `{draft}` | 200 / 200 |
| PUT | `/api/shorts/drafts/{draft_id}` | `/api/mlx/shorts/drafts/{draft_id}` | DraftWrite with project/version → `{draft}` | 200 / 200 |
| DELETE | `/api/shorts/drafts/{draft_id}` | `/api/mlx/shorts/drafts/{draft_id}` | None → `{deleted: true}` | 200 / 200 |
| POST | `/api/shorts/drafts/{draft_id}/duplicate` | `/api/mlx/shorts/drafts/{draft_id}/duplicate` | None → `{draft}` | 201 / 200 |
| POST | `/api/shorts/drafts/{draft_id}/plan` | `/api/mlx/shorts/drafts/{draft_id}/plan` | PlanRequest → `{draft}` | 200 / 200 |
| POST | `/api/shorts/drafts/{draft_id}/scenes/{scene_id}/improve` | `/api/mlx/shorts/drafts/{draft_id}/scenes/{scene_id}/improve` | None → `{draft}`; visual prompt only | 200 / 200 |
| GET | `/api/shorts/drafts/{draft_id}/preflight` | `/api/mlx/shorts/drafts/{draft_id}/preflight` | None → `{available, warnings, models}`, `message` on failure | 200 / 200 |
| POST | `/api/shorts/drafts/{draft_id}/render` | `/api/mlx/shorts/drafts/{draft_id}/render` | RenderRequest → `{job}` | 202 / 200 |
| GET | `/api/shorts-jobs` | `/api/mlx/shorts-jobs` | `limit` query (1–200, default 50) → `{projects, total, limit}` | 200 / 200 |
| GET | `/api/shorts/jobs/{job_id}` | `/api/mlx/shorts-jobs/{job_id}` | None → public job status | 200 / 200 |
| POST | `/api/shorts-jobs/{job_id}/retry` | `/api/mlx/shorts-jobs/{job_id}/retry` | None → `{job}` | 202 / 202 |
| POST | `/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise` | `/api/mlx/shorts-jobs/{job_id}/scenes/{scene_id}/revise` | SceneRevisionRequest → `{job}` | 202 / 202 |
| DELETE | `/api/shorts-jobs/failed` | `/api/mlx/shorts-jobs/failed` | None → cleanup summary | 200 / 200 |
| DELETE | `/api/shorts-jobs/{job_id}` | `/api/mlx/shorts-jobs/{job_id}` | None → project deletion summary | 200 / 200 |
| POST | `/api/system/job-queue/{kind}/{job_id}/cancel` | — | Set `kind=shorts`; no body → `{ok, kind, job}` | 200 / — |
| GET | `/api/shorts/{job_id}` | `/api/mlx/shorts/{job_id}` | Optional `download=true` → completed MP4 | 200 / 200 |
| GET | `/api/shorts/jobs/{job_id}/scenes/{scene_id}/{kind}` | `/api/mlx/shorts/jobs/{job_id}/scenes/{scene_id}/{kind}` | `kind=video` or `keyframe` → completed scene file | 200 / 200 |
| GET | `/api/shorts/library/{kind}/{track:path}` | `/api/mlx/shorts/library/{kind}/{track:path}` | `kind=music` or `sfx`; relative track → local audio file | 200 / 200 |

Web draft actions use a generic action route and return 200 for successful
render/duplicate even when the agent returns 202/201. An unknown action returns
404. There is no installed web proxy for the unified queue/cancellation paths.
Static drafts/capabilities and failed-cleanup routes precede parameter catch-alls.

### Request schemas

- **Briefing:** required `prompt` (1–12000 characters), `chat_id` (1–200).
- **DraftWrite:** optional `project` object (default project on create), `chat_id`
  (default `shorts-studio`, 1–200), `source_job_id`, `expected_version` (integer
  ≥1). PUT requires a non-null project and matching version. Chat/source fields
  are retained on update, not rebound. Empty project on create uses the default.
- **PlanRequest:** optional `scene_count` (integer 1–60); otherwise current count.
- **RenderRequest:** optional `force_scene_id`, which must exist in the project.
- **SceneRevisionRequest:** optional `narration`/`video_prompt` (1–4000), `voice`
  (1–80 letters/digits/underscore/hyphen), `voice_speed` (0.5–2),
  `force_regenerate_video`/`force_regenerate_keyframe` (default false),
  `consistency_mode`, `character_consistency`, `style_consistency`,
  `style_strength` (0–1). Requires a change/regeneration option. This older
  request schema ignores unknown fields; draft/briefing/plan/render reject them.

Send JSON objects for create/plan/render/update/revise (`{}` for defaults).
The web action proxy permits an omitted body and substitutes `{}`. Draft and
scene operations never accept arbitrary client filesystem paths.

**Project schema:** `ShortProject` in `agent/shorts_planner.py` is authoritative.
Required fields are `title` (1–200), `duration` (5–300), `scenes` (1–60). Scene
requires `id` (1–64 safe identifier) and supported integer `duration`.
`aspect_ratio` is `9:16`; quality is `fast|standard|quality`; language is a
2-letter lowercase code; voice speed 0.5–2. Optional fields include briefing,
style preset, visual bible/consistency, voice/music/subtitles, caption settings
and scene narration/caption/camera/video prompt/transition/music/SFX. Nested
schemas reject unknown fields. Use capabilities and the generated Pydantic
schema for complete nested bounds rather than duplicating them in clients.

### Response schemas and errors

Draft envelopes and fields are described above. Job creation/revision responses
contain the durable job (`id`, `kind`, `chat_id`, `run_id`, `chat_revision`,
`project`, `status`, `phase`, scene/keyframe results, child-job IDs, TTS/music/
compose state, timestamps, cancellation and revision metadata). Status GET
returns the existing tool-result envelope with `data.job`, status and artifacts;
`data.job` includes progress, and completed results add `data.video` plus the
artifact/download URL. History summaries include root/
parent IDs, revision count, title, quality, voice, scene count, progress,
timestamps, warnings and safe diagnostics; they are not complete projects.

Project DELETE removes the entire inactive revision chain and its Shorts-owned
job directories. Its result contains `deleted`, `root_job_id`, `deleted_jobs`,
`deleted_job_ids`, `cleanup_errors`. Failed cleanup removes chains whose latest
revision failed and returns `deleted_projects`, `deleted_jobs`,
`deleted_job_ids`, `skipped_active`, `cleanup_errors`. Active chains are protected.

GETs are read-only; all production/planning/duplicate POSTs are non-idempotent.
PUT is version guarded: repeating a successful request with the old version is
409. DELETE is destructive: repeating draft/project deletion normally gives
404, while bulk failed cleanup can be repeated. Cancellation is non-idempotent
at the response level: a subsequent terminal-job cancel is 409.

Agent errors: 422 for request-schema validation, 400 for invalid project/options/
readiness, 404 for missing drafts/jobs/media, 409 for stale draft versions or
active project deletion/terminal cancellation, 502 for failed planning/invalid
improved prompt. Preflight readiness failure is a **200** with `available=false`.
Unsupported/missing scene media and invalid library kinds return 404; file
responses support Range (206) when accepted by the underlying FileResponse.
Library traversal, missing tracks and unsupported audio extensions produce 400;
use the capabilities list rather than guessed track names.
The web forwards agent HTTP status for JSON errors, reports invalid action JSON
as 400 and an unreachable agent as 503; media proxies report safe unavailability.
Unexpected service/store failures can produce 5xx and are not guaranteed 400.

## Browser behavior

Edits autosave after one second. Saves and navigation are serialized: switching
Draft/History/job, closing and rendering flush pending edits. A failed save
preserves the editor and blocks navigation. Leaving the browser page with
unsaved changes triggers its standard confirmation. Source previews remain
visible until replacement production completes. Selection tokens prevent late
poll/retry/duplicate replies from replacing newer selections.

History shows selected job status, progress, scene counts, elapsed time and
previews; the legacy viewer retains scene revision actions. Editor/History adapt
to narrow viewports; expert options stay collapsible. Copy is DE/EN through
`frontend/i18n/shorts-studio.json` and the main chat translations.

## Troubleshooting

- No production after chat planning: expected; open the draft and select Render.
- Render validation fails: complete scene prompts and match the chosen quality's
  durations and project timeline.
- Provider readiness fails: check available/enabled local image models and
  [MFLUX compatibility](MFLUX_COMPATIBILITY.md); do not assume an installed model.
- Voiceover too long: shorten the identified scene's narration or increase speed.
- Save conflict: reload the latest draft before applying edits again.
- Service problems: start with `mlx doctor`; see [runtime/update commands](../README.md#mlx-manager).

Route implementations: `agent/shorts_draft_routes.py`,
`agent/shorts_studio_routes.py`, `agent/app.py`, `agent/service_proxy.py` and their
web counterparts. `tests/test_documentation.py` checks table coverage against
installed route modules and legacy/proxy declarations.
