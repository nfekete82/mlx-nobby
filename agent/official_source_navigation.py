"""General, source-grounded routing for questions naming an official publisher.

A canonical domain here is a *search constraint* and an authority preference,
never evidence, an invented article URL, or permission to bypass URL guards.
Every fetch must use an actual search hit or same-host hyperlink discovered
from a successfully loaded page. Ambiguous questions use the model planner.
"""
import re
from urllib.parse import urlsplit

# Explicitly named institutions only; adding one requires tests. The same
# algorithm handles other institutions without per-question answer templates.
_PUBLISHERS = (
    (("robert koch-institut", "robert-koch-institut", "rki"), "rki.de"),
    (("europäische zentralbank", "europäischen zentralbank",
      "europäischer zentralbank", "european central bank", "ezb", "ecb"), "ecb.europa.eu"),
    (("internet engineering task force", "ietf", "rfc editor"), "rfc-editor.org"),
)
_STOP = frozenset((
    "welche", "welcher", "welches", "wie", "viele", "viel", "hoch", "ist", "sind",
    "der", "die", "das", "den", "dem", "des", "einer", "eines", "eine", "einem",
    "in", "im", "am", "auf", "aus", "von", "laut", "bei", "und", "oder", "nach",
    "aktuell", "derzeit", "typischen", "entsprechenden", "bitte", "nennt",
    "seit", "welchem", "datum", "wird", "werden", "zum", "zur", "offiziell",
    "offiziellen", "website", "seite", "rfc", "rfcs", "haben", "gilt",
    "dieser", "diese", "diesen", "zinssatz", "sowie",
))


def _publisher(goal):
    value = str(goal or "").casefold()
    found = [
        host for aliases, host in _PUBLISHERS
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", value)
               for alias in aliases)
    ]
    return found[0] if len(found) == 1 else None


def _safe_official_url(url, host):
    if not isinstance(url, str) or len(url) > 1200:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https"
                or not (parsed.hostname == host or (parsed.hostname or "").endswith("." + host))
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443}):
            return None
    except (ValueError, TypeError):
        return None
    return parsed


def _topic_terms(goal):
    text = str(goal or "").casefold()
    for aliases, _ in _PUBLISHERS:
        for alias in sorted(aliases, key=len, reverse=True):
            text = re.sub(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", " ", text)
    words = [w for w in re.findall(r"[\w]+", text)
             if len(w) > 2 and w not in _STOP]
    # Cross-language concept hints are for search only, not evidence.
    if any(w.startswith(("symptom", "krankheitsbild")) for w in words):
        words.append("symptoms")
    if any(w.startswith(("einlage", "deposit")) for w in words):
        words.extend(("deposit", "facility", "rate", "effective"))
    if any(w.startswith(("adress", "ipv")) for w in words):
        words.extend(("address", "bits"))
    # "RFC" on its own labels thousands of unrelated index entries;
    # a document is relevant only through its actual topic or RFC number
    # explicitly given in the question.
    terms = list(dict.fromkeys(words))
    # Protocol / version identifiers are much more discriminative than
    # generic measurement units in technical search queries.
    names = [w for w in terms if re.fullmatch(r"[a-z]{2,15}\d{1,4}", w)]
    return (names + [w for w in terms if w not in names])[:9]


def choose_official_publisher_step(goal, observations):
    host = _publisher(goal)
    if not host:
        return None
    terms = _topic_terms(goal)
    if not terms:
        return None
    if not observations:
        return {
            "action": "search_web",
            "query": f"{host} {' '.join(terms[:7])}",
            "reason": "Genannte Institution mit präzisen Fachbegriffen suchen",
        }
    fetched = {
        str(o.get("query") or "")
        for o in observations if isinstance(o, dict) and o.get("action") == "fetch_url"
    }
    loaded = [o for o in observations if isinstance(o, dict)
              and o.get("action") == "fetch_url"
              and o.get("status") == "completed"
              and isinstance(o.get("result"), dict)
              and o["result"].get("ok") is True]
    # One genuinely fetched official source is enough to hand over to evidence
    # unless it has a useful same-site topic link. No speculative cycling.
    matches = []
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("status") != "completed":
            continue
        result = observation.get("result")
        if not isinstance(result, dict):
            continue
        if observation.get("action") == "search_web":
            links = result.get("results")
            base_score = 0
        elif observation.get("action") == "fetch_url" and result.get("ok") is True:
            origin = result.get("final_url") or result.get("url")
            if _safe_official_url(origin, host) is None:
                continue
            links = result.get("page_links")
            base_score = 15
        else:
            continue
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict) or link.get("source_type") == "rss_search_entry":
                continue
            url = link.get("url")
            parsed = _safe_official_url(url, host)
            if parsed is None or url in fetched:
                continue
            name = " ".join((parsed.path.lower(),
                            str(link.get("title") or "").casefold(),
                            str(link.get("snippet") or "").casefold()))
            word_hits = sum(bool(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", name))
                            for w in terms)
            # A publisher domain or its index is not relevant evidence.
            # In particular, RFC indexes and their numeric navigation links
            # must not be followed based on the word "RFC" alone.
            if host == "rfc-editor.org" and re.search(
                r"(?i)/(?:rfc-index|(?:info|rfc)/rfc\d+)(?:/|$)", parsed.path
            ) and not word_hits:
                continue
            # Page hyperlinks need a topic match, not just same-host status.
            if base_score and not word_hits:
                continue
            # Specific document beats generic login/home index even when its
            # query match is only in the path. Scores never prove correctness.
            is_home = bool(re.search(r"/home/(?:html/)?index\.", parsed.path, re.I))
            score = (base_score + 8 * word_hits + 4 * bool(parsed.path not in {"", "/"})
                     + 8 * is_home)
            if re.search(r"/(?:login|signin|account|user)/", parsed.path, re.I):
                score -= 100
            matches.append((score, url))
    if matches:
        score, url = max(matches, key=lambda pair: pair[0])
        # Accept either an explicitly topical hit or a discovered official
        # homepage on the first search; do not choose random official pages.
        if score >= 8 or (
            not loaded and urlsplit(url).path in {"", "/"}
        ):
            return {"action": "fetch_url", "query": url,
                    "reason": "Tatsächlich gefundene Primärquelle öffnen"}
    searches = [o for o in observations if isinstance(o, dict)
                and o.get("action") == "search_web"
                and o.get("status") == "completed"]
    if len(searches) == 1 and not loaded:
        # A second query drops quoted/site-scoped domains. The search engine
        # may ignore or overconstrain those tokens; use topical synonyms.
        alternates = [term for term in terms
                      if term not in {"bit", "bits", "address", "adressen", "symptoms"}]
        return {
            "action": "search_web",
            "query": " ".join((alternates or terms)[:5]) + " " + host,
            "reason": "Einmalige breitere Primärquellensuche mit Fachbegriffen",
        }
    return None



def missing_requested_identifiers(goal, observations):
    """Prevent premature synthesis for explicitly requested paired identifiers.

    Only unambiguous letter+digit names such as IPv4/IPv6 or USB3/USB4 are
    considered. This is a completeness hint, not a semantic fact checker.
    """
    names = list(dict.fromkeys(
        match.casefold() for match in re.findall(
            r"(?i)(?<!\w)[a-z]{2,12}\d{1,3}(?!\w)", str(goal or "")
        )
    ))
    if len(names) < 2 or len(names) > 5:
        return False
    texts = []
    for item in observations:
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or item.get("status") != "completed"):
            continue
        result = item.get("result")
        if (isinstance(result, dict) and result.get("ok") is True
                and isinstance(result.get("text"), str)):
            texts.append(result["text"].casefold())
    if not texts:
        return False
    corpus = "\n".join(texts)
    return any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", corpus)
               is None for name in names)



def has_discovered_deeper_primary_link(goal, observations):
    """Defer early evidence only when an actual on-page topical link is next.

    A broad official index is not necessarily the requested factual article.
    Follow one stronger document link before synthesis, without inventing a
    URL, looping through numbered indexes or suppressing useful evidence.
    """
    if not _publisher(goal):
        return False
    fetched_ok = [
        item for item in observations
        if isinstance(item, dict) and item.get("action") == "fetch_url"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
    ]
    if len(fetched_ok) != 1:
        return False
    choice = choose_official_publisher_step(goal, observations)
    if choice is None or choice.get("action") != "fetch_url":
        return False
    target = choice.get("query")
    # A real link must appear in the one loaded page, not merely in search.
    links = fetched_ok[0]["result"].get("page_links")
    return isinstance(links, list) and any(
        isinstance(link, dict) and link.get("url") == target
        for link in links
    )
