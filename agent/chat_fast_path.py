"""Conservative zero-inference fast path for self-contained, timeless chat prompts.

This is deliberately an allowlist, not a replacement for semantic routing.
Requests involving files, history, tools, workspaces or changing facts must
continue through the existing deterministic/semantic router and safety gates.
"""
from __future__ import annotations

import re


_SIMPLE_EXCHANGES = re.compile(
    r"(?:hallo|hi|hey|servus|moin|guten morgen|guten tag|guten abend|"
    r"danke(?: schön)?|vielen dank|thanks|thank you|ok|okay|alles klar)"
    r"[.! ]*",
    re.IGNORECASE,
)

# Permit *only* clearly informational standalone questions and harmless
# creative-text tasks. For any uncertainty, use the existing model router.
_INFORMATIONAL_PREFIX = re.compile(
    r"(?:bitte\s+)?(?:"
    r"nenn(?:e)?(?: mir)?|"
    r"erkläre(?: mir)?|erklaere(?: mir)?|"
    r"was sind|was bedeutet|warum ist|wieso ist|wie viele|"
    r"was ist der unterschied zwischen|"
    r"what are|why is|how many|explain(?: to me)?"
    r")\b",
    re.IGNORECASE,
)
_CREATIVE_PREFIX = re.compile(
    r"(?:bitte\s+)?(?:"
    r"schreibe|schreib|verfasse|write"
    r")\s+(?:(?:mir\s+)?(?:ein(?:e|en|em|es)?\s+))?"
    r"(?:(?:kurzes?|kurze|lustiges?|lustige|short|funny)\s+)?"
    r"(?:gedicht|geschichte|poem|story)\b",
    re.IGNORECASE,
)

# False negatives cost one router call; false positives can skip necessary
# research or tools. Bias strongly toward the former.
_UNSAFE_CONTEXT = re.compile(
    r"(?:https?://|www\.|\x60{3}|[/\\]|@|#[0-9]|(?:^|\s)\d{4}(?:\s|$)|"
    r"\b(?:"
    r"heute|gestern|morgen|jetzt|gerade|momentan|derzeit|"
    r"aktuell\w*|neueste\w*|neuesten|neuen|latest|today|yesterday|"
    r"tomorrow|current|recent|right now|"
    r"beste\w*|best|preis\w*|kosten|kurs\w*|aktie\w*|"
    r"wetter|uhrzeit|datum|öffnungszeit\w*|"
    r"meine\w*|meinem|meinen|mein|unser\w*|your|my|our|"
    r"dieses|diese|dieser|diesen|hier|dort|oben|"
    r"suche|such\w*|recherchier\w*|research|search|"
    r"finde|find\w*|prüf\w*|pruef\w*|check\w*|"
    r"analysier\w*|bewert\w*|verifizier\w*|"
    r"öffne|oeffne|start\w*|install\w*|"
    r"ändere|aendere|änder\w*|bearbeit\w*|"
    r"implementier\w*|reparier\w*|lösch\w*|loesch\w*|"
    r"lösche|delete|remove|run|execute|"
    r"zeige|zeig|schau\w*|lade|download\w*|"
    r"tool\w*|quelle\w*|source\w*|link\w*|"
    r"datei\w*|ordner\w*|anhang|attachment\w*|"
    r"workspace|projekt\w*|repository|repo|git|"
    r"nobby|mlx|docker|localhost|api|server|modell\w*|model\w*|"
    r"mac|rechner|computer|ram|speicher|prozess\w*|port|"
    r"finanz\w*|börse|boerse|bitcoin|"
    r"restaurant\w*|hotel\w*|leas\w*|"
    r"bild\w*|foto\w*|video\w*|musik\w*|audio\w*"
    r")\b)",
    re.IGNORECASE,
)
_FOLLOWUP_REFERENCE = re.compile(
    r"\b(?:das|davon|dazu|darauf|nochmal|erneut|weiter|again|this|that|these|those)\b",
    re.IGNORECASE,
)


def simple_chat_fast_path(
    prompt: str,
    *,
    has_file: bool = False,
    has_history: bool = False,
    workspace_active: bool = False,
) -> bool:
    """Return True only for short, context-free prompts needing no tools."""
    if has_file or has_history or workspace_active or not isinstance(prompt, str):
        return False
    text = " ".join(prompt.split())
    if not (2 <= len(text) <= 240):
        return False
    if _SIMPLE_EXCHANGES.fullmatch(text):
        return True
    if _UNSAFE_CONTEXT.search(text) or _FOLLOWUP_REFERENCE.search(text):
        return False
    return bool(
        _INFORMATIONAL_PREFIX.match(text)
        or _CREATIVE_PREFIX.match(text)
    )
