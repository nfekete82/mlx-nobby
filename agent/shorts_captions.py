"""Word-timed ASS captions for Shorts.

The renderer consumes Whisper word timestamps and emits compact phrase windows.
Each word gets its own ASS event so only the currently spoken word is accented,
which gives a Reels/Shorts-style highlight without relying on karaoke fill
semantics that vary between ASS renderers.
"""

import math
import re

from agent.shorts_planner import ShortProject


MAX_PHRASE_WORDS = 5
MAX_PHRASE_CHARACTERS = 34
MAX_WORD_GAP = 0.55
MIN_EVENT_DURATION = 0.06
HIGHLIGHT_COLOUR = "&H00D7FF&"
WHITE_COLOUR = "&H00FFFFFF&"


def _ass_timestamp(seconds):
    centiseconds = round(max(0.0, float(seconds)) * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _ass_text(value):
    return str(value).replace("\\", r"\\").replace("{", r"\{").replace(
        "}", r"\}",
    ).replace("\r\n", r"\N").replace("\r", r"\N").replace("\n", r"\N")


def normalize_alignment_words(payload, duration):
    """Return safe, ordered word timestamps bounded to the Short duration."""
    duration = max(0.0, float(duration))
    raw_words = payload.get("words", []) if isinstance(payload, dict) else []
    normalized = []

    for item in raw_words:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("word") or "").split())
        if not text:
            continue
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start = min(duration, max(0.0, start))
        end = min(duration, max(start, end))
        if start >= duration:
            continue
        if end - start < MIN_EVENT_DURATION:
            end = min(duration, start + MIN_EVENT_DURATION)
        if end <= start:
            continue
        word = {
            "word": text,
            "start": start,
            "end": end,
        }
        probability = item.get("probability")
        if isinstance(probability, (int, float)) and math.isfinite(float(probability)):
            word["probability"] = max(0.0, min(1.0, float(probability)))
        normalized.append(word)

    normalized.sort(key=lambda item: (item["start"], item["end"]))
    return normalized


def phrase_groups(words):
    """Split words into readable 2-5 word caption cards."""
    groups = []
    current = []
    characters = 0

    def flush():
        nonlocal current, characters
        if current:
            groups.append(current)
        current = []
        characters = 0

    for word in words:
        text = word["word"]
        next_characters = characters + (1 if current else 0) + len(text)
        gap = (
            float(word["start"]) - float(current[-1]["end"])
            if current
            else 0.0
        )
        if current and (
            len(current) >= MAX_PHRASE_WORDS
            or next_characters > MAX_PHRASE_CHARACTERS
            or gap > MAX_WORD_GAP
        ):
            flush()
            next_characters = len(text)

        current.append(word)
        characters = next_characters

        if len(current) >= 2 and re.search(r"[.!?…][\"'”’)]*$", text):
            flush()

    flush()
    return groups


def _line_break_index(group):
    if len(group) < 4:
        return None
    total = sum(len(item["word"]) for item in group) + len(group) - 1
    if total <= 24:
        return None
    target = total / 2
    running = 0
    best = None
    distance = None
    for index, item in enumerate(group[:-1], 1):
        running += len(item["word"]) + (1 if index > 1 else 0)
        candidate_distance = abs(running - target)
        if distance is None or candidate_distance < distance:
            best = index
            distance = candidate_distance
    return best


def _phrase_text(group, active_index):
    break_index = _line_break_index(group)
    parts = []
    for index, item in enumerate(group):
        if index:
            parts.append(r"\N" if break_index == index else " ")
        text = _ass_text(item["word"])
        if index == active_index:
            parts.append(
                "{\\c" + HIGHLIGHT_COLOUR + r"\fs68\b1}" + text
                + "{\\c" + WHITE_COLOUR + r"\fs60\b1}"
            )
        else:
            parts.append(text)
    return "".join(parts)


def animated_subtitles_for_words(project, alignment):
    """Render word-highlighted ASS, or return None when no timings are usable."""
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    words = normalize_alignment_words(alignment, project.duration)
    if not words:
        return None

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 576
PlayResY: 1024
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,60,&H00FFFFFF,&H00FFFFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,4,1,2,34,34,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for group in phrase_groups(words):
        for index, word in enumerate(group):
            start = float(word["start"])
            if index + 1 < len(group):
                end = max(float(word["end"]), float(group[index + 1]["start"]))
            else:
                end = float(word["end"])
            end = min(float(project.duration), max(start + MIN_EVENT_DURATION, end))
            if end <= start:
                continue
            events.append(
                "Dialogue: 0,"
                f"{_ass_timestamp(start)},{_ass_timestamp(end)},"
                f"Caption,,0,0,0,,{_phrase_text(group, index)}"
            )

    if not events:
        return None
    return header + "\n".join(events) + "\n"
