"""Conservative zero-inference fast path for self-contained, timeless chat prompts.

This is deliberately an allowlist, not a replacement for semantic routing.
Requests involving files, history, tools, workspaces or changing facts must
continue through the existing deterministic/semantic router and safety gates.
"""
from __future__ import annotations

import os
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
    r")\s+(?:(?:mir\s+)?(?:ein(?:e|en|em|es)?|a|an|the)\s+)?"
    r"(?:(?:kurzes?|kurze|lustiges?|lustige|short|funny)\s+)?"
    r"(?:gedicht|geschichte|poem|story)\b",
    re.IGNORECASE,
)

# False negatives cost one router call; false positives can skip necessary
# research or tools. Bias strongly toward the former.
_UNSAFE_CONTEXT = re.compile(
    r"(?:https?://|www\.|\x60{3}|[/\\]|@|#[0-9]|(?:^|\s)\d{4}(?:\s|$)|"
    r"\b(?:"
    r"heute|gestern|morgen|jetzt|gerade|momentan|derzeit|nächste\w*|naechste\w*|kommende\w*|"
    r"aktuell\w*|neueste\w*|neuesten|neuen|latest|today|yesterday|"
    r"tomorrow|current|recent|right now|"
    r"beste\w*|best|preis\w*|kosten|kurs\w*|aktie\w*|angebot\w*|termin\w*|veranstaltung\w*|"
    r"wetter|uhrzeit|datum|öffnungszeit\w*|"
    r"meine\w*|meinem|meinen|mein|unser\w*|your|my|our|"
    r"dieses|diese|dieser|diesen|hier|dort|oben|"
    r"suche|such\w*|recherchier\w*|research|search|online|internet|webseite\w*|website\w*|"
    r"finde|find\w*|prüf\w*|pruef\w*|check\w*|"
    r"analysier\w*|bewert\w*|verifizier\w*|"
    r"öffne|oeffne|start\w*|install\w*|"
    r"ändere|aendere|änder\w*|bearbeit\w*|"
    r"implementier\w*|reparier\w*|lösch\w*|loesch\w*|"
    r"lösche|delete|remove|run|execute|"
    r"zeige|zeig|schau\w*|lade|download\w*|sende\w*|send\w*|verschick\w*|schick\w*|poste\w*|veröffentlich\w*|"
    r"tool\w*|quelle\w*|source\w*|link\w*|"
    r"datei\w*|ordner\w*|anhang|attachment\w*|"
    r"workspace|projekt\w*|repository|repo|git|"
    r"nobby|mlx|docker|localhost|api|server|modell\w*|model\w*|"
    r"mac|rechner|computer|ram|speicher|prozess\w*|port|"
    r"finanz\w*|börse|boerse|bitcoin|"
    r"restaurant\w*|hotel\w*|leas\w*|geschäft\w*|shop\w*|firma\w*|unternehmen|adresse\w*|kontakt\w*|email|e-mail|telefon\w*|arzt|ärzte|klinike\w*|spiel\w*|game\w*|"
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
    if os.environ.get("MLX_CHAT_FAST_PATH_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return False
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


# The frontend forwards at most eight previous user/assistant messages as
# text-only context. A chat continuation may bypass the classifier *only*
# when its recent user turns are themselves proven safe by this allowlist.
# These expressions ask for explanations, never actions or source retrieval.
_EXPLANATION_FOLLOWUP = re.compile(
    r"(?:"
    r"kannst du (?:mir )?(?:das|es) "
    r"(?:bitte )?(?:noch(?:mal| einmal) )?"
    r"(?:einfacher|genauer|kurz) erkl(?:ä|ae)ren"
    r"|"
    r"erkl(?:ä|ae)r(?:e)? (?:mir )?(?:das|es) "
    r"(?:bitte )?(?:noch(?:mal| einmal) )?"
    r"(?:einfacher|genauer|kurz)"
    r"|"
    r"kannst du (?:mir )?(?:bitte )?(?:ein |ein kurzes )?"
    r"beispiel (?:dazu )?geben"
    r"|"
    r"was bedeutet das (?:genau|eigentlich)"
    r"|"
    r"warum ist das so"
    r"|"
    r"could you explain (?:that|it) (?:more simply|in simpler terms)"
    r"|"
    r"can you (?:give|show) me an example"
    r")\s*[.!?]?",
    re.IGNORECASE,
)
# An assistant reply may contain tool output, code or linked research despite
# a harmless first question. Those conversations always return to the router.
_UNTRUSTED_ASSISTANT_HISTORY = re.compile(
    r"(?:https?://|www\.|"
    r"\x60{3}|"
    r"\b(?:agent-auftrag|tool_result|coding_agent|research_agent|"
    r"diagnostic_agent|orchestrator|tool_call|artifact_id)\b)",
    re.IGNORECASE,
)


def safe_followup_chat_fast_path(
    prompt: str,
    conversation_context: object,
    *,
    workspace_active: bool = False,
) -> bool:
    """Admit only explanation follow-ups in fully benign recent conversations.

    No history metadata or validated route is available from the frontend, so
    every visible recent user turn must have qualified for our local allowlist.
    This intentionally rejects uncertain context rather than guessing a route.
    """
    if workspace_active or not isinstance(prompt, str):
        return False
    message = " ".join(prompt.split())
    if not (4 <= len(message) <= 110):
        return False
    if _UNSAFE_CONTEXT.search(message) or not _EXPLANATION_FOLLOWUP.fullmatch(message):
        return False
    if not isinstance(conversation_context, list):
        return False
    if not (2 <= len(conversation_context) <= 8) or len(conversation_context) % 2:
        return False

    for index in range(0, len(conversation_context), 2):
        user, assistant = conversation_context[index:index + 2]
        if not isinstance(user, dict) or not isinstance(assistant, dict):
            return False
        if user.get("role") != "user" or assistant.get("role") != "assistant":
            return False
        # Never trust unexpected metadata in this path: the frontend contract
        # forwards exactly the two text fields for each prior message.
        if set(user) != {"role", "content"} or set(assistant) != {"role", "content"}:
            return False
        earlier, reply = user.get("content"), assistant.get("content")
        if not isinstance(earlier, str) or not isinstance(reply, str):
            return False
        if not reply.strip() or len(reply) > 2000:
            return False
        if _UNTRUSTED_ASSISTANT_HISTORY.search(reply):
            return False
        if index == 0:
            # Honor the global opt-out, and prove the original prompt was safe.
            if not simple_chat_fast_path(earlier):
                return False
        else:
            earlier = " ".join(earlier.split())
            if (
                len(earlier) > 110
                or _UNSAFE_CONTEXT.search(earlier)
                or not _EXPLANATION_FOLLOWUP.fullmatch(earlier)
            ):
                return False
    return True
