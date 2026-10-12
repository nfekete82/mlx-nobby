"""Find an observed government explanation of five-day statutory annual leave.

§3 BUrlG's 24 *Werktage* are not the number of employee workdays for a
five-day week. Search and navigate to a genuine official explanatory source
rather than manufacturing a conversion as a sourced claim.
"""
import re
from urllib.parse import urlsplit
from agent.leave_workweek_validation import _FIVE_DAY, _LEAVE


def _five_day_leave_question(goal):
    text = str(goal or "")
    return bool(_FIVE_DAY.search(text) and _LEAVE.search(text))


def _official_law_source_loaded(observations):
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url") or ""
        try:
            parsed = urlsplit(url)
        except (TypeError, ValueError):
            continue
        if (parsed.scheme == "https" and parsed.hostname in
                {"www.gesetze-im-internet.de", "gesetze-im-internet.de"}
                and parsed.path.startswith("/burlg/")):
            return True
    return False


def _explanatory_source_loaded(observations):
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url") or ""
        try:
            parsed = urlsplit(url)
        except (TypeError, ValueError):
            continue
        if (parsed.scheme == "https" and parsed.hostname in
                {"www.bmas.de", "bmas.de"}):
            text = str(result.get("text") or "")
            # Completeness hint, not independent proof. The model must still
            # link the statement to these exact source passage IDs.
            if (_FIVE_DAY.search(text) and
                    re.search(r"(?i)\b20\s+arbeitstagen?\b", text)):
                return True
    return False


_QUERY = '!go bmas.de Brückenteilzeit Urlaubsanspruch FAQ Mindesturlaub'


def choose_leave_explanation_step(goal, observations):
    if not _five_day_leave_question(goal):
        return None
    if not _official_law_source_loaded(observations):
        return None
    if _explanatory_source_loaded(observations):
        return None

    matches = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "search_web":
            continue
        if item.get("status") != "completed":
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        for hit in result.get("results") or []:
            if not isinstance(hit, dict):
                continue
            url = hit.get("url")
            try:
                parsed = urlsplit(url)
            except (ValueError, TypeError):
                continue
            if (parsed.scheme != "https" or parsed.hostname not in
                    {"www.bmas.de", "bmas.de"} or
                    parsed.username or parsed.password or
                    parsed.port not in {None, 443}):
                continue
            if any(
                isinstance(step, dict) and step.get("action") == "fetch_url"
                and (step.get("query") == url)
                for step in observations
            ):
                continue
            title = str(hit.get("title") or "").casefold()
            snippet = str(hit.get("snippet") or "").casefold()
            path = parsed.path.casefold()
            topic = title + " " + snippet + " " + path
            if not re.search(
                r"urlaub|teilzeit|arbeitsrecht|mindesturlaub", topic
            ):
                continue
            score = 10 * bool(re.search(r"urlaub|urlaubsanspruch", topic))
            score += 25 * bool("teilzeit" in topic)
            score += 15 * bool("fragen-und-antworten" in path or "/faq-" in path)
            score += 15 * bool("brückenteilzeit" in topic or "brueckenteilzeit" in topic)
            matches.append((score, url))

    if matches:
        _, url = max(matches, key=lambda pair: pair[0])
        return {
            "action": "fetch_url", "query": url,
            "reason": "Amtliche Erläuterung zur Umrechnung der gesetzlichen Urlaubstage öffnen",
        }

    previous = {
        " ".join(str(item.get("query") or "").split()).casefold()
        for item in observations or []
        if isinstance(item, dict) and item.get("action") == "search_web"
    }
    if _QUERY.casefold() not in previous:
        return {
            "action": "search_web", "query": _QUERY,
            "reason": "Amtliche Erklärung zu fünf Arbeitstagen statt sechs Werktagen suchen",
        }
    return None


def needs_leave_explanation(goal, observations):
    return choose_leave_explanation_step(goal, observations) is not None



# Two bounded publisher-discovery queries; neither constructs an article path.
_LAW_DISCOVERY_QUERY = "gesetze-im-internet.de Bundesurlaubsgesetz § 3 Mindesturlaub"
_LAW_REFINEMENT_QUERY = "bmas.de Mindesturlaub Fünf-Tage-Woche Urlaubsanspruch"


def choose_leave_official_discovery_step(goal, observations):
    """Get an observed official law/FAQ URL before model-led broad searching.

    Only applies to the explicitly asked five-day statutory minimum. Search
    results are navigation hints, NEVER a basis for asserting a leave count.
    """
    if not _five_day_leave_question(goal):
        return None
    if _official_law_source_loaded(observations) or _explanatory_source_loaded(observations):
        return None

    fetched = {
        str(step.get("query") or "")
        for step in observations or ()
        if isinstance(step, dict) and step.get("action") == "fetch_url"
    }
    discovered = []
    for step in observations or ():
        if (not isinstance(step, dict) or step.get("action") != "search_web"
                or step.get("status") != "completed"
                or not isinstance(step.get("result"), dict)):
            continue
        for hit in step["result"].get("results") or ():
            if not isinstance(hit, dict):
                continue
            url = hit.get("url")
            try:
                parts = urlsplit(url)
            except (TypeError, ValueError):
                continue
            if (parts.scheme != "https" or parts.username is not None
                    or parts.password is not None or
                    parts.port not in {None, 443} or url in fetched):
                continue
            host, path = parts.hostname, parts.path.casefold()
            law = host in {"gesetze-im-internet.de", "www.gesetze-im-internet.de"} and (
                path.startswith("/burlg/")
            )
            faq = host in {"bmas.de", "www.bmas.de"} and (
                ("urlaub" in path or "teilzeit" in path or
                 "urlaub" in str(hit.get("title") or "").casefold())
            )
            if law or faq:
                discovered.append((2 if law else 1, url))
    if discovered:
        _, selected = max(discovered, key=lambda entry: entry[0])
        return {
            "action": "fetch_url", "query": selected,
            "reason": "Tatsächlich gefundenen amtlichen Gesetzestext oder Ministeriumsartikel laden",
        }

    tried = {
        " ".join(str(step.get("query") or "").casefold().split())
        for step in observations or ()
        if isinstance(step, dict) and step.get("action") == "search_web"
    }
    for query in (_LAW_DISCOVERY_QUERY, _LAW_REFINEMENT_QUERY):
        if " ".join(query.casefold().split()) not in tried:
            return {
                "action": "search_web", "query": query,
                "reason": "Amtliche Rechtsquelle zur angefragten Fünf-Tage-Woche suchen",
            }
    return None
