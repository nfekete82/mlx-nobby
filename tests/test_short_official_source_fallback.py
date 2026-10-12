"""Regressions for short legal documents and focus fallback contracts."""
from agent.publisher_page_quality import short_official_document_usable


def test_short_official_law_provision_is_transport_usable():
    text = ("§ 3 Dauer des Urlaubs\n(1) Der Urlaub beträgt jährlich mindestens "
            "24 Werktage.\n(2) Als Werktage gelten alle Kalendertage, "
            "die nicht Sonn- oder gesetzliche Feiertage sind.")
    assert len(text) < 500
    assert short_official_document_usable(
        "https://www.gesetze-im-internet.de/burlg/__3.html", text)


def test_short_law_exception_does_not_accept_untrusted_or_navigation_pages():
    provision = ("§ 3 Dauer des Urlaubs\n(1) Der Urlaub beträgt jährlich "
                 "mindestens 24 Werktage und enthält eine Rechtsregel.")
    assert not short_official_document_usable(
        "https://gesetze-im-internet.de.evil.example/burlg/__3.html", provision)
    assert not short_official_document_usable(
        "http://www.gesetze-im-internet.de/burlg/__3.html", provision)
    assert not short_official_document_usable(
        "https://www.gesetze-im-internet.de/burlg/BJNR000020963.html", provision)
    assert not short_official_document_usable(
        "https://www.gesetze-im-internet.de/burlg/__3.html",
        "§ 3 Navigation: Impressum, Sitemap und Cookies.")
