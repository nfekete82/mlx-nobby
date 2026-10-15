"""Offline safety and actual tool-route checks for article-grounded daily news."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from agent.news_intelligence import (
    grounded_news_digest, publisher_link, publisher_news_candidates,
    readable_article,
)

NOW = datetime(2026, 10, 15, 8, 10, tzinfo=timezone.utc)
TITLE = "Bundestag diskutiert Vorschläge zur Energieversorgung"
BODY = ("Der Bundestag diskutiert Vorschläge zur Energieversorgung und prüft "
        "gemeinsam mit verschiedenen Abgeordneten Änderungen an bisherigen "
        "Regelungen für betroffene Kommunen. "
        "Die Diskussion wird von verschiedenen Abgeordneten geführt. " * 14)


class FakeResponse:
    def __init__(self, content):
        self.content = content.encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, limit):
        return self.content[:limit]


def article(url="https://www.tagesschau.de/inland/energie-100.html", **changes):
    result = {
        "title": TITLE, "url": url, "published_date": "Thu, 15 Oct 2026 07:00:00 GMT",
        "engine": "tagesschau",
        "fetch": {"ok": True, "url": url, "text": BODY},
    }
    result.update(changes)
    return result


def test_loaded_publisher_articles_have_dated_direct_urls():
    value = grounded_news_digest("News von heute", [article()], now=NOW)
    assert value["status"] == "available"
    assert len(value["items"]) == 1
    assert "15.10.2026" in value["answer"]
    assert TITLE in value["answer"]
    assert "https://www.tagesschau.de/inland/energie-100.html" in value["answer"]
    assert value["items"][0]["article_loaded"] is True
    assert "keine unabhängige Faktenprüfung" in value["answer"]


def test_google_news_wrapper_and_unfetched_snippets_are_never_cited():
    wrappers = [
        article("https://news.google.com/rss/articles/CBAQ...."),
        article(fetch={"ok": False, "error": "not loaded"}),
        article(fetch={"ok": True, "text": BODY,
                       "url": "https://www.tagesschau.de/"}),
        article(fetch={"ok": True, "text": "Cookies" * 100,
                       "url": "https://www.tagesschau.de/inland/energie-100.html"}),
    ]
    assert not publisher_link("https://news.google.com/rss/articles/CBAQ")
    assert all(not readable_article(x) for x in wrappers)
    digest = grounded_news_digest("Wichtige Nachrichten von heute", wrappers, now=NOW)
    assert digest["status"] == "no_summarizable_articles"
    assert digest["items"] == []


def test_missing_old_future_or_naive_publication_date_are_rejected():
    old = article(published_date="Wed, 14 Oct 2026 15:00:00 GMT")
    future = article(published_date="Thu, 15 Oct 2026 12:00:00 GMT")
    undated = article(published_date=None)
    naive = article(published_date="2026-10-15T07:00:00")
    result = grounded_news_digest("News von heute", [old, future, undated, naive], now=NOW)
    assert result["status"] == "no_summarizable_articles"


def test_identical_urls_and_similar_headlines_are_deduplicated():
    a = article()
    b = article()
    c = article("https://www.deutschlandfunk.de/energie-100.html", engine="Deutschlandfunk")
    value = grounded_news_digest("News heute", [a, b, c], now=NOW)
    assert len(value["items"]) == 1


def test_official_rss_atom_feed_discovery_is_bounded_and_diverse():
    rss = ('<rss><channel><item><title>' + TITLE + '</title>'
           '<link>https://www.tagesschau.de/inland/energie-100.html</link>'
           '<pubDate>Thu, 15 Oct 2026 07:00:00 GMT</pubDate></item>'
           '<item><title>Stale</title>'
           '<link>https://www.tagesschau.de/inland/alt-100.html</link>'
           '<pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>')
    dlf = ('<rss><channel><item><title>Politische Debatte geht weiter</title>'
           '<link>https://www.deutschlandfunk.de/politik-100.html</link>'
           '<pubDate>Thu, 15 Oct 2026 07:20:00 GMT</pubDate></item></channel></rss>')
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            '<title>Software-Update vorgestellt</title>'
            '<link rel="alternate" href="https://www.heise.de/news/software-1234.html"/>'
            '<published>2026-10-15T08:00:00Z</published></entry></feed>')
    urls = []
    def opener(request, timeout):
        assert timeout <= 4
        urls.append(request.full_url)
        if "tagesschau.de" in request.full_url:
            return FakeResponse(rss)
        if "deutschlandfunk.de" in request.full_url:
            return FakeResponse(dlf)
        return FakeResponse(atom)
    items = publisher_news_candidates(
        "Alle wichtigen Nachrichten von heute", opener=opener, now=NOW
    )
    assert len(urls) == 3
    assert [x["engine"] for x in items] == [
        "tagesschau", "Deutschlandfunk", "heise online"
    ]
    assert all(x["source_type"] == "publisher_feed" for x in items)
    assert all(not x["article_loaded"] for x in items)


def test_only_broad_news_requests_use_curated_feeds():
    def no_request(*_args, **_kwargs):
        raise AssertionError("should not request fixed feeds")
    assert publisher_news_candidates("NVIDIA News von heute", opener=no_request, now=NOW) == []
    assert publisher_news_candidates("News von gestern", opener=no_request, now=NOW) == []


def test_real_chat_web_tool_uses_verified_digest_not_google_news_snippets():
    from agent import app
    source = article()
    result = {
        "query": "Alle wichtigen News von heute",
        "provider": "SearXNG",
        "provider_status": "available",
        "results": [
            {k: v for k, v in source.items() if k != "fetch"},
            {"title": "Unknown", "url": "https://news.google.com/rss/articles/1234",
             "published_date": "Thu, 15 Oct 2026 07:00:00 GMT"},
        ],
    }
    with patch.object(app, "searxng_search_results", return_value=result), \
         patch("agent.news_intelligence.publisher_news_candidates", return_value=[]), \
         patch.object(app, "fetch_web_page", return_value=source["fetch"]) as fetch, \
         patch.object(app, "observed_agent_llm", return_value='{"summaries": []}'):
        value = app.tool_web_search(SimpleNamespace(prompt="Alle wichtigen News von heute"))
    assert value["news_search"] is True
    assert value["news_digest"]["status"] == "available"
    assert value["count"] == 1
    assert value["results"][0]["url"].startswith("https://www.tagesschau.de/")
    fetch.assert_called_once_with(source["url"])


def test_real_chat_web_tool_fails_closed_when_only_google_wrapper_exists():
    from agent import app
    with patch.object(app, "searxng_search_results", return_value={
        "query": "News von heute", "provider": "Google News RSS (fallback)",
        "results": [{"title": "Unverified", "url": "https://news.google.com/rss/articles/123",
                     "published_date": "Thu, 15 Oct 2026 07:00:00 GMT"}],
    }), patch("agent.news_intelligence.publisher_news_candidates", return_value=[]), \
         patch.object(app, "fetch_web_page", side_effect=AssertionError("do not fetch wrappers")):
        result = app.tool_web_search(SimpleNamespace(prompt="News von heute"))
    assert result["count"] == 0
    assert result["news_digest"]["status"] == "no_summarizable_articles"
    assert result["news_digest"]["items"] == []


def test_atom_updated_without_published_is_not_today_news():
    from agent.news_intelligence import _entries
    import xml.etree.ElementTree as ET
    feed = ET.fromstring(
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        '<title>Alter Beitrag heute überarbeitet</title>'
        '<link rel="alternate" href="https://www.heise.de/news/alter-1234.html"/>'
        '<updated>2026-10-15T08:00:00Z</updated>'
        '</entry></feed>'
    )
    assert list(_entries(feed))[0][2] == ""



def test_every_readable_article_gets_a_source_based_preview_under_heading():
    from agent.news_intelligence import article_short_summary
    title = "Slowakei erneuert Militärkontakte mit Russland"
    first = (
        "Die Slowakei hat neue Militärkontakte mit Russland angekündigt, "
        "nachdem beide Seiten mehrere Monate lang Gespräche vorbereitet hatten."
    )
    second = (
        "Die zuständigen Ministerien sollen nun prüfen, wann die nächsten "
        "Gespräche stattfinden und welche Delegationen teilnehmen."
    )
    body = (
        "Startseite Nachrichten Aktuelle Meldungen.\n"
        + first + " " + second + "\n"
        + "Hintergrund: " + ("Zahlreiche weitere Hintergrundinformationen " * 22)
    )
    candidate = article(
        title=title,
        fetch={"ok": True,
               "url": "https://www.tagesschau.de/inland/energie-100.html",
               "text": body},
    )
    summary = article_short_summary(candidate)
    assert first in summary
    assert second in summary
    assert len(summary) <= 330
    digest = grounded_news_digest("News von heute", [candidate], now=NOW)
    assert digest["items"][0]["summary"] == summary
    assert "  \n  " in digest["answer"]
    assert digest["answer"].index(first) > digest["answer"].index(title)
    assert "Kurzüberblicke sind wörtliche" in digest["answer"]


def test_short_preview_excludes_cookie_notices_and_source_unrelated_text():
    from agent.news_intelligence import article_short_summary
    body = (
        "Cookie-Einstellungen: Klicken Sie auf Zustimmen, um weitere "
        "Nachrichten zu sehen. "
        "Bundestag diskutiert Vorschläge zur Energieversorgung in Berlin, "
        "während die beteiligten Fraktionen ihre jeweiligen Positionen erläutern. "
        + ("Diese Seite bietet zahlreiche zusätzliche Hintergrundinformationen. " * 15)
    )
    candidate = article(fetch={
        "ok": True, "url": "https://www.tagesschau.de/inland/energie-100.html",
        "text": body,
    })
    summary = article_short_summary(candidate)
    assert "Cookie" not in summary
    assert "Bundestag diskutiert" in summary
    assert summary in body


def test_missing_relevant_summary_never_fabricates_news_facts():
    from agent.news_intelligence import article_short_summary
    # The page mentions title tokens but contains no usable factual sentence.
    candidate = article(fetch={
        "ok": True,
        "url": "https://www.tagesschau.de/inland/energie-100.html",
        "text": "Bundestag Vorschläge Energieversorgung. " * 20,
    })
    assert readable_article(candidate)
    assert article_short_summary(candidate) == ""
    digest = grounded_news_digest("News von heute", [candidate], now=NOW)
    assert digest["items"] == []
    assert digest["status"] == "no_summarizable_articles"
    assert "keine ausreichend belegten Kurzmeldungen" in digest["answer"]



def test_untrusted_article_markup_is_escaped_in_overview():
    malicious = (
        "Bundestag diskutiert neue Vorschläge zur Energieversorgung in Berlin "
        "und erläutert dabei <script>alert('unsafe')</script> die aktuellen Planungen "
        "mit Vertretern verschiedener Fraktionen. "
        + "Unabhängige Angaben und weitere öffentliche Diskussionen. " * 14
    )
    candidate = article(fetch={
        "ok": True,
        "url": "https://www.tagesschau.de/inland/energie-100.html",
        "text": malicious,
    })
    value = grounded_news_digest("News von heute", [candidate], now=NOW)
    assert value["items"][0]["summary"]
    assert "<script>" not in value["answer"]
    assert "&lt;script&gt;" in value["answer"]



def test_non_summarizable_headline_is_replaced_by_next_grounded_article():
    from agent.news_intelligence import article_short_summary
    shallow = article(fetch={
        "ok": True,
        "url": "https://www.tagesschau.de/inland/energie-100.html",
        "text": "Bundestag Vorschläge Energieversorgung. " * 20,
    })
    replacement = article(
        url="https://www.tagesschau.de/inland/energie-200.html",
        title="Ministerium erläutert Vorschläge zur Energieversorgung",
        fetch={
            "ok": True,
            "url": "https://www.tagesschau.de/inland/energie-200.html",
            "text": (
                "Das Ministerium erläutert neue Vorschläge zur Energieversorgung "
                "und kündigt für die kommenden Tage weitere Gespräche an. "
                + ("Hintergründe und zusätzliche öffentliche Informationen. " * 14)
            ),
        },
    )
    assert article_short_summary(shallow) == ""
    assert article_short_summary(replacement)
    digest = grounded_news_digest("News von heute", [shallow, replacement],
                                  now=NOW, max_items=2)
    assert len(digest["items"]) == 1
    assert digest["items"][0]["url"].endswith("energie-200.html")
    assert digest["items"][0]["summary"]
    assert "1 von 2 angefragten" in digest["answer"]
    assert "Kein verlässlicher Kurztext" not in digest["answer"]


def test_actual_news_web_tool_fetches_additional_articles_until_five_summaries():
    from agent import app
    from datetime import datetime, timezone
    from email.utils import format_datetime
    now = format_datetime(datetime.now(timezone.utc))
    url_root = "https://www.tagesschau.de/inland/topic-"
    titles = [
        "Bundestag bespricht Gesetzesänderung für Energieversorgung",
        "Ministerium informiert über Pläne zur Steuerreform",
        "Bundesregierung kündigt weitere Gespräche zur Gesundheitsreform an",
        "Parteien einigen sich auf Änderungen beim Nahverkehr",
        "Forschungsteam berichtet über neue Ergebnisse der Klimastudie",
        "Parlament diskutiert die geplanten Änderungen der Bildungspolitik",
        "EU-Kommission verhandelt über neue europäische Regeln",
    ]
    search_results = [
        {"title": title, "url": f"{url_root}{i}.html",
         "published_date": now, "engine": "SearXNG"}
        for i, title in enumerate(titles)
    ]
    urls = []
    def fake_fetch(url):
        urls.append(url)
        i = int(url.rsplit("-", 1)[-1].split(".")[0])
        if i < 2:
            text = " ".join(titles[i].split()[:3]) + ". "
            text = text * 30
        else:
            text = (
                titles[i] + ": Die zuständige Behörde hat sich "
                "zu dem Vorhaben geäußert und weitere Schritte erläutert. "
                + ("Mehr unabhängige Hintergrundinformationen aus dem Bericht. " * 13)
            )
        return {"ok": True, "url": url, "text": text}
    with patch.object(app, "searxng_search_results", return_value={
        "query": "Die fünf wichtigsten Nachrichten von heute",
        "provider": "SearXNG", "results": search_results,
    }), patch("agent.news_intelligence.publisher_news_candidates", return_value=[]), \
         patch.object(app, "fetch_web_page", side_effect=fake_fetch), \
         patch.object(app, "observed_agent_llm", return_value='{"summaries": []}'):
        data = app.tool_web_search(SimpleNamespace(
            prompt="Die fünf wichtigsten Nachrichten von heute"
        ))
    assert data["count"] == 5
    assert len(urls) == 7
    assert data["fetch_attempts"] == 7
    assert all(item["summary"] for item in data["news_digest"]["items"])
    assert data["news_digest"]["requested_count"] == 5
