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



def test_pixel_refinement_searches_storefront_not_general_google_search():
    from agent.plan_fastpath import choose_official_catalog_refinement
    goal = PIXEL_GOAL
    initial = search(
        ("https://www.google.com/", "Google"),
        ("https://www.google.de/", "Google Deutschland"),
    )
    decision = choose_official_catalog_refinement(goal, [initial])
    assert decision is not None
    assert decision["action"] == "search_web"
    assert decision["query"].startswith("site:store.google.com/DE ")
    assert "pixel" in decision["query"].lower()
    # One search refinement only; avoid identical back-to-back discovery.
    assert choose_official_catalog_refinement(goal, [initial, initial]) is None


def test_pixel_discovered_category_page_is_preferred_to_account_pages():
    from agent.plan_fastpath import choose_official_followup
    goal = PIXEL_GOAL
    results = search(
        ("https://www.google.com/", "Google"),
        ("https://accounts.google.com/", "Google Konto"),
        ("https://store.google.com/de/category/phones",
         "Entdecke die Google Pixel 11 Serie"),
    )
    decision = choose_official_followup(goal, [results])
    assert decision is not None
    assert decision["query"] == "https://store.google.com/de/category/phones"


def test_support_version_table_header_and_rows_remain_contiguous():
    from agent.research_followup import support_policy_windows
    from agent.structured_evidence import build_evidence
    article = (
        "Versioning Policy\n"
        "Each major version is supported for five years.\n"
        "Version | Current minor | Supported | First Release | Final Release\n"
        "18 | 18.6 | Yes | September 25, 2025 | November 14, 2030\n"
        "17 | 17.11 | Yes | September 26, 2024 | November 8, 2029\n"
        "16 | 16.15 | Yes | September 14, 2023 | November 9, 2028\n"
        "15 | 15.19 | Yes | October 13, 2022 | November 11, 2027\n"
        "14 | 14.24 | Yes | September 30, 2021 | November 12, 2026\n"
        "13 | 13.23 | No | September 24, 2020 | November 13, 2025\n"
        "Do not confuse old versions with currently supported releases.\n"
    )
    windows = support_policy_windows(POSTGRES_GOAL, article)
    assert windows
    block = windows[0][2]
    assert "Version | Current minor | Supported" in block
    assert "18 | 18.6 | Yes" in block
    assert "13 | 13.23 | No" in block
    assert all(article[start:end] == content
               for start, end, content in windows)
    b = build_evidence([fetch("https://www.postgresql.org/support/versioning/",
                              text=article)], goal=POSTGRES_GOAL)
    assert any("-support-" in f.id for f in b.facts)
    assert any("18 | 18.6 | Yes" in f.evidence_excerpt
               for f in b.facts if "-support-" in f.id)
    assert not need_support_policy_source(
        POSTGRES_GOAL, [fetch("https://www.postgresql.org/support/versioning/")])


def test_html_table_extraction_retains_complete_version_status_rows():
    from agent.app import extract_web_text
    html = (
        "<html><body><h1>Versioning Policy</h1>"
        "<table><thead><tr>"
        "<th>Version</th><th>Current minor</th><th>Supported</th>"
        "<th>First Release</th><th>Final Release</th>"
        "</tr></thead><tbody>"
        "<tr><td>18</td><td>18.6</td><td>Yes</td>"
        "<td>September 25, 2025</td><td>November 14, 2030</td></tr>"
        "<tr><td>17</td><td>17.11</td><td>Yes</td>"
        "<td>September 26, 2024</td><td>November 8, 2029</td></tr>"
        "<tr><td>13</td><td>13.23</td><td>No</td>"
        "<td>September 24, 2020</td><td>November 13, 2025</td></tr>"
        "</tbody></table></body></html>"
    )
    text = extract_web_text(html)
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    assert any("Version" in row and "Supported" in row for row in rows)
    assert any("18" in row and "18.6" in row and "Yes" in row for row in rows)
    assert any("13" in row and "13.23" in row and "No" in row for row in rows)
    assert any("17.11" in row for row in rows)
    assert not any("18.6" in row and "13.23" in row for row in rows)
