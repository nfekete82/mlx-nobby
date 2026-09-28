"""Visual-consistency helpers for Shorts Studio.

Consistency mode creates one managed keyframe per scene and then hands that
image to LTX image-to-video.  The visual bible is deliberately persisted in the
ShortProject so scene revisions remain deterministic and resumable.
"""

from agent.shorts_planner import ShortProject


KEYFRAME_WIDTH = 576
KEYFRAME_HEIGHT = 1024
KEYFRAME_QUALITY = "standard"


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def visual_bible_text(project):
    """Return a bounded continuity description, with a safe legacy fallback."""
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)

    bible = project.visual_bible
    parts = []
    if bible is not None:
        if project.style_consistency:
            for label, value in (
                ("Visual style", bible.style),
                ("Color palette", bible.palette),
                ("Lighting and camera", bible.camera),
                ("Environment", bible.environment),
            ):
                if value:
                    parts.append(f"{label}: {_clean(value, 500)}")
        if project.character_consistency and bible.character:
            parts.append(f"Recurring character: {_clean(bible.character, 600)}")
        if bible.continuity_rules:
            rules = "; ".join(_clean(rule, 240) for rule in bible.continuity_rules[:8])
            parts.append(f"Continuity rules: {rules}")

    if not parts:
        parts.append(f"Project identity: {_clean(project.title, 300)}")
        if project.style_consistency:
            parts.append("Keep one coherent cinematic visual language across every scene.")
        if project.character_consistency:
            parts.append("Preserve recurring people, wardrobe and identifying features across scenes.")

    return "\n".join(parts)[:1800]


def scene_keyframe_prompt(project, scene, scene_index=0):
    """Build a vertical still-image prompt that preserves project continuity."""
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)

    strength = round(project.style_strength * 100)
    bible = visual_bible_text(project)
    scene_text = _clean(scene.video_prompt, 900)
    prompt = (
        "Create a photorealistic cinematic 9:16 keyframe for a short video.\n"
        f"Scene {scene_index + 1}: {scene_text}\n\n"
        "Continuity bible:\n"
        f"{bible}\n\n"
        f"Continuity strength: {strength}%. "
        "Treat the continuity bible as identity constraints, not optional inspiration. "
        "Keep recurring subjects, wardrobe, architecture, palette, lens language and lighting "
        "consistent unless this scene explicitly requires a change. "
        "No text, captions, logos, borders or watermarks. Compose for vertical 9:16 video."
    )
    return prompt[:2000]


def keyframe_job_request(job, scene, scene_index=0):
    project = ShortProject.model_validate(job["project"])
    return {
        "operation": "generate",
        "payload": {
            "prompt": scene_keyframe_prompt(project, scene, scene_index),
            "model": "auto",
            "width": KEYFRAME_WIDTH,
            "height": KEYFRAME_HEIGHT,
            "quality": KEYFRAME_QUALITY,
            "auto_size": False,
        },
        "chat_id": job["chat_id"],
        "run_id": job["run_id"],
        "chat_revision": job["chat_revision"],
    }


def consistent_video_job_request(job, scene, keyframe_path):
    """Create an LTX I2V request from a managed scene keyframe."""
    return {
        "operation": "i2v",
        "payload": {
            "prompt": scene["video_prompt"],
            "duration": scene["duration"],
            "aspect_ratio": job["project"]["aspect_ratio"],
            "first_frame": str(keyframe_path),
            "resize_mode": "cover",
            "quality": "fast",
        },
        "chat_id": job["chat_id"],
        "run_id": job["run_id"],
        "chat_revision": job["chat_revision"],
    }
