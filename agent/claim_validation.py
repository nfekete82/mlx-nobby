"""Conservative source gate for high-risk numerical claims in web answers.

This is a token/date consistency check, NOT semantic fact verification.
It only considers successfully fetched article text. When there is insufficient
evidence, it labels the whole answer as unverified rather than silently
deleting context or claiming truth.
"""
import re
from urllib.parse import urlsplit

from agent.temporal_validation import MONTH

_NUMBER = re.compile(rf"(?<![\w])(?:\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}|20\d{{2}}-\d{{2}}-\d{{2}}|\d{{1,2}}\.?\s+(?:{MONTH})\s+20\d{{2}}|(?:{MONTH})\s+\d{{1,2}},?\s+20\d{{2}}|\d[\d.,]*\s*(?:€|EUR|USD|\$)|[$€]\s*\d(?:[\d.,]*\d)?)(?!\w)", re.I)
_URL = re.compile(r"https?://[^\s)\]>]+")
_SENTENCE = re.compile(r"\n+|(?<=[!?])\s+|(?<=[a-zäöü])\.\s+(?=[A-ZÄÖÜ])")


def _normalize(value):
    return re.sub(r"\s+", "", str(value).casefold()).replace(",", ".")


def loaded_articles(observations):
    articles = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url" or item.get("status") != "completed":
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        url = result.get("final_url") or result.get("url")
        body = result.get("text")
        if not isinstance(url, str) or not isinstance(body, str) or len(body.strip()) < 80:
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        articles.append((url, body))
    return articles


def audit_numerical_claims(answer, observations):
    """Return an audit without implying that matching tokens prove a fact."""
    sources = loaded_articles(observations)
    if not sources:
        return {"checked": False, "unverified": [], "source_count": 0}
    prose = re.sub(r"\[([^]]+)\]\(https?://[^)]+\)", r"\1", str(answer or ""))
    prose = _URL.sub("", prose)
    blocks = _SENTENCE.split(prose)
    issues = []
    conflicts = []
    for block in blocks:
        # Quotes/links and pure source listings are not factual assertions.
        if re.match(r"^\s*(?:quellen?\s*:|[-*]\s*https?://)", block, re.I):
            continue
        for match in _NUMBER.finditer(block):
            claim = match.group(0)
            if re.search(r"(?:Stand|abgerufen(?:\s+am)?|Abrufdatum)\s*:?\s*$", block[:match.start()], re.I):
                continue  # The observation clock is not an article claim.
            # A token appearing in article text is necessary but not sufficient.
            from agent.claim_context import matches_claim, MODEL
            subjects = list(MODEL.finditer(block, 0, match.start()))
            context = block[subjects[-1].start():] if subjects else block
            if not matches_claim(claim, context, sources):
                issues.append(claim)
            from agent.claim_context import conflicting_values
            competing = conflicting_values(context, claim, sources)
            if competing:
                conflicts.append(", ".join(competing))
    return {"checked": True, "unverified": list(dict.fromkeys(issues)),
            "source_count": len(sources), "conflicts": list(dict.fromkeys(conflicts))}


def gate_numerical_claims(answer, observations):
    """Mark answers with unsupported precise figures; preserve original text."""
    audit = audit_numerical_claims(answer, observations)
    if not audit["checked"] or not (audit["unverified"] or audit["conflicts"]):
        return answer
    values = ", ".join(audit["unverified"][:6])
    conflicts = "; ".join(audit["conflicts"][:3])
    warning = ("**Quellenprüfung:** Die folgenden präzisen Angaben konnten "
            "in den tatsächlich geladenen Artikeln nicht nachgewiesen werden "
            f"und sind nicht verifiziert: {values}. "
            + (f"Mögliche widersprüchliche Quellendaten: {conflicts}. " if conflicts else "")
            + "Dies ist ein Hinweis auf fehlende oder uneinheitliche Evidenz, kein Beweis für einen Fehler.")
    return answer if warning in str(answer) else str(answer).rstrip() + "\n\n" + warning


def gate_source_links(answer, observations):
    """Remove invented outbound citations and disclose missing article text."""
    articles = loaded_articles(observations)
    allowed = {url.rstrip(".,;") for url, _ in articles}
    # A successfully loaded redirect may legitimately be cited by its input URL.
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url" or item.get("status") != "completed":
            continue
        result = item.get("result")
        if not isinstance(result, dict) or (result.get("final_url") or result.get("url")) not in allowed:
            continue
        for url in (result.get("url"), item.get("query")):
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                allowed.add(url.rstrip(".,;"))
    text = str(answer)
    invented = {match.group(0).rstrip(".,;") for match in _URL.finditer(text)} - allowed
    if invented:
        text = re.sub(r"\[([^]]+)\]\((https?://[^)]+)\)",
                      lambda match: match[1] if match[2].rstrip(".,;") in invented else match[0], text)
        text = _URL.sub(lambda match: "[unbelegter Link entfernt]" if match[0].rstrip(".,;") in invented else match[0], text)
        text += "\n\n**Linkprüfung:** Nicht durch tatsächlich geladene Artikel belegte Links wurden entfernt."
    if not articles:
        text += "\n\n**Evidenzstatus:** Keine erfolgreich geladenen Artikeltexte; die Angaben sind nicht unabhängig bestätigt."
    return text
