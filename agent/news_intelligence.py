"""Verified-source news discovery: fixed publisher feeds and fetched article evidence.

A headline is never treated as a loaded article merely because it appears in
RSS, SearXNG or Google News. No arbitrary user-controlled feed URLs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from backend.news_query import normalized_news_query
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
    if not requires_today_news(query) or normalized_news_query(query) == query:
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
    for char in ("\\", "[", "]", "(", ")", "*", "_"):
        value = value.replace(char, "\\" + char)
    return value


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
        seen_urls.add(key)
        seen_titles.append(title_key)
        items.append({
            "title": str(candidate["title"])[:220], "url": url,
            "publisher": str(candidate.get("engine") or host(url))[:100],
            "published_date": published.isoformat() if published else None,
            "article_loaded": True,
        })
        if len(items) >= max_items:
            break
    day = now.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y")
    if not items:
        return {
            "status": "no_readable_articles",
            "answer": ("Für heute konnte ich keine ausreichend belegte Nachrichtenübersicht "
                       "erstellen. Die Suchtreffer hatten keinen lesbaren Artikeltext oder "
                       "kein eindeutiges Veröffentlichungsdatum. Ungeprüfte Meldungen "
                       "stelle ich nicht als aktuelle Nachrichten dar."),
            "items": [], "evidence_level": "no_loaded_articles",
        }
    lines = [f"**Nachrichtenüberblick vom {day}**", ""]
    for item in items:
        url = item["url"].replace("(", "%28").replace(")", "%29")
        published = item["published_date"]
        local = datetime.fromisoformat(published).astimezone(
            ZoneInfo("Europe/Berlin")) if published else None
        time_label = f" · {local.strftime('%H:%M')} Uhr" if local else ""
        lines.append(f"- [{_safe_md(item['title'])}]({url}) "
                     f"— {_safe_md(item['publisher'])}{time_label}")
    lines.extend(("", "*Nur Überschriften aus tatsächlich lesbaren Artikelseiten. "
                  "Zeitangaben stammen aus Publisher-Feeds bzw. dem Suchindex; "
                  "keine unabhängige Faktenprüfung.*"))
    return {
        "status": "available", "answer": "\n".join(lines), "items": items,
        "evidence_level": "article_text_loaded_headline_matched",
    }
