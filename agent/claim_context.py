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
