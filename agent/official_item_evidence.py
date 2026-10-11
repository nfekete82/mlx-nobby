"""Conservative item-level evidence filter for explicitly official product lists.

A retrieved article is not proof of every listed product. For official queries,
strip unsupported individual product rows rather than leaving claims beside a
warning. This is a necessary-evidence check, not semantic entailment.
"""
import re
from agent.claim_context import MODEL, nearby_passages, normalized
from agent.claim_validation import loaded_articles, _NUMBER

_LIST = re.compile(r"^(\s*(?:[-*]|\d+[.)])\s+)(.*)$")
_OFFICIAL = ("offiziell", "official", "herstellerseite")


def filter_unsupported_official_items(answer, goal, observations):
    if not isinstance(answer, str) or not any(
        x in str(goal or "").casefold() for x in _OFFICIAL
    ):
        return answer
    articles = loaded_articles(observations)
    if not articles:
        return answer  # Existing fail-closed gate handles missing articles.
    removed = 0
    kept = []
    for line in answer.splitlines():
        match = _LIST.match(line)
        if not match:
            kept.append(line)
            continue
        body = match.group(2)
        subject_match = MODEL.search(body)
        if not subject_match:
            kept.append(line)
            continue
        subject = subject_match.group(0)
        # A model name alone or an isolated number in unrelated prose is
        # insufficient. Require a source passage naming the same model.
        excerpts = [
            passage for _, article in articles
            for passage in nearby_passages(article, subject)
            if re.search(r"(?<!\w)" + re.escape(subject) + r"(?!\w)", passage, re.I)
        ]
        if not excerpts:
            removed += 1
            continue
        # Check precise figures associated with this item locally, not against
        # a different model elsewhere on the fetched page.
        figures = _NUMBER.findall(body)
        if any(not any(normalized(number) in normalized(excerpt)
                       for excerpt in excerpts) for number in figures):
            removed += 1
            continue
        kept.append(line)
    if not removed:
        return answer
    remaining_items = sum(bool(_LIST.match(line) and MODEL.search(line)) for line in kept)
    if not remaining_items:
        return ("Die geladenen Artikel belegen keine der aufgeführten "
                "Produkt- und Zahlenangaben ausreichend. Ich gebe deshalb "
                "keine unbestätigte offizielle Produktliste aus.")
    # Do not retain introductory aggregate assertions or references that
    # could imply the discarded rows are still official current products.
    kept = [line for line in kept if not (
        not _LIST.match(line) and
        re.search(r"(?i)\b(?:insgesamt|alle modelle|gesamte palette)\b", line)
    )]
    return "\n".join(kept).rstrip() + (
        "\n\n**Evidenzstatus:** " + str(removed)
        + " Produktposition(en) ohne ausreichend passende Artikelbelege entfernt."
    )
