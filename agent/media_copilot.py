"""Smart Media Agent: bounded, optional Qwen prompt planning.

The existing deterministic router decides whether a user authorized a media
job. This module NEVER chooses a new operation, source or permission. It only
prepares a tool-specific prompt and, for images, recommends an enabled model.
Failures return a direct-mode plan rather than blocking media generation.
"""
from __future__ import annotations

import json
import re
from typing import Any

TARGETS = frozenset({"image", "image_edit", "video"})
MAX_PROMPT_CHARS = 4000
MAX_MODELS = 32

SYSTEM_PROMPT = """You are MLX-Nobby's Smart Media Agent. Return JSON only.
Return exactly one JSON object with keys: prompt, model, negative_prompt.
The caller already authorized the media operation. Do NOT change its type.
Preserve the user's identity, people count, gender, body, clothing, scene,
camera, action, mood, exact restrictions, and negations. Do not invent important
attributes or turn one person into a different person.
For source image edits: change ONLY the requested details; preserve the rest.
For reference/resemblance: preserve requested resemblance, not exact identity
unless requested. For image-to-video: preserve subject, frame and appearance;
describe movement and camera motion precisely. Do not invent dialogue.
Write the result prompt in clear English for the target image/video model.
Add only neutral technical details when they materially clarify the request.
Use an image model only from the provided list of enabled IDs.
If the input has an explicit selected model, output EXACTLY that ID.
If no image models are supplied, use model "auto". For video use model "auto".
For negative_prompt: use a short, model-compatible exclusion only when
a user requested a new image and negative prompts are supported; otherwise "".
Never add restrictions or censorship-related rewrites beyond the user's brief.
Never include extra keys, Markdown fences, chain-of-thought or commentary."""


def _json_object(text: str) -> dict:
    text = str(text or "").strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        # Some local models wrap strict JSON in a fenced code block.
        fenced = re.fullmatch(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
        if not fenced:
            raise ValueError("Model output is not JSON") from exc
        value = json.loads(fenced.group(1))
    if not isinstance(value, dict):
        raise ValueError("Model output is not an object")
    return value


def direct_plan(prompt: str, target: str, selected_model: str = "auto", reason: str = "direct") -> dict:
    return {
        "prompt": prompt, "model": selected_model or "auto",
        "negative_prompt": "", "mode": "direct", "reason": reason,
        "target": target,
    }


def plan_media(
    *,
    prompt: str, target: str, source_kind: str,
    candidate_models: list[dict],
    selected_model: str = "auto",
    complete,
) -> dict:
    """Call the existing chat-role Qwen once; validate every field returned.

    Source metadata is intentionally descriptive only: no local image paths,
    artifacts, data URLs or arbitrary client-provided model lists reach Qwen.
    """
    prompt = str(prompt or "").strip()
    selected_model = str(selected_model or "auto").strip() or "auto"
    if target not in TARGETS or not prompt or len(prompt) > MAX_PROMPT_CHARS:
        return direct_plan(prompt, target, selected_model, "invalid_input")
    choices = [
        {"id": str(m.get("id")), "name": str(m.get("name") or m.get("id"))[:96]}
        for m in candidate_models[:MAX_MODELS]
        if isinstance(m, dict) and m.get("id") and m.get("enabled") is True
    ] if target in {"image", "image_edit"} else []
    valid_ids = {m["id"] for m in choices}
    if selected_model != "auto" and selected_model not in valid_ids:
        # Never silently replace an unavailable manual choice with an auto one.
        return direct_plan(prompt, target, selected_model, "manual_model_unavailable")

    task = {
        "user_request": prompt,
        "authorized_target": target,
        "source_kind": source_kind if source_kind in {"none", "image", "images", "video", "audio"} else "none",
        "selected_model": selected_model,
        "available_models": choices,
    }
    try:
        raw = complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
        ])
        parsed = _json_object(raw)
        final = parsed.get("prompt")
        if not isinstance(final, str) or not final.strip() or len(final) > MAX_PROMPT_CHARS:
            raise ValueError("Invalid media prompt")
        model = str(parsed.get("model") or "auto")
        if selected_model != "auto":
            model = selected_model
        elif target == "video" or model not in valid_ids:
            model = "auto"
        negative = parsed.get("negative_prompt", "")
        if not isinstance(negative, str):
            negative = ""
        if target != "image" or model != "juggernaut-xl":
            negative = ""
        return {
            "prompt": final.strip(), "model": model,
            "negative_prompt": negative.strip()[:600],
            "mode": "smart", "target": target,
        }
    except Exception:
        return direct_plan(prompt, target, selected_model, "planner_unavailable")
