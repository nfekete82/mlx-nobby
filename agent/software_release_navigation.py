"""Follow up a loaded current-release download index with an original text focus.

Focus is not an invented release or a fabricated URL. It requests a source-
exact excerpt from the HTTPS page the agent already fetched and remains
subject to the ordinary per-passage semantic verifier.
"""
import re
from urllib.parse import urlsplit


def python_latest_version_question(goal):
    question = str(goal or "").casefold()
    return bool(
        re.search(r"(?:python\.org|\bpython[-\s]*3\b)", question)
        and re.search(r"\b(?:neueste|aktuell\w*|latest|newest|stabile|stable)\b", question)
        and re.search(r"\b(?:version|release|veröffentlicht|released)\b", question)
    )


def python_release_focus_step(goal, observations):
    """One focus on an already-fetched official index; never guess the URL."""
    if not python_latest_version_question(goal):
        return None

    candidates = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url")
        try:
            parsed = urlsplit(url)
        except (ValueError, TypeError):
            continue
        if (parsed.scheme != "https" or
                parsed.hostname not in {"www.python.org", "python.org"} or
                parsed.path.rstrip("/") != "/downloads"):
            continue
        if result.get("focus") is not None:
            return None
        candidates.append(url)

    if not candidates:
        return None
    url = candidates[-1]
    for item in observations or []:
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or str(item.get("query") or "") != url):
            continue
        if "focus=" in str(item.get("instruction") or "").casefold():
            return None
    return {
        "action": "fetch_url",
        "query": url,
        "instruction": "focus=Active Python releases",
        "reason": "Originalen aktuellen Versionsabschnitt der zuvor geladenen offiziellen Downloadseite lesen",
    }


def needs_python_release_focus(goal, observations):
    return python_release_focus_step(goal, observations) is not None



def python_source_linked_release_step(goal, observations):
    """After an unsuccessful focus, open a REAL linked final-release article.

    The title is only a relevance signal. The article itself must be fetched
    and its stability/currentness independently verified by the model.
    """
    if not python_latest_version_question(goal):
        return None
    failed_focus = False
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") == "completed" and isinstance(result, dict)
                and result.get("ok") is False
                and "focus=Active Python releases" in
                    str(item.get("instruction") or "")):
            failed_focus = True
            break
    if not failed_focus:
        return None

    attempted_urls = {
        str(item.get("query") or "")
        for item in observations or []
        if isinstance(item, dict) and item.get("action") == "fetch_url"
    }
    links = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url")
        try:
            origin = urlsplit(url)
        except (TypeError, ValueError):
            continue
        if (origin.scheme != "https" or origin.hostname not in
                {"www.python.org", "python.org"} or
                origin.path.rstrip("/") != "/downloads"):
            continue
        for link in result.get("page_links") or []:
            if not isinstance(link, dict):
                continue
            destination = link.get("url")
            try:
                parsed = urlsplit(destination)
            except (TypeError, ValueError):
                continue
            if (parsed.scheme != "https" or parsed.hostname != origin.hostname or
                    parsed.username is not None or parsed.password is not None or
                    parsed.port not in {None, 443} or
                    destination in attempted_urls):
                continue
            matched = re.fullmatch(
                r"/downloads/release/python-(3)(\d{1,2})(\d{1,2})/?",
                parsed.path,
            )
            if not matched:
                continue
            # Only source-observed titles count; preview/beta/dev links are
            # excluded, but no release status is asserted by this selector.
            title = str(link.get("title") or "")
            sem = re.fullmatch(r"Python\s+3\.(\d{1,2})\.(\d{1,2})", title, re.I)
            if not sem:
                continue
            major, minor = int(sem.group(1)), int(sem.group(2))
            if int(matched.group(2)) != major or int(matched.group(3)) != minor:
                continue
            links.append(((major, minor), destination))
    if not links:
        return None
    _version, selected = max(links, key=lambda p: p[0])
    return {
        "action": "fetch_url", "query": selected,
        "reason": "Tatsächlich verlinkten offiziellen Python-Releaseartikel nach unlesbarer Übersicht prüfen",
    }


def needs_python_release_article(goal, observations):
    return python_source_linked_release_step(goal, observations) is not None
