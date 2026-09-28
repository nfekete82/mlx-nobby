"""Validated production plans for short-form videos."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from agent.model_provider import ModelProvider, ModelRequest
from agent.run_state import RunContext
from video_service import SUPPORTED_DURATIONS_BY_RESOLUTION


LTX_SCENE_DURATIONS = frozenset().union(*(
    durations
    for resolution, durations in SUPPORTED_DURATIONS_BY_RESOLUTION.items()
    if resolution != "preview"
))


class ShortScene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    duration: int
    narration: str = Field(min_length=1, max_length=4000)
    video_prompt: str = Field(min_length=1, max_length=4000)

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

    @model_validator(mode="after")
    def validate_timeline(self):
        if sum(scene.duration for scene in self.scenes) != self.duration:
            raise ValueError("scene durations must sum exactly to project duration")
        scene_ids = [scene.id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene ids must be unique")
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
                "Create a production plan for a vertical short video. "
                "Return exactly one JSON object and nothing else: no markdown, "
                "comments, or explanation. Follow this JSON Schema exactly: "
                f"{schema}\n"
                "Infer language from the user's prompt; use 'de' when unclear. "
                "Use aspect_ratio '9:16'. Every scene duration must be compatible "
                f"with LTX and one of {sorted(LTX_SCENE_DURATIONS)}. Scene durations "
                "must sum exactly to duration. Prefer four 5-second scenes for a "
                "20-second short. Narration and video_prompt must be non-empty. "
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


def plan_short(prompt, provider: ModelProvider, *, run_context: RunContext | None = None):
    """Create a ShortProject, with exactly one repair attempt on invalid output."""
    value = str(prompt or "").strip()
    if not value:
        raise ValueError("short prompt must not be empty")

    response = provider.complete(
        ModelRequest(
            messages=_planning_messages(value),
            max_tokens=3200,
            temperature=0.1,
            role="agent",
        ),
        run_context=run_context,
    )
    try:
        return _validate_plan(response.text)
    except ValueError as initial_error:
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
                            f"Validation error: {str(initial_error)[:2000]}\n"
                            f"Schema: {json.dumps(ShortProject.model_json_schema())}\n"
                            f"Output: {response.text[:10000]}"
                        ),
                    },
                ],
                max_tokens=3200,
                temperature=0.0,
                role="agent",
            ),
            run_context=run_context,
        )
        try:
            return _validate_plan(repair.text)
        except ValueError as repair_error:
            raise ShortPlanningError(
                "ShortProject remained invalid after one repair attempt"
            ) from repair_error
