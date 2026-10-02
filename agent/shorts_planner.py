"""Validated production plans for short-form videos."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator, ValidationInfo, PrivateAttr

from agent.model_provider import ModelProvider, ModelRequest
from agent.run_state import RunContext
from video_service import SUPPORTED_DURATIONS_BY_RESOLUTION, RESOLUTION_SIZES
from quality_profiles import resolve_video_profile


LTX_SCENE_DURATIONS = frozenset().union(*(
    durations
    for resolution, durations in SUPPORTED_DURATIONS_BY_RESOLUTION.items()
    if resolution != "preview"
))


MusicStyle = Literal["cinematic", "futuristic", "dark", "emotional", "energetic", "ambient"]


class SceneTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["cut", "fade", "fadeblack", "fadewhite", "flash"] = "cut"
    duration: float = Field(default=0.0, ge=0, le=2)

    @model_validator(mode="after")
    def valid_effect(self):
        if self.type == "cut" and self.duration != 0:
            raise ValueError("cut duration must be zero")
        if self.type != "cut" and self.duration <= 0:
            raise ValueError("fade/flash duration must be positive")
        return self


class SceneMusic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool | None = None
    style: MusicStyle | None = None
    track: str | None = Field(default=None, max_length=240)
    volume: float | None = Field(default=None, ge=0, le=1)
    start_offset: float = Field(default=0.0, ge=0, le=3600)
    fade_in: float = Field(default=0.0, ge=0, le=10)
    fade_out: float = Field(default=0.0, ge=0, le=10)
    duck_under_voice: bool = True


class SceneSfx(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    track: str | None = Field(default=None, max_length=240)
    volume: float = Field(default=0.5, ge=0, le=1)
    offset: float = Field(default=0.0, ge=0, le=300)


class CaptionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    position: Literal["bottom", "center", "top"] = "bottom"
    size: int = Field(default=54, ge=20, le=100)
    style: Literal["bold", "plain"] = "bold"


def quality_capabilities():
    result = {}
    for quality in ("fast", "standard", "quality"):
        profile = resolve_video_profile({"model_family": "ltx-2.5"}, quality)
        resolution = profile["resolution"]
        result[quality] = {**profile, "durations": sorted(SUPPORTED_DURATIONS_BY_RESOLUTION[resolution]),
                           "dimensions": list(RESOLUTION_SIZES[resolution]["9:16"])}
    return result


class ShortScene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    duration: int
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    narration: str = Field(default="", max_length=4000)
    caption: str = Field(default="", max_length=4000)
    camera: str = Field(default="", max_length=600)
    voice_enabled: bool = True
    transition: SceneTransition = Field(default_factory=SceneTransition)
    music: SceneMusic | None = None
    sfx: SceneSfx = Field(default_factory=SceneSfx)
    video_prompt: str = Field(default="", max_length=4000)

    @field_validator("duration")
    @classmethod
    def duration_supported_by_ltx(cls, value):
        if value not in LTX_SCENE_DURATIONS:
            allowed = ", ".join(str(item) for item in sorted(LTX_SCENE_DURATIONS))
            raise ValueError(f"scene duration must be one of: {allowed}")
        return value


class VisualBible(BaseModel):
    """Persisted identity/style constraints shared by every scene."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    style: str | None = Field(default=None, max_length=1200)
    character: str | None = Field(default=None, max_length=1200)
    environment: str | None = Field(default=None, max_length=1200)
    palette: str | None = Field(default=None, max_length=600)
    camera: str | None = Field(default=None, max_length=600)
    continuity_rules: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("continuity_rules")
    @classmethod
    def bounded_rules(cls, value):
        if any(not rule or len(rule) > 400 for rule in value):
            raise ValueError("continuity rules must contain 1-400 characters")
        return value


class ShortProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    _normalization_warnings: list[str] = PrivateAttr(default_factory=list)
    style_preset: Literal['auto', 'cinematic', 'luxury_commercial', 'funny_meme', 'documentary', 'futuristic', 'product_ad', 'social_viral'] = 'auto'
    schema_version: Literal[1, 2] = 1
    briefing: str = Field(default="", max_length=12000)
    quality: Literal["fast", "standard", "quality"] = "fast"
    music_selection: Literal['auto', 'off', 'custom'] = 'custom'
    music_mode: Literal["off", "global", "scene"] = "global"
    music_track: str | None = Field(default=None, max_length=240)
    music_volume: float = Field(default=0.18, ge=0, le=1)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
    title: str = Field(min_length=1, max_length=200)
    duration: int = Field(ge=5, le=300)
    aspect_ratio: Literal["9:16"] = "9:16"
    language: str = Field(default="de", pattern=r"^[a-z]{2}$")
    voice_enabled: bool = True
    voice: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    music_enabled: bool = True
    music_style: Literal[
        "cinematic", "futuristic", "dark", "emotional", "energetic", "ambient",
    ] | None = None
    subtitles_enabled: bool = True
    # False is the compatibility default for stored/legacy projects. The planner
    # explicitly enables it for newly planned multi-scene Shorts.
    consistency_mode: bool = False
    character_consistency: bool = True
    style_consistency: bool = True
    style_strength: float = Field(default=0.8, ge=0.0, le=1.0)
    visual_bible: VisualBible | None = None
    scenes: list[ShortScene] = Field(min_length=1, max_length=60)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy(cls, value):
        if isinstance(value, dict) and value.get("schema_version", 1) == 1:
            value = dict(value)
            if isinstance(value.get("scenes"), list):
                scenes = []
                for scene in value["scenes"]:
                    if isinstance(scene, ShortScene):
                        scene = scene.model_dump(exclude_unset=True)
                    if isinstance(scene, dict):
                        scene = dict(scene, caption=scene.get("caption", scene.get("narration", "")))
                    scenes.append(scene)
                value["scenes"] = scenes
        return value

    @model_validator(mode="after")
    def validate_timeline(self, info: ValidationInfo):
        scene_ids = [scene.id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene ids must be unique")
        if (info.context or {}).get("draft"):
            return self
        if self.schema_version == 1 and any(not scene.narration for scene in self.scenes):
            raise ValueError("legacy narration must contain at least 1 character")
        allowed = quality_capabilities()[self.quality]["durations"]
        for scene in self.scenes:
            if scene.duration not in allowed:
                raise ValueError(f"{self.quality}: scene duration must be one of {allowed}")
            if not scene.video_prompt:
                raise ValueError("video_prompt must contain at least 1 character before rendering")
            if scene.transition.duration > scene.duration:
                raise ValueError("transition exceeds scene duration")
            if scene.sfx.enabled and not scene.sfx.track:
                raise ValueError("enabled sound effect requires a track")
        if sum(scene.duration for scene in self.scenes) != self.duration:
            raise ValueError("scene durations must sum exactly to project duration")
        return self


class ShortPlanningError(RuntimeError):
    """The model could not produce a valid ShortProject."""


def _validate_plan(value):
    try:
        parsed = json.loads(str(value or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("short plan must be one JSON object")
    try:
        return ShortProject.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"invalid ShortProject: {exc}") from exc


def _planning_messages(prompt):
    schema = json.dumps(ShortProject.model_json_schema(), ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "Create a production plan for a vertical short video. For new plans set schema_version=2. "
                "Return exactly one JSON object and nothing else: no markdown, "
                "comments, or explanation. Follow this JSON Schema exactly: "
                f"{schema}\n"
                "Infer language from the user's prompt; use 'de' when unclear. "
                "Use aspect_ratio '9:16'. Every scene duration must be compatible "
                f"with LTX and one of {sorted(LTX_SCENE_DURATIONS)}. Scene durations "
                "must sum exactly to duration. Prefer four 5-second scenes for a "
                "20-second short. video_prompt must be non-empty; narration may be empty. "
                "video_prompt must describe only the visual scene. If music is "
                "enabled, choose music_style from cinematic, futuristic, dark, "
                "emotional, energetic, or ambient; default to cinematic. Enable "
                "voice, subtitles, and music unless the user explicitly asks otherwise. "
                "Voice configuration is not a creative choice: leave voice null and "
                "voice_speed at 1.0 unless the user explicitly names a local voice/profile "
                "or requests another speaking speed. Never invent a voice name. "
                "For newly planned multi-scene Shorts set consistency_mode=true unless "
                "the user explicitly requests independent scenes or direct text-to-video. "
                "When consistency_mode=true, create a concise visual_bible that captures "
                "the shared visual style, recurring character identity/wardrobe when one "
                "exists, environment, palette, camera language and continuity rules. "
                "Set character_consistency=false when there is no recurring person or "
                "character. Keep style_consistency=true unless explicitly disabled. "
                "Use style_strength 0.8 by default. Do not put narration or captions in "
                "the visual bible or video prompts."
            ),
        },
        {"role": "user", "content": str(prompt).strip()},
    ]


def plan_short(prompt, provider: ModelProvider, *, run_context: RunContext | None = None, constraints=None):
    """Create a ShortProject, with exactly one repair attempt on invalid output."""
    value = str(prompt or "").strip()
    if not value:
        raise ValueError("short prompt must not be empty")

    constraints = dict(constraints or {})
    scene_count = constraints.pop("scene_count", None)
    if scene_count and 'duration' in constraints and 'quality' in constraints:
        from agent.shorts_normalization import allocate_durations
        allocate_durations(constraints['duration'], scene_count, quality_capabilities()[constraints['quality']]['durations'])
    def validate_output(text):
        parsed = json.loads(str(text).strip())
        parsed.update(constraints)
        parsed["schema_version"] = 2 if constraints else parsed.get("schema_version", 1)
        from agent.shorts_normalization import normalize_short_for_available_runtime
        parsed, warnings = normalize_short_for_available_runtime(parsed, planning=True, scene_count=scene_count)
        project = ShortProject.model_validate(parsed)
        project._normalization_warnings = warnings
        if scene_count is not None and len(project.scenes) != scene_count:
            raise ValueError(f"exactly {scene_count} scenes required")
        return project
    from agent.shorts_normalization import STYLE_PRESETS
    messages = _planning_messages(value)
    messages[0]['content'] += ' Selected visual style: ' + STYLE_PRESETS.get(constraints.get('style_preset', 'auto'), '')
    messages[0]['content'] += ' Use local audio track auto/null, never invent filenames. Final scene transition must be cut with duration zero.'
    messages[0]["content"] += (
        " Separate spoken narration from visible caption. Narration may be empty. "
        "Fill scene title, human-friendly description, camera and caption. "
        "Transitions are composer effects, never put them in video_prompt. "
        "Respect these immutable settings and scene count: "
        + json.dumps({**constraints, "scene_count": scene_count}, ensure_ascii=False)
    )
    response = provider.complete(
        ModelRequest(
            messages=messages,
            max_tokens=min(16000, max(3200, (scene_count or 4) * 900)),
            temperature=0.1,
            role="agent",
        ),
        run_context=run_context,
    )
    try:
        return validate_output(response.text)
    except (ValueError, TypeError, AttributeError) as initial_error:
        repair = provider.complete(
            ModelRequest(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Repair the supplied output into exactly one valid JSON "
                            "object matching the ShortProject schema. Return JSON only. "
                            "Do not add unknown fields or change the user's intent."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Immutable constraints: {json.dumps({**constraints, 'scene_count': scene_count})}\n"
                            f"Validation error: {str(initial_error)[:2000]}\n"
                            f"Schema: {json.dumps(ShortProject.model_json_schema())}\n"
                            f"Output: {response.text[:10000]}"
                        ),
                    },
                ],
                max_tokens=min(16000, max(3200, (scene_count or 4) * 900)),
                temperature=0.0,
                role="agent",
            ),
            run_context=run_context,
        )
        try:
            return validate_output(repair.text)
        except (ValueError, TypeError, AttributeError) as repair_error:
            raise ShortPlanningError(
                "ShortProject remained invalid after one repair attempt"
            ) from repair_error
