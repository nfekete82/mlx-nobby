"""Publisher fetches prefer actual article HTML and reject non-publisher pages."""
from agent.app import extract_web_text
from agent.publisher_page_quality import (
    prefer_publisher_main, python_download_identity_missing,
)


def test_official_bmas_main_is_preferred_over_global_site_menu():
    html = (
        "<html><body><div class='global-navigation'>"
        + "<a href='/DE/Arbeit'>Arbeitsfoerderung und allgemeine Navigation</a>" * 200
        + "</div><main><article><h1>Fragen und Antworten zur Brückenteilzeit</h1>"
        + ("<p>Bei einer 5-Tage-Woche beträgt der gesetzliche Mindesturlaub "
           "20 Arbeitstage.</p>" * 18)
        + "</article></main></body></html>"
    )
    full = extract_web_text(html)
    article = prefer_publisher_main(
        "https://www.bmas.de/DE/Arbeit/Arbeitsrecht/Teilzeit/faq.html",
        html, full, extract_web_text,
    )
    assert "20 Arbeitstage" in article
    assert "Fragen und Antworten zur Brückenteilzeit" in article
    assert "Arbeitsfoerderung und allgemeine Navigation" not in article
    assert len(article) < len(full)


def test_bmas_short_or_missing_main_does_not_erase_source_text():
    html = "<html><div>Official main overview context. " + "More context. " * 80 + "</div><main>Intro.</main></html>"
    full = extract_web_text(html)
    assert prefer_publisher_main(
        "https://www.bmas.de/DE/index.html", html, full, extract_web_text,
    ) == full
    assert prefer_publisher_main(
        "https://www.bmas.de.evil.example/DE/index.html", html, full,
        extract_web_text,
    ) == full


def test_publisher_identity_mismatch_requires_exact_python_download_host():
    url = "https://www.python.org/downloads/"
    assert python_download_identity_missing(
        url, "Generic consent gateway without software release information",
    )
    assert not python_download_identity_missing(
        url, "Active Python releases; Python 3.15.0 bugfix",
    )
    assert not python_download_identity_missing(
        "https://www.python.org.evil.example/downloads/",
        "Generic consent gateway without software release information",
    )
    assert not python_download_identity_missing(
        "https://www.python.org/downloads/release/python-3150/",
        "text without publisher name",
    )
