"""SearXNG may return results from other domains for site-scoped queries."""
from agent.search_relevance import filter_site_results, required_site


def test_explicit_site_scope_accepts_only_real_subdomains():
    query = "site:rfc-editor.org RFC 791 IPv4 32-bit"
    results = [
        {"url": "https://support.google.com/chrome/answer/95464", "title": "Support"},
        {"url": "https://www.rfc-editor.org/rfc/rfc791.html", "title": "RFC 791"},
        {"url": "https://rfc-editor.org/rfc/rfc8200", "title": "RFC 8200"},
        {"url": "https://rfc-editor.org.evil.example/rfc/rfc791", "title": "Fake"},
        {"url": "http://www.rfc-editor.org/rfc/rfc791", "title": "HTTP"},
    ]
    filtered, removed = filter_site_results(query, results)
    assert required_site(query) == "rfc-editor.org"
    assert len(filtered) == 2
    assert removed == 3


def test_store_site_scope_handles_path_without_promoting_other_hosts():
    query = "site:store.google.com/DE Pixel Smartphones"
    results = [
        {"url": "https://store.google.com/de/category/phones", "title": "Store"},
        {"url": "https://www.pexels.com/", "title": "Photo"},
        {"url": "https://store.google.com/de/product/pixel_11", "title": "Phone"},
    ]
    filtered, rejected = filter_site_results(query, results)
    assert len(filtered) == 2 and rejected == 1
    assert all(x["url"].startswith("https://store.google.com/") for x in filtered)


def test_unscoped_search_retains_all_results_including_irrelevant_ones():
    results = [{"url": "https://example.org/"}, {"url": "https://google.com/"}]
    filtered, removed = filter_site_results("RFC 791", results)
    assert filtered is results and removed == 0
    assert required_site("site:example.org site:other.org test") is None


def test_site_query_does_not_promote_spoofed_evidence():
    results = [
        {"url": "https://site.example.org.evil.test/something"},
        {"url": "https://evil.test/?redirect=site.example.org"},
    ]
    assert filter_site_results("site:site.example.org", results) == ([], 2)
