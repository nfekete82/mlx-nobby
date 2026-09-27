"""Revision helpers for the Shorts Studio workflow.

A revision creates a new durable job instead of mutating a completed source job.
Unchanged completed scene videos are reused; only scenes whose visual prompt is
changed (or explicitly forced) are regenerated. Narration-only edits therefore
reuse every video while producing fresh TTS, subtitles and final composition.
"""

from copy import deepcopy

from agent import shorts_jobs
from agent.shorts_planner import ShortProject


def _scene_index(project: ShortProject, scene_id: str) -> int:
    value = str(scene_id or "").strip()
    for index, scene in enumerate(project.scenes):
        if scene.id == value:
            return index
    raise ValueError("short scene not found")


def _completed_scene_results(job):
    return {
        str(result.get("scene_id")): deepcopy(result)
        for result in job.get("scene_results", [])
        if result.get("status") == "completed" and result.get("path")
    }


def create_scene_revision(
    source_job_id,
    scene_id,
    *,
    narration=None,
    video_prompt=None,
    force_regenerate_video=False,
    voice=None,
    voice_speed=None,
):
    """Create a new Shorts job from an existing job with one scene revised.

    The source job remains immutable. Passing only ``narration`` reuses all
    completed videos. Changing ``video_prompt`` or setting
    ``force_regenerate_video`` invalidates that scene's video so the normal
    durable worker regenerates only that scene.
    """
    source = shorts_jobs.get_short_job(source_job_id)
    project = ShortProject.model_validate(source["project"])
    index = _scene_index(project, scene_id)

    if narration is None and video_prompt is None and not force_regenerate_video and voice is None and voice_speed is None:
        raise ValueError("short revision requires a change")

    project_data = project.model_dump(mode="json")
    scene_data = dict(project_data["scenes"][index])

    if narration is not None:
        scene_data["narration"] = str(narration).strip()
    if video_prompt is not None:
        scene_data["video_prompt"] = str(video_prompt).strip()
    project_data["scenes"][index] = scene_data

    if voice is not None:
        project_data["voice"] = str(voice).strip() or None
    if voice_speed is not None:
        project_data["voice_speed"] = voice_speed

    revised_project = ShortProject.model_validate(project_data)
    revised = shorts_jobs.create_short_job(
        revised_project,
        chat_id=source["chat_id"],
        chat_revision=source.get("chat_revision", 0),
    )

    reused = _completed_scene_results(source)
    invalidate_video = force_regenerate_video or video_prompt is not None
    if invalidate_video:
        reused.pop(revised_project.scenes[index].id, None)

    ordered_results = [
        reused[scene.id]
        for scene in revised_project.scenes
        if scene.id in reused
    ]
    completed_ids = set(reused)
    current_scene = next(
        (
            scene_index
            for scene_index, scene in enumerate(revised_project.scenes)
            if scene.id not in completed_ids
        ),
        len(revised_project.scenes),
    )

    return shorts_jobs._update_job(
        revised["id"],
        parent_job_id=source["id"],
        revision_scene_id=revised_project.scenes[index].id,
        revision_kind=(
            "video"
            if invalidate_video
            else "audio"
        ),
        scene_results=ordered_results,
        current_scene=current_scene,
        active_video_job_id=None,
        tts_status="pending",
        tts_path=None,
        tts_started_at=None,
        tts_finished_at=None,
        tts_metadata=None,
        subtitles_path=None,
        compose_status="pending",
        final_path=None,
        compose_started_at=None,
        compose_finished_at=None,
        status="queued",
        phase="queued",
        started_at=None,
        finished_at=None,
        error=None,
        cancel_requested=False,
    )
