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
            return True  # Let the normal verifier judge its actual contents.
    return False


_QUERY = '!go site:bmas.de "5-Tage-Woche" "Mindesturlaub" Arbeitstage'


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
            score += 5 * bool("teilzeit" in topic)
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
