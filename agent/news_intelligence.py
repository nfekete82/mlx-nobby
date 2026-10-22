"""Verified-source news discovery: fixed publisher feeds and fetched article evidence.

A headline is never treated as a loaded article merely because it appears in
RSS, SearXNG or Google News. No arbitrary user-controlled feed URLs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape, unescape
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from backend.news_query import financial_news_topic, normalized_news_query
from backend.search_freshness import filter_today_news, publication_time, requires_today_news

FEEDS = (
    ("tagesschau", "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml", "tagesschau.de"),
    ("Deutschlandfunk", "https://www.deutschlandfunk.de/nachrichten-100.rss", "deutschlandfunk.de"),
    ("heise online", "https://www.heise.de/newsticker/heise-atom.xml", "heise.de"),
)
WRAPPERS = {"news.google.com", "google.com", "www.google.com",
            "lite.duckduckgo.com", "duckduckgo.com", "www.duckduckgo.com"}
STOP = {"dieser", "diese", "einem", "einer", "einen", "eines", "wegen",
        "durch", "heute", "aktuell", "neues", "neuen", "beim", "über",
        "gegen", "sowie", "nicht", "mehr", "noch", "sich", "oder", "aber",
        "news", "meldung", "nachrichten", "sagt", "dass", "wird", "sind",
        "from", "with", "that", "this", "their", "about"}


def host(url):
    try:
        p = urlparse(str(url or ""))
        return (p.hostname or "").lower() if p.scheme == "https" else ""
    except (ValueError, TypeError):
        return ""


def publisher_link(url, allowed_domain=None):
    name = host(url)
    if (not name or name in WRAPPERS or name.endswith(".google.com")
            or allowed_domain and not (name == allowed_domain or name.endswith("." + allowed_domain))):
        return False
    p = urlparse(url)
    return bool(p.path.strip("/") and not p.username and not p.password)


def _text(node, names):
    for part in node:
        if part.tag.rsplit("}", 1)[-1] in names and part.text:
            return unescape(part.text).strip()
    return ""


def _entries(root):
    if root.tag.rsplit("}", 1)[-1] == "feed":
        for entry in root:
            if entry.tag.rsplit("}", 1)[-1] != "entry":
                continue
            link = next((x.get("href", "") for x in entry
                         if x.tag.rsplit("}", 1)[-1] == "link"
                         and x.get("rel", "alternate") == "alternate"), "")
            yield _text(entry, {"title"}), link, _text(entry, {"published"})
    else:
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1] == "item":
                yield (_text(item, {"title"}), _text(item, {"link"}),
                       _text(item, {"pubDate", "date"}))


def publisher_news_candidates(query, *, opener=None, now=None, per_feed=6):
    """Discover dated headlines from three fixed feeds, only for broad daily news."""
    if (not requires_today_news(query) or financial_news_topic(query)
            or normalized_news_query(query) == query):
        return []
    opener = opener or urlopen
    now = now or datetime.now(timezone.utc)
    buckets = []
    for provider, url, domain in FEEDS:
        try:
            req = Request(url, headers={"User-Agent": "MLX-Nobby-News/1.0",
                                        "Accept": "application/xml,application/rss+xml,application/atom+xml"})
            with opener(req, timeout=4) as response:
                raw = response.read(160_001)
            if len(raw) > 160_000:
                raise ValueError("Feed too large")
            root = ET.fromstring(raw)
        except (OSError, ValueError, TimeoutError, ET.ParseError):
            buckets.append([])
            continue
        candidates = []
        for title, link, published in _entries(root):
            if title and published and publisher_link(link, domain):
                candidates.append({
                    "title": re.sub(r"\s+", " ", title)[:220],
                    "url": link[:2000],
                    "published_date": published[:100],
                    "engine": provider,
                    "source_type": "publisher_feed",
                    "article_loaded": False,
                })
            if len(candidates) >= 40:
                break
        buckets.append(filter_today_news(candidates, now=now)[:per_feed])
    result = []
    for index in range(per_feed):
        for bucket in buckets:
            if index < len(bucket):
                result.append(bucket[index])
    return result


def title_tokens(title):
    return {word for word in re.findall(r"[\wäöüß]{4,}", str(title).casefold())
            if word not in STOP and not word.isdigit()}


def readable_article(item):
    fetched = item.get("fetch")
    if not isinstance(fetched, dict) or fetched.get("ok") is not True:
        return False
    original = str(item.get("url") or "")
    final = str(fetched.get("url") or original)
    if not publisher_link(original) or not publisher_link(final):
        return False
    # A redirect to another host is not the original article.
    if host(original) != host(final):
        return False
    text = str(fetched.get("text") or "")
    if len(text.strip()) < 500:
        return False
    tokens = title_tokens(item.get("title", ""))
    if len(tokens) < 2:
        return False
    return sum(word in text.casefold() for word in tokens) >= min(3, len(tokens))


def _title_key(title):
    base = re.split(r"\s+[|–-]\s+", str(title or ""))[0]
    return frozenset(title_tokens(base))


def _safe_md(value):
    value = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    # News prose is untrusted HTML/Markdown content; do not emit tags.
    value = escape(value, quote=False)
    for char in ("\\", "[", "]", "(", ")", "*", "_"):
        value = value.replace(char, "\\" + char)
    return value


_SUMMARY_SENTENCE = re.compile(r"[^.!?\n]+[.!?](?=\s|$)", re.UNICODE)
_SUMMARY_JUNK = re.compile(
    r"(?i)\b(?:cookies?|datenschutz|newsletter|abonnieren|"
    r"werbung|weiterlesen|mehr zum thema|alle meldungen|"
    r"teilen sie|social media|javascript|kontakt|impressum|"
    r"registrieren|anmelden|zum inhalt)\b"
)


def article_short_summary(item, *, max_characters=330):
    """Select 1-2 short *verbatim* source sentences, never generate facts.

    Pick a substantive statement matching the headline's topic and, when
    useful, the immediately following sentence. A page without such evidence
    gets no summary rather than a plausible-sounding fabrication.
    """
    if not readable_article(item):
        return ""
    title = str(item.get("title") or "").strip()
    title_words = title_tokens(title)
    text = str(item["fetch"].get("text") or "")[:10000]
    if len(title_words) < 2:
        return ""

    candidates = []
    for match in _SUMMARY_SENTENCE.finditer(text):
        sentence = " ".join(unescape(match.group()).split()).strip(" \t-–•\"„“")
        if not (50 <= len(sentence) <= min(340, max_characters)):
            continue
        if not (7 <= len(sentence.split()) <= 55):
            continue
        if _SUMMARY_JUNK.search(sentence):
            continue
        tokens = title_tokens(sentence)
        overlap = len(title_words & tokens)
        # The bare headline is not a useful summary.
        title_normalized = re.sub(r"\W+", " ", title.casefold()).strip()
        text_normalized = re.sub(r"\W+", " ", sentence.casefold()).strip()
        if text_normalized == title_normalized or (
            text_normalized.startswith(title_normalized) and
            len(text_normalized) - len(title_normalized) < 35
        ):
            continue
        candidates.append((match.start(), sentence, overlap))

    suitable = [item for item in candidates if item[2] >= min(2, len(title_words))]
    if not suitable:
        return ""

    # A high headline overlap is evidence of topic relevance; position breaks
    # ties so boilerplate/related-article text near the end cannot dominate.
    first = max(suitable, key=lambda row: (min(row[2], 5), -row[0]))
    selected = [first[1]]
    remaining = max_characters - len(first[1])
    if remaining >= 85:
        for offset, sentence, overlap in candidates:
            if offset <= first[0] or offset - first[0] > 480:
                continue
            if sentence == first[1] or len(sentence) + 1 > remaining:
                continue
            # Adjacent article prose may use pronouns instead of title terms.
            if overlap >= 1 or offset - first[0] <= len(first[1]) + 12:
                selected.append(sentence)
                break
    return " ".join(selected)[:max_characters]


def grounded_news_digest(query, results, *, now=None, max_items=6):
    """An extractive headline overview: no generated details or invented events."""
    now = now or datetime.now(timezone.utc)
    same_day = requires_today_news(query)
    pool = filter_today_news(results, now=now) if same_day else list(results)
    items, seen_urls, seen_titles = [], set(), []
    for candidate in pool:
        if not isinstance(candidate, dict) or not readable_article(candidate):
            continue
        url = str(candidate["fetch"].get("url") or candidate["url"])
        parsed = urlparse(url)
        key = (host(url), parsed.path.rstrip("/"))
        title_key = _title_key(candidate.get("title"))
        if key in seen_urls or (title_key and any(
            len(title_key & past) / max(1, len(title_key | past)) >= .72
            for past in seen_titles
        )):
            continue
        published = publication_time(candidate.get("published_date"))
        if same_day and published is None:
            continue
        summary = article_short_summary(candidate)
        if not summary:
            # A readable webpage is insufficient: prefer another *grounded*
            # article rather than showing a headline without a useful brief.
            continue
        seen_urls.add(key)
        seen_titles.append(title_key)
        items.append({
            "title": str(candidate["title"])[:220], "url": url,
            "publisher": (str(candidate.get("engine") or host(url))[:100]
                          if candidate.get("source_type") == "publisher_feed"
                          else host(url)),
            "published_date": published.isoformat() if published else None,
            "article_loaded": True,
            "summary": summary,
        })
        if len(items) >= max_items:
            break
    day = now.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y")
    if not items and financial_news_topic(query):
        # An indexed headline is not a verified article. Nevertheless a dated,
        # relevant headline can be useful when the publisher article cannot be
        # loaded (notably Google News RSS redirects). Label this lower-evidence
        # mode explicitly; never invent a summary or a direct publisher URL.
        from backend.news_query import filter_financial_news_results
        headline_pool = filter_financial_news_results(query, pool)
        headline_items, headline_keys = [], set()
        for candidate in headline_pool:
            if not isinstance(candidate, dict):
                continue
            title = str(candidate.get("title") or "").strip()
            link = str(candidate.get("url") or "")
            published = publication_time(candidate.get("published_date"))
            title_key = _title_key(title)
            if not title_key or len(title_key) < 2 or not published:
                continue
            if not host(link) or not link.startswith("https://"):
                continue
            if title_key in headline_keys:
                continue
            # A current RSS publication date does not make a historical
            # retrospective into news about today's market.
            historical = re.search(r"\\b(?:19\\d{2}|20\\d{2})\\b", title)
            if historical and int(historical.group()) < now.year:
                continue
            headline_keys.add(title_key)
            headline_items.append({
                "title": title[:220], "url": link[:2000],
                "published_date": published.isoformat(),
                "article_loaded": False, "summary": "",
                "publisher": str(candidate.get("engine") or host(link))[:100],
                "evidence_level": "dated_headline_only",
            })
            if len(headline_items) >= max_items:
                break
        if headline_items:
            lines = [f"**Börsen-Schlagzeilen vom {day}**", "",
                     "*Nur datierte Überschriften aus dem Nachrichtenindex. "
                     "Die Originalartikel konnten nicht ausreichend verifiziert "
                     "werden; deshalb keine inhaltlichen Zusammenfassungen "
                     "oder daraus abgeleiteten Kursbehauptungen.*", ""]
            for item in headline_items:
                url = item["url"].replace("(", "%28").replace(")", "%29")
                local = datetime.fromisoformat(item["published_date"]).astimezone(
                    ZoneInfo("Europe/Berlin"))
                lines.append(
                    f"- **[{_safe_md(item['title'])}]({url})** "
                    f"— {local.strftime('%H:%M')} Uhr "
                    f"(Index-Zeitstempel; Originaltext ungeprüft)")
            return {
                "status": "headlines_only", "answer": "\\n".join(lines),
                "items": headline_items, "requested_count": max_items,
                "report_date": day, "evidence_level": "dated_headlines_only",
            }
    if not items:
        return {
            "status": "no_summarizable_articles",
            "answer": ("Für heute konnte ich keine ausreichend belegten Kurzmeldungen "
                       "zusammenstellen. Es fehlten lesbare, eindeutig datierte "
                       "Originalartikel mit genügend verwertbarem Text. "
                       "Ich ersetze fehlende Informationen nicht durch erfundene Zusammenfassungen."),
            "items": [], "evidence_level": "no_grounded_summaries",
        }
    lines = [f"**Nachrichtenüberblick vom {day}**", ""]
    if len(items) < max_items:
        lines.extend((
            f"*{len(items)} von {max_items} angefragten Nachrichten hatten "
            "ausreichend belegte Kurztexte.*", ""
        ))
    for item in items:
        url = item["url"].replace("(", "%28").replace(")", "%29")
        published = item["published_date"]
        local = datetime.fromisoformat(published).astimezone(
            ZoneInfo("Europe/Berlin")) if published else None
        time_label = f" · {local.strftime('%H:%M')} Uhr" if local else ""
        lines.append(f"- **[{_safe_md(item['title'])}]({url})** "
                     f"— {_safe_md(item['publisher'])}{time_label}  ")
        lines.append(f"  {_safe_md(item['summary'])}")
        lines.append("")
    lines.extend(("*Kurzüberblicke sind wörtliche, gekürzte Auszüge aus lesbaren "
                  "Artikeln – keine unabhängige Faktenprüfung. "
                  "Veröffentlichungszeiten stammen aus Publisher-Feeds oder Suchindex.*",))
    return {
        "status": "available", "answer": "\n".join(lines), "items": items,
        "requested_count": max_items, "report_date": day,
        "evidence_level": "article_text_loaded_with_grounded_summary",
    }
