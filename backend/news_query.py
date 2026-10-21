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


# Compound German topics are a single word, so \bnews\b alone misses them.
FINANCIAL_NEWS = re.compile(
    r"(?i)\b(?P<topic>börsen|aktien|finanz|wirtschafts)[\s-]*(?:news|nachrichten)\b"
)
_SPECIFIC_FINANCIAL_CONTEXT = re.compile(
    r"(?i)\b(?:nvidia|amd|apple|microsoft|tesla|bitcoin|göppingen|"
    r"deutschland|europa|usa|ukraine|deutsche börse)\b"
)
_FINANCIAL_RESULT_SIGNAL = re.compile(
    r"(?i)\b(?:börse\w*|aktie\w*|finanzmarkt\w*|finanzmärkte|"
    r"dax|mdax|sdax|tecdax|nasdaq|wall street|dow jones|s&p\s*500|"
    r"stock\w*|share\w*|anleihe\w*|rendite\w*|investor\w*|"
    r"trading|kurs\w*|quartalszahl\w*|indizes|index|notiert|"
    r"marktbericht\w*|handelstag\w*|börsengang\w*)\b"
)


def financial_news_topic(query: str) -> str | None:
    """Recognize finance news even in glued German compounds."""
    match = FINANCIAL_NEWS.search(str(query or ""))
    return match.group("topic").casefold() if match else None


def filter_financial_news_results(query: str, results: list) -> list:
    """Reject obviously off-topic search hits for broad stocks/exchange news.

    Narrow company queries and general economic headlines are unchanged.
    Callers retain their own timestamp, URL and article-evidence checks.
    """
    if (financial_news_topic(query) not in {"börsen", "aktien"}
            or normalized_news_query(query) == str(query or "").strip()):
        return results
    return [
        item for item in results
        if isinstance(item, dict) and _FINANCIAL_RESULT_SIGNAL.search(
            " ".join(str(item.get(field) or "") for field in ("title", "snippet"))
        )
    ]


def normalized_news_query(query: str) -> str:
    """Produce index-friendly words for unspecified daily news requests."""
    text = str(query or "").strip()
    topic = financial_news_topic(text)
    if (topic and BROAD_REQUEST.search(text)
            and not _SPECIFIC_FINANCIAL_CONTEXT.search(text)):
        # Provider-friendly terms, without the imperative "gib mir" which
        # search engines may misread as the ticker/acronym GIB.
        return {
            "börsen": "Börse Aktienmärkte",
            "aktien": "Aktien Börse",
            "finanz": "Finanznachrichten Märkte",
            "wirtschafts": "Wirtschaft Unternehmen",
        }[topic]
    if not BROAD_NEWS.search(text) or TOPICS.search(text) or not BROAD_REQUEST.search(text):
        return text
    return "aktuelle Nachrichten Deutschland Welt Politik Wirtschaft"
