"""General, source-grounded routing for questions naming an official publisher.

Canonical publisher hosts are registry entries, never evidence. Article URLs
must be actual search hits or same-host links from loaded official pages.
After repeated unusable searches a publisher's exact HTTPS ROOT may be used
as a bounded discovery entry point, never as authority for unquoted facts.
Ambiguous questions use the model planner.
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
    (("national aeronautics and space administration", "nasa"), "nasa.gov"),
    (("bundeszentrale für politische bildung", "bundeszentrale fuer politische bildung",
      "bpb"), "bpb.de"),
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
    # German compound nouns may name the same event as separate query words:
    # "Berliner Mauer" -> "Mauerfall". This only affects discovery ranking;
    # it never supplies an answer or constructs a URL.
    if "mauer" in words:
        words.append("mauerfall")
    # "RFC" on its own labels thousands of unrelated index entries;
    # a document is relevant only through its actual topic or RFC number
    # explicitly given in the question.
    terms = list(dict.fromkeys(words))
    # Technical source terminology may differ from a colloquial German term.
    # These are query synonyms only, never facts or unobserved source URLs.
    if any(w.startswith("einlagezins") for w in terms):
        terms = list(dict.fromkeys(["deposit", "facility", "key", "interest", "rates"] + terms))
    # Protocol / version identifiers are more discriminative than generic
    # measurement units and should dominate the initial search query.
    names = [w for w in terms if re.fullmatch(r"[a-z]{2,15}\d{1,4}", w)]
    return (names + [w for w in terms if w not in names])[:9]


def _nasa_numbered_mission(goal):
    """Find a requested numbered mission without inferring an article URL."""
    if _publisher(goal) != "nasa.gov":
        return None
    match = re.search(
        r"(?i)\b(?:apollo|artemis|gemini|mercury)\s+\d{1,3}\b",
        str(goal or ""),
    )
    return " ".join(match.group(0).casefold().split()) if match else None


def _nasa_landing_chronology_step(goal, observations):
    """Follow a discovered mission chronology when a landing *day* is asked.

    A mission profile may state launch, splashdown and moonwalk dates without
    explicitly anchoring the date of touchdown. Following a genuine NASA
    mission overview provides the verifier with more precise event context;
    this step never supplies a date or invents a URL.
    """
    mission = _nasa_numbered_mission(goal)
    question = str(goal or "").casefold()
    if not mission or not re.search(r"\b(?:wann|when)\b", question) or not re.search(
        r"\b(?:landete|landed|landung|landing|touchdown)\b", question
    ):
        return None
    name, number = mission.split()
    expected = re.compile(
        r"(?i)(?:^|/)" + re.escape(name) + r"[-_]" + re.escape(number) +
        r"[-_]mission[-_]overview/?$"
    )
    profile_path = "/" + "mission/" + name + "-" + number
    fetched_urls = {
        str(item.get("query") or "")
        for item in observations if isinstance(item, dict)
        and item.get("action") == "fetch_url"
    }
    profiles = []
    for item in observations:
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or item.get("status") != "completed"):
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        parsed = _safe_official_url(
            result.get("final_url") or result.get("url"), "nasa.gov"
        )
        if parsed and parsed.path.rstrip("/").casefold() == profile_path:
            profiles.append(result)
    # Only one follow-up per exact mission profile and only a real link
    # in that fetched profile. Never repeat after the chronology is loaded.
    for profile in profiles[:1]:
        for link in profile.get("page_links") or []:
            if not isinstance(link, dict):
                continue
            url = link.get("url")
            parsed = _safe_official_url(url, "nasa.gov")
            if (parsed and url not in fetched_urls
                    and expected.search(parsed.path)):
                return {
                    "action": "fetch_url", "query": url,
                    "reason": "Verlinkte NASA-Missionschronologie für genaues Landedatum lesen",
                }
    return None


def clinical_presentation_question(goal):
    """Clinical features, not vaccination effects or outbreak statistics."""
    return bool(
        _publisher(goal)
        and re.search(r"(?i)\b(?:symptom\w*|krankheitsbild|symptomatik|clinical signs)\b",
                      str(goal or ""))
        and not re.search(r"(?i)\b(?:impf\w*|vaccin\w*|nebenwirkung\w*)\b",
                          str(goal or ""))
    )


def _irrelevant_clinical_variant(goal, url, title=""):
    """A veterinary/zoonotic influenza article is not a seasonal flu answer."""
    if not clinical_presentation_question(goal):
        return False
    question = str(goal).casefold()
    if re.search(r"(?i)\b(?:zoonot\w*|vogelgrippe|aviär\w*|avian|schweinegrippe)\b",
                 question):
        return False
    try:
        path = urlsplit(str(url or "")).path
    except (ValueError, TypeError):
        return False
    # Source labels matter: mixed directory pages can mention both families.
    marker = path + " " + str(title or "")
    return bool(re.search(
        r"(?i)zoonotische[-_/ ]*influenza|zoonotisch|"
        r"vogelgrippe|avi[aä]r(?:e|en|es)?[-_ ]*influenza|"
        r"animal[-_ ]*influenza",
        marker,
    ))


def missing_clinical_article(goal, observations):
    """Navigation hint: loaded article text lacks an explanatory clinical passage.

    This heuristic cannot certify medical facts; extraction/verification must
    still inspect source-exact anchored passages. Exclude bibliographies and
    general epidemiological indices from early evidence synthesis.
    """
    if not clinical_presentation_question(goal):
        return False
    official = _publisher(goal)
    bodies = []
    seen_official = False
    for item in observations:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True
                or _safe_official_url(result.get("final_url") or result.get("url"),
                                      official) is None):
            continue
        seen_official = True
        source_url = result.get("final_url") or result.get("url") or ""
        if _irrelevant_clinical_variant(goal, source_url):
            continue
        # A vaccine side-effects page is not evidence about presentation of
        # the infection, even if both pages mention similar symptoms.
        if re.search(r"(?i)(?:^|/)(?:impfen|impfungen)(?:/|$)", urlsplit(source_url).path):
            continue
        if isinstance(result.get("text"), str):
            bodies.append(result["text"])
    if not bodies:
        return seen_official

    # Strong *source relevance* indicators only. These are not symptom values
    # and should never be used to synthesize a medical answer.
    topic_terms = [w for w in _topic_terms(goal)
                   if w not in {"symptom", "symptome", "symptoms"}]
    for body in bodies:
        for line in body.splitlines():
            normalized = " ".join(line.casefold().split())
            if len(normalized) < 45 or len(normalized) > 1500:
                continue
            if re.search(r"(?i)\b(?:epid(?:emiologisches)? bull(?:etin)?|literatur|referenzen)\b",
                         normalized):
                continue
            if topic_terms and not any(term in normalized for term in topic_terms):
                continue
            if re.search(
                r"(?i)\b(?:symptomatik|symptome|krankheitsbild|"
                r"beginnt|auftreten|gekennzeichnet|äußert sich|"
                r"manifestiert sich|clinical presentation)\b",
                normalized,
            ) and re.search(
                r"(?i)\b(?:ist|sind|durch|mit|bei|"
                r"beginnt|auftreten|gekennzeichnet|gehören|zeigt)\b",
                normalized,
            ):
                return False
    return True


def official_home_fallback_host(goal, observations):
    """Authorize publisher-root discovery after two DISTINCT completed queries.

    Duplicate/cached observations or fabricated step counts do not justify a
    new fetch. This only enables an exact registered HTTPS homepage; article
    subpaths still require actual search/link provenance.
    """
    host = _publisher(goal)
    if not host:
        return None
    queries = set()
    for item in observations or ():
        if (not isinstance(item, dict)
                or item.get("action") != "search_web"
                or item.get("status") != "completed"
                or not isinstance(item.get("result"), dict)):
            continue
        query = item.get("query")
        if isinstance(query, str) and query.strip():
            queries.add(" ".join(query.casefold().split()))
    return host if len(queries) >= 2 else None


def missing_official_answer_document(goal, observations):
    """Topic-only check: page navigation cannot certify an answer."""
    host = _publisher(goal)
    q = str(goal or "").casefold()
    paired = (
        host == "rfc-editor.org"
        and len(set(re.findall(r"(?i)(?<!\w)[a-z]{2,12}\d{1,3}(?!\w)", q))) >= 2
        and bool(re.search(r"(?i)\bbits?\b", q))
    )
    deposit = host == "ecb.europa.eu" and (
        "einlagezins" in q or "deposit facility" in q
    )
    # Publisher homepages are discovery pages, not the requested NASA/bpb
    # historical article. This is a document-completeness check only; values
    # and even the existence of a qualifying article remain unverified.
    publisher_home = host in {"nasa.gov", "bpb.de"}
    if not (paired or deposit or publisher_home):
        return False
    loaded = []
    for item in observations or ():
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        parsed = _safe_official_url(result.get("final_url") or result.get("url"), host)
        if parsed is not None:
            loaded.append((parsed.path.casefold(), str(result.get("text") or "").casefold()))
    if not loaded:
        return False
    if publisher_home:
        # General homepages and mission directories are discovery surfaces,
        # not factual articles. A genuinely fetched document is needed.
        if host == "nasa.gov" and _nasa_numbered_mission(goal):
            return all(
                path in {"", "/"} or
                bool(re.search(r"/(?:a-to-z-of-nasa-missions|nasa-missions|missions)/?$", path))
                for path, _ in loaded
            )
        return all(path in {"", "/"} for path, _ in loaded)
    if paired:
        # A document that covers IPv4 alone is not a complete source set
        # for a paired IPv4+IPv6 request. Its 32-bit statement must not
        # suppress discovery of the missing IPv6 specification.
        if missing_requested_identifiers(goal, observations):
            return True
        return not any(
            re.search(r"/(?:info|rfc)/rfc\d+", path)
            and re.search(r"\b(?:ipv4|ipv6|ip version [46])\b", body)
            and re.search(r"\bbits?\b", body)
            for path, body in loaded
        )
    # An explicitly focused, source-exact homepage excerpt can itself be
    # a primary source when the page publishes its policy rate next to the
    # applicable date. Mere topic mentions or unrelated rate headlines
    # are not enough. This is a completeness hint, NOT value verification.
    for item in observations or ():
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True
                or result.get("focus") != "deposit facility"):
            continue
        url = result.get("final_url") or result.get("url")
        if _safe_official_url(url, host) is None:
            continue
        body = str(result.get("text") or "")
        rate = re.search(
            r"(?is)\bdeposit facility\b[^\n]{0,100}\b\d{1,3}(?:[.,]\d{1,4})?\s*%",
            body,
        )
        if rate and re.search(
            r"\b(?:19|20)\d{2}\b", body[rate.start():rate.end()+500]
        ):
            return False
    # A dedicated monetary-policy rate document is an appropriate place to
    # hand off to source-exact extraction, even when its loaded snippet
    # ultimately proves too thin and the verifier must abstain. Do not keep
    # navigating after reaching that documented source family.
    return not any(
        re.search(r"key.ecb.interest.rates|monetary.policy.decisions|"
                  r"monetary-policy-decisions|key.interest.rates", path)
        for path, _body in loaded
    )


def choose_official_publisher_step(goal, observations):
    host = _publisher(goal)
    if not host:
        return None
    terms = _topic_terms(goal)
    if not terms:
        return None
    if not observations:
        query = f"{host} {' '.join(terms[:7])}"
        if clinical_presentation_question(goal):
            clinical_topics = [w for w in terms if w not in {
                "symptome", "symptom", "symptoms", "krankheitsbild",
            }]
            query = f"{host} {' '.join(clinical_topics[:3])} Krankheitsbild FAQ Symptome"
        return {
            "action": "search_web",
            "query": query,
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
    # A source-discovered chronology resolves the difference between a
    # mission's launch day, touchdown day and return day before synthesis.
    chronology = _nasa_landing_chronology_step(goal, observations)
    if chronology is not None:
        return chronology
    covered_identifiers, missing_identifiers = (), ()
    if loaded and missing_requested_identifiers(goal, observations):
        # After the first official document, pursue an explicitly requested
        # missing version once instead of repeatedly downloading more chunks
        # of a document about a different version. Values are not inferred.
        names = list(dict.fromkeys(match.casefold() for match in re.findall(
            r"(?i)(?<!\w)[a-z]{2,12}\d{1,3}(?!\w)", str(goal or "")
        )))
        corpus = "\n".join(str(item["result"].get("text") or "").casefold()
                           for item in loaded)
        present = [name for name in names if re.search(
            r"(?<!\w)" + re.escape(name) + r"(?!\w)", corpus
        )]
        missing = [name for name in names if name not in present]
        covered_identifiers, missing_identifiers = tuple(present), tuple(missing)
        # A generic index/homepage is not evidence for any requested
        # protocol. Only search for a *missing counterpart* once a loaded
        # source actually discusses another requested identifier.
        # Prevent repeating the specialized search after a failed attempt.
        already_refined = any(
            isinstance(item, dict)
            and item.get("action") == "search_web"
            and "RFC Internet Protocol Specification " + host in str(item.get("query") or "")
            for item in observations
        )
        recent_search = any(
            isinstance(item, dict) and item.get("action") == "search_web"
            for item in observations[observations.index(loaded[-1]) + 1:]
        )
        if present and missing and not recent_search and not already_refined:
            return {
                "action": "search_web",
                "query": f"{' '.join(missing[:2])} RFC Internet Protocol Specification {host}",
                "reason": "Gezielt nach der noch unbelegten angefragten Version suchen",
            }
    # Many official homepages contain current rates near the *bottom*
    # while the first 18k chars contain only media releases/navigation.
    # Re-fetch the exact same previously observed URL with a topic focus;
    # the fetch tool returns a verbatim excerpt with its original offset.
    if host == "ecb.europa.eu" and (
        "einlagezins" in str(goal).casefold()
        or "deposit facility" in str(goal).casefold()
    ):
        focused = any(
            isinstance(item, dict) and item.get("action") == "fetch_url"
            and (str(item.get("instruction") or "").casefold()
                 == "focus=deposit facility"
                 or (item.get("result") or {}).get("focus") == "deposit facility")
            for item in observations
        )
        if not focused:
            for item in reversed(loaded):
                result = item["result"]
                url = result.get("final_url") or result.get("url")
                parsed = _safe_official_url(url, host)
                if parsed is None or not (
                    parsed.path in {"", "/"}
                    or re.search(r"(?i)/home/(?:html/)?index\.", parsed.path)
                ):
                    continue
                if (result.get("truncated") is True
                        and type(result.get("next_offset")) is int):
                    return {
                        "action": "fetch_url",
                        "query": item.get("query") or url,
                        "instruction": "focus=deposit facility",
                        "reason": "Themenabschnitt derselben amtlichen Seite quellengetreu lesen",
                    }
    # Large technical standards are served in 18k character windows. If
    # the first page slice has no address-width statement, load the next
    # *same observed URL* with its advertised offset once. Do not construct
    # a sibling document URL or treat an offset as proof of the answer.
    if host == "rfc-editor.org" and re.search(r"(?i)\bbits?\b", str(goal or "")):
        for item in reversed(loaded):
            result = item["result"]
            url = result.get("final_url") or result.get("url")
            if _safe_official_url(url, host) is None:
                continue
            try:
                current_offset = result.get("offset")
                next_offset = result.get("next_offset")
                if (type(current_offset) is not int or current_offset != 0
                        or type(next_offset) is not int
                        or not 1000 <= next_offset <= 18000
                        or result.get("truncated") is not True):
                    continue
            except (ValueError, TypeError):
                continue
            if not re.search(r"(?i)/(?:info|rfc)/rfc\d+", urlsplit(url).path):
                continue
            # An additional chunk of an already covered protocol does not
            # help when the question explicitly still needs another version.
            # Preserve continuation for single-protocol questions and for
            # sources that actually mention the outstanding identifier.
            if missing_identifiers and covered_identifiers:
                document_text = str(result.get("text") or "").casefold()
                if any(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)",
                                 document_text) for p in covered_identifiers) and not any(
                    re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)",
                              document_text) for p in missing_identifiers
                ):
                    continue
            passage = str(result.get("text") or "")
            address_measurement = any(
                re.search(
                    r"(?i)(?:addresses?|adressen?)\W.{0,90}\b\d+\s*bits?\b"
                    r"|\b\d+\s*bits?\W.{0,90}(?:addresses?|adressen?)",
                    line,
                )
                for line in passage.splitlines()
            )
            if address_measurement:
                continue
            already_read = any(
                isinstance(other, dict) and other.get("action") == "fetch_url"
                and (other.get("result") or {}).get("offset") == next_offset
                and ((other.get("result") or {}).get("final_url")
                     or (other.get("result") or {}).get("url")) == url
                for other in observations
            )
            if not already_read:
                return {
                    "action": "fetch_url",
                    "query": url,
                    "instruction": f"offset={next_offset}",
                    "reason": "Fortsetzung desselben verifizierten RFC-Dokuments laden",
                }
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
            if _irrelevant_clinical_variant(goal, url, link.get("title")):
                continue
            name = " ".join((parsed.path.lower(),
                            str(link.get("title") or "").casefold(),
                            str(link.get("snippet") or "").casefold()))
            word_hits = sum(bool(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", name))
                            for w in terms)
            mission = _nasa_numbered_mission(goal)
            # A mission name without its requested number is not a match.
            # Scores choose among *discovered* links, never guessed URLs.
            normalized_name = re.sub(r"[^a-z0-9]+", " ", name)
            exact_mission = bool(mission and re.search(
                r"(?<!\w)" + re.escape(mission) + r"(?!\w)",
                normalized_name,
            ))
            if mission and word_hits and not exact_mission:
                continue
            # If the first requested identifier is already documented, do
            # not repeatedly crawl pages explicitly limited to that same
            # identifier while the other requested identifier is absent.
            missing_hits = any(re.search(
                r"(?<!\w)" + re.escape(w) + r"(?!\w)", name
            ) for w in missing_identifiers)
            covered_hits = any(re.search(
                r"(?<!\w)" + re.escape(w) + r"(?!\w)", name
            ) for w in covered_identifiers)
            if host == "rfc-editor.org" and covered_hits and not missing_hits:
                continue
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
            # Monetary-policy deposit rates differ from reference-rate benchmarks.
            deposit_question = host == "ecb.europa.eu" and (
                "einlagezins" in str(goal).casefold()
                or "deposit facility" in str(goal).casefold()
            )
            if deposit_question:
                if re.search(
                    r"(?i)euro.short.term.rates|interest.rate.benchmarks|"
                    r"risk.free.rates|fxrates|\bestr\b|€str",
                    name,
                ):
                    continue
                if not re.search(
                    r"(?i)deposit.facility|key.ecb.interest.rates|"
                    r"key.interest.rates|monetary.policy|"
                    r"geldpolitik|einlagefazilit|standing.facilit",
                    name,
                ):
                    # The homepage is a permitted discovery entry, never a
                    # policy-rate citation by itself.
                    landing = parsed.path in {"", "/"} or bool(re.search(
                        r"(?i)/home/(?:html/)?index\.", parsed.path,
                    ))
                    if loaded or not landing:
                        continue
            # Specific document beats generic login/home index even when its
            # query match is only in the path. Scores never prove correctness.
            is_home = bool(re.search(r"/home/(?:html/)?index\.", parsed.path, re.I))
            score = (base_score + 8 * word_hits + 4 * bool(parsed.path not in {"", "/"})
                     + 8 * is_home + 24 * bool(missing_hits))
            if exact_mission:
                score += 100
            if deposit_question:
                if re.search(r"(?i)deposit.facility|key.ecb.interest.rates|"
                             r"key.interest.rates|einlagefazilit|standing.facilit", name):
                    score += 40
                elif re.search(r"(?i)monetary.policy|geldpolitik", name):
                    score += 8
            # Side effects of vaccination must not be mistaken for clinical
            # symptoms of the disease. Only reject the irrelevant branch;
            # the fetched URL must still be independently discovered.
            if clinical_presentation_question(goal) and re.search(
                r"(?i)(?:^|/)(?:impfen|impfungen)(?:/|$)|impfung|vaccin",
                name,
            ):
                continue
            # Clinical presentation pages outrank generic disease indexes.
            if clinical_presentation_question(goal):
                if re.search(
                    r"(?i)symptom|krankheitsbild|(?:^|[/_.-])faq|"
                    r"antworten|häufige fragen|ratgeber|clinical",
                    name,
                ):
                    score += 20
                if re.search(r"(?i)(?:-node\.html|/rfc-index/|/index\.html)$", parsed.path):
                    score -= 12
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
    mission = _nasa_numbered_mission(goal)
    if mission and loaded:
        # After irrelevant external search results, navigate the publisher's
        # real A-to-Z directory link. Neither the path nor the facts are guessed.
        for item in reversed(loaded):
            for link in item["result"].get("page_links") or []:
                if not isinstance(link, dict):
                    continue
                url = link.get("url")
                label = str(link.get("title") or "")
                if (url not in fetched
                        and _safe_official_url(url, "nasa.gov") is not None
                        and re.search(r"(?i)a\s*(?:to|-|–)\s*z.*missions?",
                                      label + " " + url)):
                    return {
                        "action": "fetch_url", "query": url,
                        "reason": "Verlinktes NASA-Missionsverzeichnis öffnen",
                    }
    # If an official article was fetched but only general navigation or
    # bibliography was present, request a more precise search ONCE. No
    # invented URL or medical facts are created by this research fallback.
    if loaded and missing_clinical_article(goal, observations):
        topics = [w for w in terms if w not in {
            "symptome", "symptoms", "symptom", "krankheitsbild",
            "typische", "typischen", "faq",
        }]
        if host == "rki.de" and topics:
            # The generic RKI homepage is not medical evidence. Look for a
            # specific clinic FAQ by its subject, using an alternative actual
            # SearXNG engine. The resulting URL still has to be observed,
            # fetched and independently verified; no article path is guessed.
            refined = f'!go "Krankheitsbild der {topics[0]}" RKI symptomatik'
        else:
            refined = f"{host} {' '.join(topics[:3])} krankheitsbild FAQ symptomatik"
        attempted = any(
            isinstance(item, dict) and item.get("action") == "search_web"
            and " ".join(str(item.get("query") or "").casefold().split())
                == " ".join(refined.casefold().split())
            for item in observations
        )
        if not attempted:
            return {
                "action": "search_web", "query": refined,
                "reason": "Gezielt nach amtlicher klinischer Fachseite statt Institutionen-Homepage suchen",
            }
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
    # After an official source URL fails (e.g. HTTP 404), refine the
    # publisher-specific topic once instead of trusting dead search hits.
    # The refinement is ONLY a search query; fetched URLs must still be
    # observed original links and pass the research allowlist.
    failed_official = [
        o for o in observations if isinstance(o, dict)
        and o.get("action") == "fetch_url"
        and o.get("status") == "completed"
        and isinstance(o.get("result"), dict)
        and o["result"].get("ok") is False
        and _safe_official_url(
            o["result"].get("url") or o.get("query"), host
        ) is not None
    ]
    if failed_official and host == "ecb.europa.eu" and (
        "einlagezins" in str(goal).casefold()
        or "deposit facility" in str(goal).casefold()
    ):
        retry_query = f"standing facilities deposit facility rate effective date {host}"
        if not any(
            isinstance(o, dict) and o.get("action") == "search_web"
            and str(o.get("query") or "").casefold() == retry_query.casefold()
            for o in observations
        ):
            return {
                "action": "search_web", "query": retry_query,
                "reason": "Nicht erreichbare amtliche Zinsseite durch eine neue Quellensuche ersetzen",
            }

    if not loaded and official_home_fallback_host(goal, observations):
        # Search pollution may justify ONE root-only discovery after two
        # genuinely distinct searches. Replayed identical observations do
        # not trigger the fallback.
        root = f"https://www.{host}/"
        if root not in fetched:
            return {
                "action": "fetch_url",
                "query": root,
                "reason": "Offiziellen HTTPS-Einstiegspunkt nach irrelevanten Suchtreffern prüfen",
            }
    # One bounded source-discovery retry, never guessed factual values or URLs.
    if loaded and missing_official_answer_document(goal, observations):
        if host in {"nasa.gov", "bpb.de"}:
            # No guessed article path or historical facts: refine search only
            # after a genuine official homepage failed to yield a topical link.
            question_words = {"wann", "wer", "wurde", "angaben", "nenne", "quelle"}
            keywords = [term for term in terms if term not in question_words]
            if host == "nasa.gov" and any(term.startswith("mond") for term in keywords):
                keywords.extend(("moon", "landing"))
            refinement = f"{host} {' '.join(dict.fromkeys(keywords))} article history"
            attempted = any(
                isinstance(item, dict) and item.get("action") == "search_web"
                and str(item.get("query") or "").casefold() == refinement.casefold()
                for item in observations
            )
            if not attempted:
                return {
                    "action": "search_web", "query": refinement,
                    "reason": "Nach amtlichem Fachartikel statt allgemeiner Startseite suchen",
                }
            return None
        names = re.findall(
            r"(?i)(?<!\w)[a-z]{2,12}\d{1,3}(?!\w)", str(goal)
        )
        if host == "rfc-editor.org":
            # An initially generic RFC landing page and an already loaded
            # version-specific RFC need distinct follow-up queries. Never
            # guess a document number: the search backend must return the
            # specific RFC URL before we can fetch or cite it.
            target = names[-1] if names else ""
            if covered_identifiers and missing_identifiers:
                target = missing_identifiers[0]
                refinement = f"{target} Internet Protocol version specification RFC Editor"
            else:
                refinement = f"{target} address specification RFC {host}"
        else:
            refinement = f"deposit facility key ECB interest rates effective date {host}"
        attempted = any(
            isinstance(item, dict) and item.get("action") == "search_web"
            and str(item.get("query") or "").casefold() == refinement.casefold()
            for item in observations
        )
        if not attempted:
            return {
                "action": "search_web",
                "query": refinement,
                "reason": "Passende offizielle Fachquelle statt Übersichtsseite suchen",
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
    # A focused primary page that already contains an attributable rate
    # and effective date should go to the verifier before any link crawl.
    if (_publisher(goal) == "ecb.europa.eu"
            and not missing_official_answer_document(goal, observations)
            and any(
                isinstance(o, dict) and o.get("action") == "fetch_url"
                and isinstance(o.get("result"), dict)
                and o["result"].get("focus") == "deposit facility"
                for o in observations
            )):
        return False
    fetched_ok = [
        item for item in observations
        if isinstance(item, dict) and item.get("action") == "fetch_url"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
    ]
    if not 1 <= len(fetched_ok) <= 3:
        return False
    # After NASA's homepage, mission index and mission profile, allow one
    # *genuinely linked* chronology to resolve an explicitly requested day.
    # Ordinary research retains its existing two-page bound.
    chronology = (_nasa_landing_chronology_step(goal, observations)
                  if len(fetched_ok) == 3 else None)
    if len(fetched_ok) == 3 and chronology is None:
        return False
    choice = chronology or choose_official_publisher_step(goal, observations)
    if choice is None or choice.get("action") != "fetch_url":
        return False
    target = choice.get("query")
    # Follow only a real document linked by an already-loaded official page.
    # The research URL allowlist separately checks exact link provenance.
    # After two loaded pages, prefer substantive FAQ/guide/article links;
    # otherwise return current evidence without indefinite site crawling.
    links = [
        link for item in fetched_ok
        for link in (item["result"].get("page_links") or [])
        if isinstance(link, dict)
    ]
    discovered = [link for link in links if link.get("url") == target]
    mission = _nasa_numbered_mission(goal)
    if chronology is not None:
        return bool(discovered)
    if len(fetched_ok) == 2 and mission and any(
        re.search(r"(?<!\w)" + re.escape(mission) + r"(?!\w)",
                  re.sub(r"[^a-z0-9]+", " ",
                         str(link.get("title") or "").casefold() + " " +
                         str(link.get("url") or "").casefold()))
        for link in discovered
    ):
        return True
    if len(fetched_ok) == 2 and not any(re.search(
        r"(?i)faq|antwort|ratgeber|krankheitsbild|symptom|"
        r"clinical|/article/|/guide/|/report/",
        str(link.get("title") or "") + " " + str(link.get("url") or ""),
    ) for link in discovered):
        return False
    return bool(discovered)
