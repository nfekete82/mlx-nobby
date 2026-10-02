"""Pre-production API, installed alongside the existing Shorts Studio routes."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from agent import shorts_drafts, shorts_jobs
from agent.shorts_planner import quality_capabilities
from agent.shorts_composer import library_tracks, library_path


class DraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: dict | None = None
    chat_id: str = Field(default="shorts-studio", min_length=1, max_length=200)
    source_job_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_count: int | None = Field(default=None, ge=1, le=60)


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force_scene_id: str | None = None


class BriefingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=12000)
    chat_id: str = Field(min_length=1, max_length=200)


def model_provider():
    from agent.app import agent_model_provider
    return agent_model_provider()


def checked(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "Short draft/job not found") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409 if "reload before saving" in str(exc) else 400, str(exc)) from exc


def install_routes(app):
    if any(getattr(r, "path", None) == "/api/shorts/drafts" for r in app.routes):
        return
    first_new_route = len(app.router.routes)

    @app.post("/api/shorts/plan", status_code=201)
    def briefing(request: BriefingRequest):
        from agent.shorts_planner import plan_short
        try:
            project = plan_short(request.prompt, model_provider(), constraints={"schema_version": 2})
            project.briefing = request.prompt
            return {"draft": checked(shorts_drafts.save_draft, project.model_dump(mode="json"), chat_id=request.chat_id, normalization_warnings=project._normalization_warnings)}
        except RuntimeError as exc:
            raise HTTPException(502, "Die Szenenplanung konnte nicht abgeschlossen werden. Bitte erneut versuchen.") from exc

    @app.get("/api/shorts/capabilities")
    def capabilities():
        return {"qualities": quality_capabilities(), "music": library_tracks(shorts_jobs.MUSIC_DIRECTORY),
                "sfx": library_tracks(shorts_jobs.MUSIC_DIRECTORY.parent / "sfx"),
                "transitions": ["cut", "fade", "fadeblack", "fadewhite", "flash"]}

    @app.get("/api/shorts/drafts")
    def drafts():
        return {"drafts": shorts_drafts.list_drafts()}

    @app.post("/api/shorts/drafts", status_code=201)
    def create(request: DraftWrite):
        return {"draft": checked(shorts_drafts.save_draft, request.project, chat_id=request.chat_id,
                                  source_job_id=request.source_job_id)}

    @app.get("/api/shorts/drafts/{draft_id}")
    def get(draft_id: str):
        return {"draft": checked(shorts_drafts.get_draft, draft_id)}

    @app.put("/api/shorts/drafts/{draft_id}")
    def save(draft_id: str, request: DraftWrite):
        if request.project is None:
            raise HTTPException(400, "project required")
        return {"draft": checked(shorts_drafts.save_draft, request.project, draft_id=draft_id,
                                  expected_version=request.expected_version)}

    @app.delete("/api/shorts/drafts/{draft_id}")
    def delete(draft_id: str):
        return checked(shorts_drafts.delete_draft, draft_id)

    @app.post("/api/shorts/drafts/{draft_id}/duplicate", status_code=201)
    def duplicate(draft_id: str):
        return {"draft": checked(shorts_drafts.duplicate_draft, draft_id)}

    @app.post("/api/shorts/drafts/{draft_id}/plan")
    def plan(draft_id: str, request: PlanRequest):
        try:
            return {"draft": checked(shorts_drafts.plan_draft, draft_id, model_provider(),
                                     scene_count=request.scene_count)}
        except RuntimeError as exc:
            raise HTTPException(502, "Die Szenenplanung konnte nicht abgeschlossen werden. Bitte erneut versuchen.") from exc

    @app.post("/api/shorts/drafts/{draft_id}/render", status_code=202)
    def render(draft_id: str, request: RenderRequest):
        return {"job": checked(shorts_drafts.render_draft, draft_id, force_scene_id=request.force_scene_id)}

    @app.post("/api/shorts/drafts/{draft_id}/scenes/{scene_id}/improve")
    def improve(draft_id: str, scene_id: str):
        from agent.model_provider import ModelRequest
        draft = checked(shorts_drafts.get_draft, draft_id)
        scene = next((s for s in draft["project"]["scenes"] if s["id"] == scene_id), None)
        if scene is None:
            raise HTTPException(404, "scene not found")
        response = model_provider().complete(ModelRequest(messages=[
            {"role": "system", "content": "Improve only the visual LTX video prompt. Return plain English prompt, no explanation or markdown. Preserve action, subject and camera. No captions, narration or transitions."},
            {"role": "user", "content": f"Briefing: {draft['project']['briefing']}\nDescription: {scene['description']}\nCamera: {scene['camera']}\nPrompt: {scene['video_prompt']}"}],
            max_tokens=600, temperature=0.1, role="agent"))
        prompt = str(response.text).strip()
        if not prompt or len(prompt) > 4000:
            raise HTTPException(502, "invalid improved prompt")
        scene["video_prompt"] = prompt
        return {"draft": checked(shorts_drafts.save_draft, draft["project"], draft_id=draft_id,
                                  expected_version=draft["version"])}

    @app.get('/api/shorts/drafts/{draft_id}/preflight')
    def preflight(draft_id: str):
        from agent.shorts_preflight import preflight_project
        from agent.shorts_planner import ShortProject
        draft = checked(shorts_drafts.get_draft, draft_id)
        project = ShortProject.model_validate(draft['project'], context={'draft': True})
        try:
            return preflight_project(project)
        except ValueError as exc:
            return {'available': False, 'message': str(exc), 'warnings': [], 'models': getattr(exc, 'models', [])}

    @app.get("/api/shorts/library/{kind}/{track:path}")
    def audio(kind: str, track: str, request: Request):
        if kind not in {"music", "sfx"}:
            raise HTTPException(404, "library not found")
        root = shorts_jobs.MUSIC_DIRECTORY if kind == "music" else shorts_jobs.MUSIC_DIRECTORY.parent / "sfx"
        path = checked(library_path, root, track)
        return FileResponse(path)

    @app.get("/api/shorts/jobs/{job_id}/scenes/{scene_id}/{kind}")
    def media(job_id: str, scene_id: str, kind: str):
        job = checked(shorts_jobs.get_short_job, job_id)
        key = {"video": "scene_results", "keyframe": "keyframe_results"}.get(kind)
        if not key:
            raise HTTPException(404, "media not found")
        result = next((r for r in job.get(key, []) if r.get("scene_id") == scene_id and r.get("status") == "completed"), None)
        if not result:
            raise HTTPException(404, "scene media not ready")
        from pathlib import Path
        if not shorts_jobs.valid_media_file(result.get("path")):
            raise HTTPException(404, "scene file missing")
        return FileResponse(Path(result["path"]))

    # The legacy single-segment download route must not swallow the static
    # drafts/capabilities GET paths. Entrypoints install these routes after app.py.
    added = app.router.routes[first_new_route:]
    del app.router.routes[first_new_route:]
    legacy_index = next((i for i, route in enumerate(app.router.routes)
                         if getattr(route, "path", None) == "/api/shorts/{job_id}"),
                        len(app.router.routes))
    app.router.routes[legacy_index:legacy_index] = added
