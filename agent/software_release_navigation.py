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

    # A source-linked official release article answers this question more
    # directly than another reread of the general downloads landing page.
    for item in observations or ():
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        try:
            fetched = urlsplit(result.get("final_url") or result.get("url"))
        except (TypeError, ValueError):
            continue
        if (fetched.scheme == "https" and fetched.hostname in
                {"www.python.org", "python.org"} and
                re.fullmatch(r"/downloads/release/python-3\d{2,4}/?", fetched.path)):
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
    # Do not wait for an unnecessary failed focus if the downloaded official
    # index already exposes an exact stable version article hyperlink.
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
                    parsed.port not in {None, 443}):
                continue
            matched = re.fullmatch(
                r"/downloads/release/python-(3)(\d{1,2})(\d{1,2})/?",
                parsed.path,
            )
            if not matched:
                continue
            # Only source-observed titles count; preview/beta/dev links are
            # excluded, but no release status is asserted by this selector.
            title = str(link.get("title") or "").strip()
            sem = re.fullmatch(r"Python\s+3\.(\d{1,2})\.(\d{1,2})", title, re.I)
            major, minor = int(matched.group(2)), int(matched.group(3))
            if sem:
                # An explicit title must agree with the *observed* URL.
                if (int(sem.group(1)), int(sem.group(2))) != (major, minor):
                    continue
            elif not re.fullmatch(r"(?i)download(?:\s+python)?", title):
                # "Download" labels are normal for release tables; other
                # unexplained/contradictory labels are not treated as releases.
                continue
            links.append(((major, minor), destination))
    if not links:
        return None
    # No speculative source discovery: without observed hyperlinks, retain
    # the previous focus-then-search fallback instead.
    # Choose the newest *observed* release first, including already attempted
    # links. If that link was fetched (successfully OR unsuccessfully), stop.
    # Do not fall back to an older release and mislabel it the latest.
    _version, selected = max(links, key=lambda p: p[0])
    if selected in attempted_urls:
        return None
    return {
        "action": "fetch_url", "query": selected,
        "reason": "Tatsächlich verlinkten offiziellen Python-Releaseartikel nach unlesbarer Übersicht prüfen",
    }


def needs_python_release_article(goal, observations):
    return python_source_linked_release_step(goal, observations) is not None



_PYTHON_SEARCH_QUERY = 'python.org "Latest Python 3 Release" stable releases'


def python_release_search_step(goal, observations):
    """Fallback to discovered official download/individual release after focus fails.

    A searched release URL is never synthesized from a version string.
    Search result text alone never establishes the current version.
    """
    if not python_latest_version_question(goal):
        return None
    failed_focus = any(
        isinstance(step, dict) and step.get("action") == "fetch_url"
        and step.get("status") == "completed"
        and isinstance(step.get("result"), dict)
        and step["result"].get("ok") is False
        and "focus=Active Python releases" in str(step.get("instruction") or "")
        for step in observations or ()
    )
    if not failed_focus:
        return None

    already = {
        str(step.get("query") or "")
        for step in observations or ()
        if isinstance(step, dict) and step.get("action") == "fetch_url"
    }
    # Stop after an actual alternate official release index has been read.
    # Its table still has to pass the normal evidence verifier.
    for step in observations or ():
        if not isinstance(step, dict) or step.get("action") != "fetch_url":
            continue
        result = step.get("result")
        if (step.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        try:
            loaded = urlsplit(result.get("final_url") or result.get("url"))
        except (TypeError, ValueError):
            continue
        if (loaded.scheme == "https" and loaded.hostname in
                {"python.org", "www.python.org"} and
                (loaded.path.rstrip("/") in
                 {"/downloads/macos", "/downloads/windows", "/downloads/source"}
                 or loaded.path.startswith("/downloads/release/python-3"))):
            return None

    found = []
    for step in observations or ():
        if (not isinstance(step, dict) or step.get("action") != "search_web"
                or step.get("status") != "completed"
                or not isinstance(step.get("result"), dict)):
            continue
        for result in step["result"].get("results") or ():
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            try:
                parsed = urlsplit(url)
            except (TypeError, ValueError):
                continue
            if (parsed.scheme != "https" or parsed.hostname not in
                    {"www.python.org", "python.org"} or
                    parsed.username is not None or parsed.password is not None
                    or parsed.port not in {None, 443}):
                continue
            path = parsed.path.casefold().rstrip("/")
            title = str(result.get("title") or "").casefold()
            # An official OS-specific releases directory exposes the
            # stable/pre-release separation and an explicit current heading.
            release_index = path in {
                "/downloads/windows", "/downloads/macos", "/downloads/source",
            }
            # A versioned article needs a source-backed title; whether it
            # is stable/latest must still pass the evidence verifier.
            version_article = (bool(re.fullmatch(
                r"/downloads/release/python-3\d{2,4}", path
            )) and "python 3." in title and
                not re.search(r"(?i)alpha|beta|pre-?release|rc\d|a\d|b\d", title))
            if release_index or version_article:
                priority = 30 if release_index else 15
                priority += 5 if "latest" in title else 0
                found.append((priority, url))
    if found:
        _, url = max(found, key=lambda hit: hit[0])
        if url in already:
            return None  # An older release is not newly "latest".
        return {
            "action": "fetch_url", "query": url,
            "reason": "Offizielle Python-Releaseübersicht aus echtem Suchtreffer laden",
        }
    attempted_queries = {
        " ".join(str(step.get("query") or "").casefold().split())
        for step in observations or ()
        if isinstance(step, dict) and step.get("action") == "search_web"
    }
    if " ".join(_PYTHON_SEARCH_QUERY.casefold().split()) not in attempted_queries:
        return {
            "action": "search_web", "query": _PYTHON_SEARCH_QUERY,
            "reason": "Alternative offizielle Releaseübersicht nach erfolglosem Textfokus finden",
        }
    return None


def needs_python_release_search(goal, observations):
    return python_release_search_step(goal, observations) is not None
