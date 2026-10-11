"""Regression: source-relative support tables and actual HTML navigation links."""
import json

from agent.page_navigation import same_site_html_links, choose_catalog_page_link
from agent.support_table_evidence import support_matrix_candidates
from agent.structured_evidence import build_evidence
from agent.semantic_evidence import synthesize_verified_evidence

GOAL = "Welche PostgreSQL-Hauptversionen werden auf der offiziellen PostgreSQL-Website derzeit unterstützt?"
PIXEL = "Welche aktuellen Pixel-Smartphones bietet Google im deutschen Google Store offiziell an?"
POLICY = "https://www.postgresql.org/support/versioning/"


def fetched(url, text, *, links=None):
    return {"action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "text": text,
                       "page_links": links or []}}


def support_table():
    return (
        "Versioning Policy\nThe PostgreSQL Global Development Group supports each major version for five years.\n"
        "Version | Current minor | Supported | First Release | Final Release\n"
        "18 | 18.6 | Yes | September 25, 2025 | November 14, 2030\n"
        "17 | 17.11 | Yes | September 26, 2024 | November 8, 2029\n"
        "16 | 16.15 | Yes | September 14, 2023 | November 9, 2028\n"
        "15 | 15.19 | Yes | October 13, 2022 | November 11, 2027\n"
        "14 | 14.24 | Yes | September 30, 2021 | November 12, 2026\n"
        "13 | 13.23 | No | September 24, 2020 | November 13, 2025\n"
        "12 | 12.22 | No | October 3, 2019 | November 21, 2024\n"
        "No version is to be inferred by adding numbers to existing rows.\n"
    )


def test_real_html_links_are_normalized_and_same_host_only():
    html = (
        '<nav><a href="/de/category/phones?hl=de"><span>Smartphones entdecken</span></a>'
        '<a href="https://accounts.google.com/login">Google Konto</a>'
        '<a href="javascript:alert(1)">Bad</a>'
        '<a href="https://store.google.com.evil.example/de/category/phones">Spoof</a>'
        '<a href="/de/product/pixel_11">Pixel 11</a>'
        '<a href="/de/category/phones?hl=de#same">Smartphones</a></nav>'
    )
    links = same_site_html_links(html, "https://store.google.com/de/")
    assert [l["url"] for l in links] == [
        "https://store.google.com/de/category/phones?hl=de",
        "https://store.google.com/de/product/pixel_11",
    ]


def test_actual_fetched_store_link_selected_before_more_search_queries():
    html = (
        '<a href="/de/category/phones">Smartphones entdecken</a>'
        '<a href="/de/product/pixel_11">Google Pixel 11</a>'
        '<a href="/de/support">Help</a>'
    )
    links = same_site_html_links(html, "https://store.google.com/de/")
    obs = [fetched("https://store.google.com/de/", "Google Store intro " * 20, links=links)]
    decision = choose_catalog_page_link(PIXEL, obs)
    assert decision["action"] == "fetch_url"
    assert decision["query"] == "https://store.google.com/de/category/phones"
    assert choose_catalog_page_link(PIXEL, obs + [
        fetched(decision["query"], "Pixel Models " * 30),
    ]) is None


def test_untrusted_scraped_html_cannot_link_to_cross_host_or_internal_url():
    html = (
        '<a href="http://127.0.0.1/admin">internal</a>'
        '<a href="//store.google.com.evil.example/de/category/phones">spoof</a>'
        '<a href="https://example.org/de/category/phones">other publisher</a>'
    )
    assert same_site_html_links(html, "https://store.google.com/de/") == []
    assert same_site_html_links(html, "file:///private/home") == []


def test_support_matrix_parser_only_emits_yes_versions_from_exact_source():
    bundle = build_evidence([fetched(POLICY, support_table())], goal=GOAL)
    records = support_matrix_candidates(GOAL, bundle)
    assert [subject for subject, _, _ in records] == [
        "PostgreSQL 18", "PostgreSQL 17", "PostgreSQL 16",
        "PostgreSQL 15", "PostgreSQL 14",
    ]
    assert all("13" not in record[0] for record in records)
    ids = {fact.id for fact in bundle.facts}
    assert all(passage_id in ids for _, _, passage_id in records)


def test_structured_matrix_reduces_extractor_call_but_keeps_model_verification():
    obs = [fetched(POLICY, support_table())]
    purposes = []

    def llm(purpose, prompt, limit):
        purposes.append(purpose)
        assert purpose == "agent.verify"
        request = json.loads(prompt.split("\n")[-1])
        assert len(request["claims"]) == 5
        assert len(request["passages"]) >= 1
        ids = [c["passage_ids"][0] for c in request["claims"]]
        return json.dumps({"claims": [
            {"id": c["id"], "status": "supported",
             "reason": "Officially marked Yes in version matrix",
             "passage_ids": [ids[i]]}
            for i, c in enumerate(request["claims"])
        ]})

    answer = synthesize_verified_evidence(GOAL, obs, llm)
    assert purposes == ["agent.verify"]
    assert answer.audit["extraction_method"] == "source_exact_support_matrix"
    assert answer.audit["verified_supported_count"] == 5
    assert "PostgreSQL 18" in answer and "PostgreSQL 14" in answer
    assert "PostgreSQL 13" not in answer
    assert POLICY in answer


def test_support_matrix_requires_same_named_publisher_and_no_conflicting_rows():
    source = support_table().replace(
        "13 | 13.23 | No", "18 | 13.23 | No")
    expected = build_evidence([fetched(POLICY, source)], goal=GOAL)
    assert all(subject != "PostgreSQL 18"
               for subject, _, _ in support_matrix_candidates(GOAL, expected))
    fake = build_evidence([
        fetched("https://postgresql.org.evil.example/support/versioning/",
                support_table()),
    ], goal=GOAL)
    assert support_matrix_candidates(GOAL, fake) == []



def test_real_html_extractor_to_source_evidence_to_table_candidates():
    """Unlike hand-written pipe data, HTML extraction prefixes each <th>/<td>."""
    from agent.app import extract_web_text
    from agent.research_followup import support_policy_windows
    tr = lambda cells, tag: "<tr>" + "".join(
        "<" + tag + ">" + str(cell) + "</" + tag + ">" for cell in cells
    ) + "</tr>"
    markup = (
        "<html><body><h1>Versioning Policy</h1>"
        "<p>Each PostgreSQL major version receives five years of support.</p>"
        "<table>" + tr(
            ["Version", "Current minor", "Supported", "First Release", "Final Release"], "th"
        ) + tr(["18", "18.6", "Yes", "September 25, 2025", "November 14, 2030"], "td")
        + tr(["17", "17.11", "Yes", "September 26, 2024", "November 8, 2029"], "td")
        + tr(["13", "13.23", "No", "September 24, 2020", "November 13, 2025"], "td")
        + "</table><p>See also other projects.</p></body></html>"
    )
    extracted = extract_web_text(markup)
    assert " | Version" in extracted
    windows = support_policy_windows(GOAL, extracted)
    assert len(windows) == 1
    source = build_evidence([fetched(POLICY, extracted)], goal=GOAL)
    candidates = support_matrix_candidates(GOAL, source)
    assert [subject for subject, _, _ in candidates] == ["PostgreSQL 18", "PostgreSQL 17"]
    assert all("13" not in subject for subject, _, _ in candidates)
    assert all(source.facts for _ in candidates)
