"""Context-aware numerical source matching.

Conservative heuristic: a number elsewhere on the page is not sufficient
evidence for a named product. This is not a semantic entailment engine.
"""
import re

MODEL = re.compile(r"\b(?:iPhone|Pixel|Galaxy|MacBook|ThinkPad)\s+[A-Za-z0-9]+(?:\s+(?:Pro|Max|Ultra|Plus|Air|XL))?\b", re.I)


def subject_in_text(text):
    match = MODEL.search(text or "")
    return match.group(0) if match else None


def nearby_passages(text, subject, radius=160):
    if not subject:
        return [text]
    return [text[max(0, match.start()-radius):match.end()+radius]
            for match in re.finditer(re.escape(subject), text, re.I)]


def normalized(value):
    return re.sub(r"\s+", "", str(value).casefold()).replace(",", ".")


def matches_claim(claim, block, articles):
    subject = subject_in_text(block)
    return any(normalized(claim) in normalized(passage)
               for _, text in articles
               for passage in nearby_passages(text, subject))

def conflicting_values(block, claim, articles):
    """Report possible different values near the same model across sources.

    Only inspect numeric values of the same kind (EUR prices or ISO-style
    day dates). Returns candidates, not a definitive factual contradiction.
    """
    subject = subject_in_text(block)
    if not subject or len(articles) < 2:
        return []
    is_euro = "€" in claim
    if not is_euro:
        return []
    values_by_source = []
    for url, body in articles:
        values = set()
        for passage in nearby_passages(body, subject):
            values.update(normalized(v) for v in
                          re.findall(r"\d[\d.,]*\s*€", passage))
        if values:
            values_by_source.append(values)
    if len(values_by_source) < 2:
        return []
    overlap = set.intersection(*values_by_source)
    if overlap:
        return []
    return sorted(set.union(*values_by_source))
