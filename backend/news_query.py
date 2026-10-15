"""Normalize broad news requests without altering narrow topical searches.

The semantic router owns tool selection. This module only turns a *broad*
request into useful provider keywords after the web-search tool was selected.
Never relax same-day verification or invent missing results.
"""
import re

BROAD_NEWS = re.compile(
    r"(?i)\b(?:news|nachrichten|schlagzeilen|neuigkeiten)\b"
)
TOPICS = re.compile(
    r"(?i)\b(?:nvidia|apple|microsoft|tesla|bitcoin|aktien?|börsen?|"
    r"sport|fußball|fussball|technik|ki|ai|künstliche intelligenz|"
    r"politik|wirtschaft|wissenschaft|regional|baden.württemberg|"
    r"göppingen|ukraine|usa|europa|deutschland)\b"
)
BROAD_REQUEST = re.compile(
    r"(?i)\b(?:alle|wichtigsten?|wichtig(?:e|en)?|zusammenfass\w*|"
    r"überblick|überblick|was gibt.s neues|heute|latest|aktuell(?:e|en)?)\b"
)


def normalized_news_query(query: str) -> str:
    """Produce index-friendly words for unspecified daily news requests."""
    text = str(query or "").strip()
    if not BROAD_NEWS.search(text) or TOPICS.search(text) or not BROAD_REQUEST.search(text):
        return text
    return "aktuelle Nachrichten Deutschland Welt Politik Wirtschaft"
