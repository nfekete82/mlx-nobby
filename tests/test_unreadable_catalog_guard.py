"""Only multiple distinct unreadable primary catalogs cause early abstention."""
from agent.search_failure_fastpath import exhausted_unreadable_catalog

GOAL = (
    "Welche aktuellen Pixel-Smartphones bietet Google im "
    "deutschen Google Store offiziell an?"
)


def failed(url, error="Zu wenig verwertbarer Seiteninhalt"):
    return {
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": False, "url": url, "error": error},
    }


def test_two_distinct_official_store_pages_cannot_establish_current_lineup():
    urls = [
        "https://store.google.com/de/category/phones",
        "https://store.google.com/de/product/pixel_11",
    ]
    assert exhausted_unreadable_catalog(GOAL, [failed(url) for url in urls])


def test_single_failed_official_page_and_duplicate_page_are_not_exhausted():
    url = "https://store.google.com/de/category/phones"
    assert not exhausted_unreadable_catalog(GOAL, [failed(url)])
    assert not exhausted_unreadable_catalog(GOAL, [failed(url), failed(url)])


def test_nonofficial_or_spoofed_site_is_not_a_primary_failure():
    steps = [
        failed("https://store.google.com.evil.test/de/category/phones"),
        failed("https://www.example.org/de/product/pixel_11"),
    ]
    assert not exhausted_unreadable_catalog(GOAL, steps)


def test_http_error_or_successful_article_prevents_early_stop():
    urls = [
        "https://store.google.com/de/category/phones",
        "https://store.google.com/de/product/pixel_11",
    ]
    assert not exhausted_unreadable_catalog(GOAL, [failed(urls[0], "HTTP 500"), failed(urls[1])])
    good = {
        "action": "fetch_url", "status": "completed",
        "query": "https://store.google.com/de/category/phones",
        "result": {"ok": True, "url": "https://store.google.com/de/category/phones",
                   "text": "Official Google Store current phone portfolio. " * 12},
    }
    assert not exhausted_unreadable_catalog(GOAL, [failed(url) for url in urls] + [good])


def test_requires_actual_official_catalog_question():
    urls = [
        "https://store.google.com/de/category/phones",
        "https://store.google.com/de/product/pixel_11",
    ]
    assert not exhausted_unreadable_catalog(
        "Was ist Google?", [failed(url) for url in urls]
    )
