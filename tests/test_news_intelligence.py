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
BODY = ("Bundestag diskutiert Vorschläge zur Energieversorgung in Berlin. "
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
    assert digest["status"] == "no_readable_articles"
    assert digest["items"] == []


def test_missing_old_future_or_naive_publication_date_are_rejected():
    old = article(published_date="Wed, 14 Oct 2026 15:00:00 GMT")
    future = article(published_date="Thu, 15 Oct 2026 12:00:00 GMT")
    undated = article(published_date=None)
    naive = article(published_date="2026-10-15T07:00:00")
    result = grounded_news_digest("News von heute", [old, future, undated, naive], now=NOW)
    assert result["status"] == "no_readable_articles"


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
         patch.object(app, "fetch_web_page", return_value=source["fetch"]) as fetch:
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
    assert result["news_digest"]["status"] == "no_readable_articles"
    assert result["news_digest"]["items"] == []
