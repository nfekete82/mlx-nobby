"""Regression cases based on cross-domain native failures, not fake live success."""
from agent.plan_fastpath import official_catalog_goal
from agent.catalog_evidence import catalog_source_windows, catalog_claim_is_lineup
from agent.semantic_evidence import SemanticClaim
from agent.research_followup import (
    support_policy_question, need_support_policy_source,
    choose_support_policy_followup,
)


PIXEL_GOAL = "Welche aktuellen Pixel-Smartphones bietet Google im deutschen Google Store offiziell an?"
POSTGRES_GOAL = "Welche PostgreSQL-Hauptversionen werden auf der offiziellen PostgreSQL-Website derzeit unterstützt?"


def fetch(url, *, text=""):
    return {
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": True, "url": url, "text": text},
    }


def search(*entries):
    return {
        "action": "search_web", "status": "completed",
        "result": {"provider": "SearXNG",
                   "results": [{"url": u, "title": title} for u, title in entries]},
    }


def test_google_pixel_and_android_are_catalog_questions_not_apple_only():
    assert official_catalog_goal(PIXEL_GOAL)
    assert official_catalog_goal("Welche Galaxy-Smartphones bietet Samsung offiziell an?")
    assert official_catalog_goal("Welche Surface-Tablets bietet Microsoft aktuell offiziell an?")
    assert not official_catalog_goal("Wie funktioniert die Pixel Kamera?")
    assert not official_catalog_goal("Ist PostgreSQL 17 schneller als 16?")


def test_exact_pixel_portfolio_cards_remain_anchored():
    source = (
        "Entdecke die Google Pixel 11 Serie\n"
        "Einleitung über Kameratechnologie und Design.\n"
        "Entdecke das gesamte Portfolio\n"
        "Alle Smartphones vergleichen\n"
        "Google Pixel 11 Pro\nGoogle Pixel 11 Pro Fold\n"
        "Google Pixel 11\nGoogle Pixel 10a\nGoogle Pixel 10\n"
        "Die Herstellerseite stellt diese Produktfamilie vor.\n"
        "Weitere Informationen und Datenschutz." + " Design" * 80
    )
    windows = catalog_source_windows(PIXEL_GOAL, source)
    assert windows
    assert any("Google Pixel 11 Pro Fold" in block for _, _, block in windows)
    assert all(source[start:end] == block for start, end, block in windows)


def test_pixel_catalog_listing_is_not_claim_of_shipping_today():
    positive = SemanticClaim(
        "c1", "Google Pixel 11 Pro", "catalog",
        "Google Pixel 11 Pro", (),
        "Das Google Pixel 11 Pro ist in der aktuellen Modellpalette gelistet.", ())
    assert catalog_claim_is_lineup(PIXEL_GOAL, positive)
    irrelevant = SemanticClaim(
        "c2", "Google Pixel 11 Pro", "camera",
        "Google Pixel 11 Pro", (),
        "Das Google Pixel 11 Pro bietet eine hochwertige Kamera.", ())
    assert not catalog_claim_is_lineup(PIXEL_GOAL, irrelevant)


def test_official_support_versions_are_distinct_from_download_pages():
    assert support_policy_question(POSTGRES_GOAL)
    initial = search(
        ("https://www.postgresql.org/", "PostgreSQL"),
        ("https://www.postgresql.org/download/", "PostgreSQL Downloads"),
    )
    download = fetch("https://www.postgresql.org/download/", text="Packages and Installers.")
    assert need_support_policy_source(POSTGRES_GOAL, [initial, download])
    decision = choose_support_policy_followup(POSTGRES_GOAL, [initial, download])
    assert decision["action"] == "search_web"
    assert "site:postgresql.org" in decision["query"]
    assert "versions" in decision["query"].lower()


def test_discovered_support_policy_link_beats_download_link():
    initial = search(("https://www.postgresql.org/download/", "Downloads"))
    download = fetch("https://www.postgresql.org/download/")
    refined = search(
        ("https://www.postgresql.org/download/windows/", "Downloads for Windows"),
        ("https://postgresql.org/support/versioning/", "PostgreSQL: Versioning Policy"),
        ("https://postgresql.org.evil.example/support/versioning/", "Policy spoof"),
    )
    decision = choose_support_policy_followup(
        POSTGRES_GOAL, [initial, download, refined])
    assert decision["action"] == "fetch_url"
    assert decision["query"] == "https://postgresql.org/support/versioning/"
    loaded = fetch(decision["query"])
    assert not need_support_policy_source(
        POSTGRES_GOAL, [initial, download, refined, loaded])
    assert choose_support_policy_followup(
        POSTGRES_GOAL, [initial, download, refined, loaded]) is None


def test_no_fabricated_policy_for_unnamed_or_mismatched_publisher():
    observation = fetch("https://unrelated.example/download/")
    assert not need_support_policy_source(POSTGRES_GOAL, [observation])
    assert choose_support_policy_followup(POSTGRES_GOAL, [observation]) is None
    assert choose_support_policy_followup(
        "Wie kann ich die Anwendung herunterladen?",
        [fetch("https://www.postgresql.org/download/")],
    ) is None
