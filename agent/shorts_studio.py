"""Revision helpers for the Shorts Studio workflow.

A revision creates a new durable job instead of mutating a completed source job.
Unchanged completed scene videos/keyframes are reused. Visual or consistency
changes invalidate only the media that must actually be regenerated. When the
first keyframe is the recurring-character anchor, changing it also invalidates
all dependent scene keyframes/videos.
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


def _completed_keyframe_results(job):
    return {
        str(result.get("scene_id")): deepcopy(result)
        for result in job.get("keyframe_results", [])
        if result.get("status") == "completed" and result.get("path")
    }


def create_scene_revision(
    source_job_id,
    scene_id,
    *,
    narration=None,
    video_prompt=None,
    force_regenerate_video=False,
    force_regenerate_keyframe=False,
    voice=None,
    voice_speed=None,
    consistency_mode=None,
    character_consistency=None,
    style_consistency=None,
    style_strength=None,
):
    """Create a new Shorts job from an existing job with one scene revised."""
    source = shorts_jobs.get_short_job(source_job_id)
    project = ShortProject.model_validate(source["project"])
    index = _scene_index(project, scene_id)

    requested = (
        narration is not None
        or video_prompt is not None
        or force_regenerate_video
        or force_regenerate_keyframe
        or voice is not None
        or voice_speed is not None
        or consistency_mode is not None
        or character_consistency is not None
        or style_consistency is not None
        or style_strength is not None
    )
    if not requested:
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
    if consistency_mode is not None:
        project_data["consistency_mode"] = consistency_mode
    if character_consistency is not None:
        project_data["character_consistency"] = character_consistency
    if style_consistency is not None:
        project_data["style_consistency"] = style_consistency
    if style_strength is not None:
        project_data["style_strength"] = style_strength

    revised_project = ShortProject.model_validate(project_data)
    if force_regenerate_keyframe and not revised_project.consistency_mode:
        raise ValueError("keyframe regeneration requires consistency mode")

    consistency_changed = any((
        consistency_mode is not None and consistency_mode != project.consistency_mode,
        character_consistency is not None and character_consistency != project.character_consistency,
        style_consistency is not None and style_consistency != project.style_consistency,
        style_strength is not None and style_strength != project.style_strength,
    ))

    revised = shorts_jobs.create_short_job(
        revised_project,
        chat_id=source["chat_id"],
        chat_revision=source.get("chat_revision", 0),
    )

    reused = _completed_scene_results(source)
    reused_keyframes = _completed_keyframe_results(source)
    selected_id = revised_project.scenes[index].id

    invalidate_video = force_regenerate_video or video_prompt is not None
    invalidate_keyframe = force_regenerate_keyframe or (
        revised_project.consistency_mode and video_prompt is not None
    )
    anchor_changed = (
        invalidate_keyframe
        and index == 0
        and revised_project.consistency_mode
        and revised_project.character_consistency
    )

    if consistency_changed or anchor_changed:
        reused = {}
        reused_keyframes = {}
    else:
        if invalidate_video or invalidate_keyframe:
            reused.pop(selected_id, None)
        if invalidate_keyframe:
            reused_keyframes.pop(selected_id, None)
        if not revised_project.consistency_mode:
            reused_keyframes = {}

    ordered_results = [
        reused[scene.id]
        for scene in revised_project.scenes
        if scene.id in reused
    ]
    ordered_keyframes = [
        reused_keyframes[scene.id]
        for scene in revised_project.scenes
        if scene.id in reused_keyframes
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

    if consistency_changed:
        revision_kind = "consistency"
    elif invalidate_keyframe:
        revision_kind = "keyframe"
    elif invalidate_video:
        revision_kind = "video"
    else:
        revision_kind = "audio"

    return shorts_jobs._update_job(
        revised["id"],
        parent_job_id=source["id"],
        revision_scene_id=selected_id,
        revision_kind=revision_kind,
        scene_results=ordered_results,
        keyframe_results=ordered_keyframes,
        current_scene=current_scene,
        active_image_job_id=None,
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
