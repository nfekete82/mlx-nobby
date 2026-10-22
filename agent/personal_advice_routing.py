"""High-precision guard for first-person advice rather than external web research.

A personal account may mention websites, prices, statistics or today's
conversation without asking for public information. Do not use those nouns
as evidence for a web-search action. Genuine search/news/weather or direct
external-fact requests remain eligible for the normal router.
"""
from __future__ import annotations

import re

_PERSONAL_REFERENCE = re.compile(
    r"(?i)\b(?:"
    r"mein(?:e|er|em|en)?\s+(?:chef|chefin|boss|vorgesetzt\w*|kolleg\w*|"
    r"partner(?:in)?|freund(?:in)?|mutter|vater|bruder|schwester|"
    r"mann|frau|kind(?:er)?|sohn|tochter)|"
    r"my\s+(?:boss|manager|colleague|partner|mother|father|friend)"
    r")\b"
)

_PERSONAL_EXPERIENCE = re.compile(
    r"(?i)\b(?:"
    r"ich|wir|uns|unser\w*|meiner|meinen|mir|mich|"
    r"i|we|our|me|"
    r"sag(?:t|te|en)|meint|behauptet|findet|denkt|verlangt|"
    r"kritisiert|streit|diskussion|feedback|"
    r"said|says|thinks|insists|argues|feedback"
    r")\b"
)

_EXPLICIT_EXTERNAL = re.compile(
    r"(?i)(?:"
    r"\b(?:suche|such|recherchier\w*|google|search|research|look\s+up)\b"
    r"(?:\s+(?:im\s+web|online|im\s+internet|nach|for))?"
    r"|"
    r"\b(?:websuche|quellen?|belege?|links?|zitate|sources?)\s+"
    r"(?:finden|suchen|zeigen|nennen|dazu|hierzu|bitte|angeben)\b"
    r"|"
    r"\b(?:aktuell\w*|heute|latest|current|today)\s+"
    r"(?:news|nachrichten|preise|price\w*|angebote|offers?|kurs\w*|"
    r"wetter|weather|statistik\w*|zahlen|data|daten)\b"
    r"|"
    r"\b(?:news|nachrichten|wetter|weather)\s+"
    r"(?:heute|aktuell\w*|today|latest|current)\b"
    r"|"
    r"\b(?:was\s+steht|what\s+does)\b.{0,65}"
    r"\b(?:webseite|website|site|online)\b"
    r")"
)


def is_personal_advice_without_external_request(prompt: str) -> bool:
    """True only for grounded personal accounts with no explicit web intent."""
    if not isinstance(prompt, str):
        return False
    text = prompt.strip()
    return bool(
        25 <= len(text) <= 4000
        and _PERSONAL_REFERENCE.search(text)
        and _PERSONAL_EXPERIENCE.search(text)
        and not _EXPLICIT_EXTERNAL.search(text)
    )
