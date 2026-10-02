"""Durable pre-production projects. Saving/planning never queues media work."""
from copy import deepcopy
import threading
import time
import uuid

from agent import batch_state, shorts_jobs
from agent.shorts_planner import ShortProject, plan_short

_lock = threading.RLock()


def _path():
    return shorts_jobs.SHORTS_DIRECTORY / "drafts.json"


def _load():
    path = _path()
    if not path.exists():
        return {}
    # A broken store must never be silently replaced by an empty one.
    import json
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid Shorts draft store")
    return value


def _save(items):
    batch_state.save_jobs(shorts_jobs.SHORTS_DIRECTORY, _path(), items)


def default_project():
    return {"schema_version": 2, "title": "Neuer Short", "duration": 20,
            "consistency_mode": True, "music_selection": "auto",
            "scenes": [{"id": f"scene-{i}", "duration": 5} for i in range(1, 5)]}


def list_drafts():
    with _lock:
        return sorted(deepcopy(list(_load().values())), key=lambda d: d["updated_at"], reverse=True)


def get_draft(draft_id):
    shorts_jobs._job_id(draft_id)
    with _lock:
        value = _load().get(draft_id)
    if value is None:
        raise KeyError("Short draft not found")
    return deepcopy(value)


def save_draft(project=None, *, draft_id=None, chat_id="shorts-studio", source_job_id=None,
               expected_version=None, normalization_warnings=None):
    from agent.shorts_normalization import normalize_short_for_available_runtime
    normalized, warnings = normalize_short_for_available_runtime(project or default_project())
    warnings = list(dict.fromkeys([*(normalization_warnings or []), *warnings]))
    value = ShortProject.model_validate(normalized, context={"draft": True})
    if source_job_id:
        source = shorts_jobs.get_short_job(source_job_id)
        if source["status"] != "completed":
            raise ValueError("only completed jobs can be edited as drafts")
    with _lock:
        items = _load()
        old = items.get(draft_id) if draft_id else None
        if draft_id and old is None:
            raise KeyError("Short draft not found")
        if old and expected_version != old["version"]:
            raise ValueError("draft changed; reload before saving")
        now = time.time()
        value = {"id": draft_id or uuid.uuid4().hex[:24], "kind": "shorts_draft",
                 "project": value.model_dump(mode="json"), "chat_id": old["chat_id"] if old else chat_id,
                 "source_job_id": old["source_job_id"] if old else source_job_id,
                 "created_at": old["created_at"] if old else now, "updated_at": now,
                 "version": old["version"] + 1 if old else 1, "warnings": warnings}
        items[value["id"]] = value
        _save(items)
    return deepcopy(value)


def delete_draft(draft_id):
    shorts_jobs._job_id(draft_id)
    with _lock:
        items = _load()
        if items.pop(draft_id, None) is None:
            raise KeyError("Short draft not found")
        _save(items)
    return {"deleted": True}


def duplicate_draft(draft_id):
    source = get_draft(draft_id)
    return save_draft(source["project"], chat_id=source["chat_id"], source_job_id=source["source_job_id"])


def plan_draft(draft_id, provider, *, scene_count=None):
    draft = get_draft(draft_id)
    p = draft["project"]
    constraints = {key: value for key, value in p.items() if key not in
                   {"scenes", "title", "visual_bible", "briefing"}}
    if p["title"] != "Neuer Short":
        constraints["title"] = p["title"]
    bible = p.get("visual_bible")
    if bible and any(bible.values()):
        constraints["visual_bible"] = bible
    constraints["scene_count"] = scene_count or len(p["scenes"])
    project = plan_short(p["briefing"], provider, constraints=constraints)
    project.briefing = p["briefing"]
    return save_draft(project.model_dump(mode="json"), draft_id=draft_id,
                      expected_version=draft["version"], normalization_warnings=project._normalization_warnings)


def render_draft(draft_id, *, force_scene_id=None):
    from agent.shorts_studio import create_project_revision
    draft = get_draft(draft_id)
    from agent.shorts_normalization import normalize_short_for_available_runtime
    data, _ = normalize_short_for_available_runtime(draft['project'])
    project = ShortProject.model_validate(data)
    from agent.shorts_preflight import preflight_project
    if force_scene_id and force_scene_id not in {scene.id for scene in project.scenes}:
        raise ValueError("short scene not found")
    if draft["source_job_id"]:
        job = create_project_revision(draft["source_job_id"], project, force_scene_id=force_scene_id, preflight=True)
        readiness = job['provider_preflight']
    else:
        readiness = preflight_project(project)
        job = shorts_jobs.create_short_job(project, chat_id=draft["chat_id"])
    job = shorts_jobs._update_job(job['id'], warnings=readiness['warnings'], provider_preflight=readiness)
    shorts_jobs.start_short_job(job["id"])
    return job
