"""Conservative per-turn clock routing for prefix-cache stability.

Only omit the changing clock block for unambiguously timeless text requests.
Everything uncertain retains the fresh authoritative system clock.
"""
from __future__ import annotations

import os
import re

_TEMPORAL = re.compile(
    r"(?i)(?<!\w)(?:"
    r"heute|morgen|gestern|vorgestern|übermorgen|uebermorgen|"
    r"jetzt|aktuell\w*|derzeit|momentan|bald|neulich|"
    r"uhr(?:zeit)?|datum|kalender|wochentag|woche\w*|monat\w*|jahr\w*|"
    r"frist\w*|termin\w*|deadline\w*|alter|geburtstag\w*|"
    r"seit wann|wie lange|wann|"
    r"today|tomorrow|yesterday|now|currently|current|latest|recent|"
    r"time|date|calendar|week\w*|month\w*|year\w*|"
    r"deadline\w*|birthday\w*|age|when|"
    r"\d{1,2}[.:/]\d{1,2}(?:[.:/]\d{2,4})?|\d{4}"
    r")(?!\w)"
)


def include_live_clock(messages: list, system_prompt: str = "") -> bool:
    # Escape hatch: old behavior always supplies the authoritative clock.
    if os.getenv("NOBBY_CLOCK_CONTEXT_ALWAYS") == "1":
        return True
    # Scope to normal, purely textual latest user turns with explicit content.
    if not messages or not isinstance(messages[-1], dict):
        return True
    latest = messages[-1]
    if latest.get("role") != "user" or not isinstance(latest.get("content"), str):
        return True
    text = latest["content"]
    if not text.strip():
        return True
    # Do not scan generic system instructions for temporal words: broad\n    # boilerplate (e.g. "today", "date", "year") otherwise disables APC\n    # even when the user asks a timeless question. Only explicit system\n    # demands for fresh host time override the current user intent.\n    explicit_clock_instruction = re.search(\n        r"(?i)(?:current|live|actual|host|heutig|aktuell)\\s+"\n        r"(?:system\\s+)?(?:time|date|clock|uhrzeit|datum)|"\n        r"(?:zeit|uhrzeit|datum)\\s+(?:vom|des)\\s+(?:host|system)",\n        system_prompt,\n    )\n    return bool(_TEMPORAL.search(text) or explicit_clock_instruction)
