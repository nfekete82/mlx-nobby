"""Regression: finance RSS headlines remain useful without article bodies."""
from datetime import datetime, timezone

from agent.news_intelligence import grounded_news_digest

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _row(title, url="https://news.google.com/rss/articles/test"):
    return {"title": title, "url": url,
            "published_date": "Thu, 22 Oct 2026 10:00:00 GMT",
            "fetch": {"ok": False}}


def test_finance_headlines_fallback_is_labeled_not_fake_article_summary():
    rows = [
        _row("DAX und Aktienmärkte fallen"),
        _row("Börsenjahr 2021: Die wichtigsten Erkenntnisse",
             "https://news.google.com/rss/articles/old"),
        _row("DAX und Aktienmärkte fallen",
             "https://news.google.com/rss/articles/duplicate"),
        _row("Aktien Europa: Verluste belasten Handel",
             "https://news.google.com/rss/articles/europe"),
    ]
    digest = grounded_news_digest("gib mir alle börsennews von heute",
                                  rows, now=NOW)
    assert digest["status"] == "headlines_only"
    assert digest["evidence_level"] == "dated_headlines_only"
    assert len(digest["items"]) == 2
    assert all(item["article_loaded"] is False and not item["summary"]
               for item in digest["items"])
    assert "Originaltext ungeprüft" in digest["answer"]
    assert "2021" not in digest["answer"]


def test_nonfinance_does_not_get_headline_only_fallback():
    digest = grounded_news_digest("Nachrichten von heute",
                                  [_row("DAX und Aktienmärkte fallen")], now=NOW)
    assert digest["status"] == "no_summarizable_articles"


def test_finance_fallback_never_uses_undated_headlines():
    row = _row("DAX und Aktienmärkte fallen")
    row.pop("published_date")
    digest = grounded_news_digest("börsennews von heute", [row], now=NOW)
    assert digest["status"] == "no_summarizable_articles"
