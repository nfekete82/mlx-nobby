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
                and parsed.path.startswith("/burlg/")
                and re.search(r"(?i)\b24\s+werktagen?\b",
                              str(result.get("text") or ""))):
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


_QUERY = 'bmas.de Brückenteilzeit Urlaubsanspruch Mindesturlaub Fünf-Tage-Woche'
_FAQ_HEADING_QUERY = 'bmas.de "Wie verändert sich mein Urlaubsanspruch" Brückenteilzeit'


def choose_leave_explanation_step(goal, observations):
    if not _five_day_leave_question(goal):
        return None
    if not _official_law_source_loaded(observations):
        return None
    if _explanatory_source_loaded(observations):
        return None

    # The BMAS FAQ is long; the five-day annual-leave paragraph often lies
    # beyond the first 18k-character HTML excerpt. Reread the SAME actual
    # fetched URL once at its authentic topic heading, not a new source.
    for item in reversed(observations or ()):
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url")
        try:
            parsed = urlsplit(url)
        except (TypeError, ValueError):
            continue
        if (parsed.scheme != "https" or
                parsed.hostname not in {"www.bmas.de", "bmas.de"} or
                not re.search(r"(?i)(?:fragen-und-antworten|/faq[-/])",
                              parsed.path)):
            continue
        if not any(
            isinstance(attempt, dict) and attempt.get("action") == "fetch_url"
            and attempt.get("query") == url
            and "focus=" in str(attempt.get("instruction") or "")
            for attempt in observations
        ):
            return {
                "action": "fetch_url", "query": url,
                "instruction": "focus=Wie verändert sich mein Urlaubsanspruch",
                "reason": "Originalen Urlaubsanspruch-Abschnitt derselben amtlichen FAQ lesen",
            }

    # If the search provider indexes only the ministry homepage, navigate
    # its REAL same-host links towards employment law, part-time and FAQs.
    # Stop after four different official BMAS pages to bound exploration.
    fetched_urls = {
        str(item.get("query") or "")
        for item in observations or ()
        if isinstance(item, dict) and item.get("action") == "fetch_url"
    }
    bmas_fetches = []
    for item in observations or ():
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or item.get("status") != "completed"
                or not isinstance(item.get("result"), dict)
                or item["result"].get("ok") is not True):
            continue
        result = item["result"]
        try:
            source = urlsplit(result.get("final_url") or result.get("url"))
        except (TypeError, ValueError):
            continue
        if source.scheme != "https" or source.hostname not in {"bmas.de", "www.bmas.de"}:
            continue
        bmas_fetches.append(result)
    if bmas_fetches and len(bmas_fetches) < 4:
        links = []
        for page in bmas_fetches:
            origin = urlsplit(page.get("final_url") or page.get("url"))
            for link in page.get("page_links") or ():
                if not isinstance(link, dict):
                    continue
                url = link.get("url")
                try:
                    target = urlsplit(url)
                except (TypeError, ValueError):
                    continue
                if (target.scheme != "https" or target.hostname != origin.hostname
                        or target.username or target.password
                        or target.port not in {None, 443}
                        or url in fetched_urls):
                    continue
                path, title = target.path.casefold(), str(link.get("title") or "").casefold()
                hint = path + " " + title
                if not re.search(r"urlaub|arbeitsrecht|teilzeit|brueckenteilzeit|brückenteilzeit", hint):
                    continue
                score = (100 * bool("faq-brueckenteilzeit" in path)
                         + 60 * bool("fragen-und-antworten" in path)
                         + 40 * bool("teilzeit" in path)
                         + 20 * bool("arbeitsrecht" in path)
                         + 5 * bool("urlaub" in hint))
                links.append((score, url))
        if links:
            _, selected = max(links, key=lambda item: item[0])
            return {
                "action": "fetch_url", "query": selected,
                "reason": "Auf echter BMAS-Seite verlinkte Arbeitsrechts-/Urlaubs-FAQ prüfen",
            }

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

    # A search provider can return only BMAS homepages for the generic
    # workweek query. Ask for an exact publisher FAQ heading once before
    # visiting further generic navigation pages. The title is a navigation
    # hint; only the fetched official article can establish the actual days.
    search_queries = {
        " ".join(str(item.get("query") or "").casefold().split())
        for item in observations or ()
        if isinstance(item, dict) and item.get("action") == "search_web"
        and item.get("status") == "completed"
    }
    if (_QUERY.casefold() in search_queries
            and _FAQ_HEADING_QUERY.casefold() not in search_queries):
        return {
            "action": "search_web", "query": _FAQ_HEADING_QUERY,
            "reason": "Amtliche FAQ anhand der tatsächlich veröffentlichten Abschnittsüberschrift suchen",
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
    # The publisher itself was found, but the search index omitted deep FAQs.
    # Enter its observed homepage and follow real links; never synthesize the
    # ministerial FAQ path. Do not open the homepage more than once.
    for item in observations or ():
        if (not isinstance(item, dict) or item.get("action") != "search_web"
                or item.get("status") != "completed"
                or not isinstance(item.get("result"), dict)):
            continue
        for hit in item["result"].get("results") or ():
            if not isinstance(hit, dict):
                continue
            url = hit.get("url")
            try:
                parsed = urlsplit(url)
            except (TypeError, ValueError):
                continue
            if (parsed.scheme == "https"
                    and parsed.hostname in {"bmas.de", "www.bmas.de"}
                    and parsed.path.casefold() in {
                        "/de/startseite/start.html", "/en/home/home.html",
                    } and url not in fetched_urls):
                return {
                    "action": "fetch_url", "query": url,
                    "reason": "Gefundene amtliche BMAS-Startseite als Navigationsquelle öffnen",
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
    # A publisher table of contents is NOT the law text. Follow its
    # authentic link to the complete HTML statute before trying a
    # different search engine. Never synthesize a law document URL.
    for step in observations or ():
        if (not isinstance(step, dict) or step.get("action") != "fetch_url"
                or step.get("status") != "completed"
                or not isinstance(step.get("result"), dict)
                or step["result"].get("ok") is not True):
            continue
        page = step["result"]
        try:
            origin = urlsplit(page.get("final_url") or page.get("url"))
        except (ValueError, TypeError):
            continue
        if (origin.scheme != "https" or origin.hostname not in
                {"www.gesetze-im-internet.de", "gesetze-im-internet.de"}
                or origin.path.rstrip("/") != "/burlg"):
            continue
        for link in page.get("page_links") or ():
            if not isinstance(link, dict):
                continue
            destination = link.get("url")
            try:
                target = urlsplit(destination)
            except (ValueError, TypeError):
                continue
            if (target.scheme != "https" or target.hostname != origin.hostname
                    or target.username or target.password
                    or target.port not in {None, 443} or destination in fetched):
                continue
            if re.fullmatch(r"(?i)/burlg/BJNR\d+\.html", target.path):
                return {
                    "action": "fetch_url", "query": destination,
                    "reason": "Aus verifiziertem Gesetzes-Inhaltsverzeichnis verlinkte Gesamtausgabe öffnen",
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
                if law:
                    # The full HTML statute carries the actual paragraphs.
                    # A directory or a tiny §3 fragment is weaker evidence.
                    if re.fullmatch(r"(?i)/burlg/BJNR\d+\.html", path):
                        score = 100
                    elif re.fullmatch(r"(?i)/burlg/__\d+\.html", path):
                        score = 20
                    else:
                        score = 10
                else:
                    score = 5
                discovered.append((score, url))
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
