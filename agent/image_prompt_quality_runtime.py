"""Semantic prompt safeguards and Juggernaut-specific photorealism tuning.

The image model remains unchanged. This layer protects information that a local
translation can accidentally drop and adds a small set of realism anchors only
for photorealistic human prompts sent to Juggernaut XL.
"""

from __future__ import annotations

from functools import wraps
import importlib
import re


_FEMALE_MARKERS = re.compile(r"\b(?:female|woman|women|girl|girls)\b", re.IGNORECASE)
_MALE_MARKERS = re.compile(r"\b(?:male|man|men|boy|boys)\b", re.IGNORECASE)
_SOURCE_FEMALE = re.compile(
    r"\b(?:frau|frauen|mädchen|maedchen|weiblich(?:e|er|es|en|em)?|"
    r"polizistin|polizistinnen|ärztin|aerztin|ärztinnen|aerztinnen|"
    r"lehrerin|lehrerinnen|soldatin|soldatinnen|anwältin|anwaeltin|"
    r"anwältinnen|anwaeltinnen|fotografin|fotografinnen|journalistin|"
    r"journalistinnen)\b",
    re.IGNORECASE,
)
_SOURCE_MALE_EXPLICIT = re.compile(
    r"\b(?:mann|männer|maenner|männlich(?:e|er|es|en|em)?|junge|jungen)\b",
    re.IGNORECASE,
)
_SOURCE_NEGATION = re.compile(
    r"\b(?:ohne|kein|keine|keinen|keinem|keiner|keines|nicht|nie|niemals)\b",
    re.IGNORECASE,
)
_ENGLISH_NEGATION = re.compile(r"\b(?:without|no|not|never|none)\b", re.IGNORECASE)

# Deterministic repairs for common gendered German occupations. They are only
# applied when the source contains the explicit gendered form and the model's
# draft translation lost that information.
_FEMALE_OCCUPATIONS = (
    (re.compile(r"\bpolizistin\b", re.IGNORECASE), re.compile(r"\bpolice officer\b", re.IGNORECASE), "female police officer"),
    (re.compile(r"\bpolizistinnen\b", re.IGNORECASE), re.compile(r"\bpolice officers\b", re.IGNORECASE), "female police officers"),
    (re.compile(r"\b(?:ärztin|aerztin)\b", re.IGNORECASE), re.compile(r"\bdoctor\b", re.IGNORECASE), "female doctor"),
    (re.compile(r"\blehrerin\b", re.IGNORECASE), re.compile(r"\bteacher\b", re.IGNORECASE), "female teacher"),
    (re.compile(r"\bsoldatin\b", re.IGNORECASE), re.compile(r"\bsoldier\b", re.IGNORECASE), "female soldier"),
    (re.compile(r"\b(?:anwältin|anwaeltin)\b", re.IGNORECASE), re.compile(r"\blawyer\b", re.IGNORECASE), "female lawyer"),
    (re.compile(r"\bfotografin\b", re.IGNORECASE), re.compile(r"\bphotographer\b", re.IGNORECASE), "female photographer"),
    (re.compile(r"\bjournalistin\b", re.IGNORECASE), re.compile(r"\bjournalist\b", re.IGNORECASE), "female journalist"),
)

_QUOTED_TEXT = re.compile(r'"([^"]+)"|“([^”]+)”')
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")

_PHOTOREALISTIC = re.compile(
    r"\b(?:photorealistic|photo-realistic|photorealism|photograph(?:ic|y)?|photo|"
    r"realistic portrait|portrait photo|headshot|fotorealistisch(?:e|er|es|en|em)?|"
    r"fotografie|foto)\b",
    re.IGNORECASE,
)
_HUMAN_SUBJECT = re.compile(
    r"\b(?:person|people|human|woman|women|man|men|girl|girls|boy|boys|female|male|"
    r"portrait|porträt|headshot|police officer|doctor|teacher|soldier|lawyer|photographer|"
    r"journalist|officer|model|frau|frauen|mann|männer|maenner|polizistin|polizist)\b",
    re.IGNORECASE,
)

_JUGGERNAUT_REALISM_SUFFIX = (
    "natural skin texture, visible pores and fine facial detail, subtle facial asymmetry, "
    "lifelike eyes with natural catchlights, realistic hair strands, realistic fabric texture, "
    "physically plausible soft lighting, natural tonal variation, subtle photographic grain, "
    "unretouched photographic look"
)
_JUGGERNAUT_REALISM_NEGATIVE = (
    "waxy skin, plastic skin, airbrushed skin, over-smoothed skin, doll-like face, "
    "CGI, 3D render, synthetic skin, excessive beauty retouching, oversharpened"
)


def _normalized_number(value: str) -> str:
    return value.replace(",", ".")


def _preserves_numbers(source: str, translated: str) -> bool:
    source_numbers = {_normalized_number(item) for item in _NUMBER.findall(source)}
    translated_numbers = {_normalized_number(item) for item in _NUMBER.findall(translated)}
    return source_numbers.issubset(translated_numbers)


def _preserves_quoted_text(source: str, translated: str) -> bool:
    for match in _QUOTED_TEXT.finditer(source):
        literal = match.group(1) or match.group(2)
        if literal and literal not in translated:
            return False
    return True


def repair_translation_semantics(source: str, translated: str) -> str:
    """Repair high-value semantic loss without creatively rewriting the prompt.

    If structural information such as a number, quoted literal, or negation was
    lost, the original source is safer than a fluent but incorrect translation.
    Explicit female occupations can be repaired deterministically in English.
    """
    source = str(source or "").strip()
    result = str(translated or "").strip()
    if not source or not result:
        return source or result

    # The translator intentionally returns the source on uncertainty/error. Do
    # not mix an English repair suffix into an untranslated German prompt.
    if result.casefold() == source.casefold():
        return result

    if not _preserves_numbers(source, result):
        return source
    if not _preserves_quoted_text(source, result):
        return source
    if _SOURCE_NEGATION.search(source) and not _ENGLISH_NEGATION.search(result):
        return source

    for source_pattern, neutral_pattern, replacement in _FEMALE_OCCUPATIONS:
        if source_pattern.search(source) and not _FEMALE_MARKERS.search(result):
            repaired, count = neutral_pattern.subn(replacement, result, count=1)
            if count:
                result = repaired

    if _SOURCE_FEMALE.search(source) and not _FEMALE_MARKERS.search(result):
        result = result.rstrip(" .") + ", female subject."

    if _SOURCE_MALE_EXPLICIT.search(source) and not _MALE_MARKERS.search(result):
        result = result.rstrip(" .") + ", male subject."

    return result


def _is_juggernaut(model: str | None) -> bool:
    value = str(model or "").strip().casefold()
    return "juggernaut" in value


def _is_photorealistic_human_prompt(prompt: str) -> bool:
    text = str(prompt or "")
    return bool(_PHOTOREALISTIC.search(text) and _HUMAN_SUBJECT.search(text))


def enhance_juggernaut_payload(
    payload: dict,
    *,
    model: str | None,
    explicit_negative_prompt: bool = False,
) -> dict:
    """Add restrained realism hints for Juggernaut photorealistic people only."""
    if not isinstance(payload, dict) or not _is_juggernaut(model):
        return payload

    prompt = str(payload.get("prompt") or "").strip()
    if not _is_photorealistic_human_prompt(prompt):
        return payload

    if "natural skin texture" not in prompt.casefold():
        payload["prompt"] = prompt.rstrip(" ,.") + ", " + _JUGGERNAUT_REALISM_SUFFIX

    if not explicit_negative_prompt and not str(payload.get("negative_prompt") or "").strip():
        payload["negative_prompt"] = _JUGGERNAUT_REALISM_NEGATIVE

    return payload


def install_runtime():
    """Patch agent.app after import without changing its public API contracts."""
    agent_app = importlib.import_module("agent.app")

    original_translate = agent_app.translate_media_prompt_to_english
    if not getattr(original_translate, "__mlx_semantic_prompt_guard_v1__", False):
        @wraps(original_translate)
        def guarded_translate(prompt):
            source = str(prompt or "").strip()
            translated = original_translate(prompt)
            return repair_translation_semantics(source, translated)

        guarded_translate.__mlx_semantic_prompt_guard_v1__ = True
        agent_app.translate_media_prompt_to_english = guarded_translate

    original_payload = agent_app._image_generate_payload
    if not getattr(original_payload, "__mlx_juggernaut_realism_v1__", False):
        @wraps(original_payload)
        def tuned_payload(request):
            payload = original_payload(request)
            model = payload.get("model")
            if not model or model == "auto":
                try:
                    model = agent_app.load_model_roles().get("image")
                except Exception:
                    model = model or "auto"

            options = getattr(request, "image_options", None)
            explicit_negative = isinstance(options, dict) and "negative_prompt" in options
            return enhance_juggernaut_payload(
                payload,
                model=model,
                explicit_negative_prompt=explicit_negative,
            )

        tuned_payload.__mlx_juggernaut_realism_v1__ = True
        agent_app._image_generate_payload = tuned_payload

    return agent_app.translate_media_prompt_to_english, agent_app._image_generate_payload
