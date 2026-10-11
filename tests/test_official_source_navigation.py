"""Named official-source search only chooses discovered HTTPS primary links."""
from dataclasses import replace
from agent.official_source_navigation import (
    choose_official_publisher_step, _publisher,
)

RKI_GOAL = "Welche typischen Symptome einer Influenza nennt das Robert Koch-Institut?"
ECB_GOAL = "Wie hoch ist aktuell der Einlagezins der Europäischen Zentralbank, und seit welchem Datum gilt dieser Zinssatz?"
RFC_GOAL = "Wie viele Bit haben IPv4- und IPv6-Adressen laut den entsprechenden IETF-RFCs?"


def search(*urls):
    return {"action": "search_web", "status": "completed",
            "result": {"provider": "SearXNG", "results": [
                {"url": url, "title": title} for url, title in urls]}}


def fetched(url, *, links=()):
    return {"action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "page_links": list(links),
                       "text": "Official source article with sufficient readable text. " * 4}}


def test_explicit_organizations_generate_search_hints_without_inventing_urls():
    cases = (
        (RKI_GOAL, "rki.de", "influenza"),
        (ECB_GOAL, "ecb.europa.eu", "deposit"),
        (RFC_GOAL, "rfc-editor.org", "ipv6"),
    )
    for goal, host, term in cases:
        decision = choose_official_publisher_step(goal, [])
        assert decision["action"] == "search_web"
        assert host in decision["query"]
        assert term in decision["query"].lower()
        assert "site:" not in decision["query"]
        assert "http" not in decision["query"]
    assert _publisher("Welche Symptome bei Grippe?") is None
    assert choose_official_publisher_step("Welche Symptome bei Grippe?", []) is None


def test_publisher_rejects_spoof_and_prefers_specific_rki_faq():
    faq = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    found = search(
        ("https://rki.de.evil.example/Influenza/symptome/", "Influenza Symptome"),
        ("https://restaurantrobert.de/", "Robert: menu"),
        ("http://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html", "HTTP"),
        ("https://www.rki.de/", "RKI"),
        (faq, "Influenza - häufige Fragen zu den Symptomen"),
    )
    choice = choose_official_publisher_step(RKI_GOAL, [found])
    assert choice["action"] == "fetch_url"
    assert choice["query"] == faq


def test_ecb_search_prefers_official_interest_rate_terms_without_asserting_values():
    decision = choose_official_publisher_step(ECB_GOAL, [])
    assert decision["action"] == "search_web"
    assert "ecb.europa.eu" in decision["query"]
    assert "deposit facility key interest rates" in decision["query"]
    assert "2.50" not in decision["query"]
    assert "2026-09-16" not in decision["query"]


def test_ecb_primary_home_beats_other_banks_and_about_us():
    home = "https://www.ecb.europa.eu/home/html/index.de.html"
    found = search(
        ("https://www.lbbw.de/maerkte/ezb-zins/", "Einlagezins EZB"),
        ("https://www.ecb.europa.eu/ecb/all-about-us/html/index.de.html",
         "Über uns - EZB"),
        (home, "European Central Bank"),
    )
    decision = choose_official_publisher_step(ECB_GOAL, [found])
    assert decision["query"] == home


def test_official_source_can_follow_exact_link_but_not_spoof():
    home = "https://www.ecb.europa.eu/home/html/index.de.html"
    rate = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.de.html"
    found = search((home, "European Central Bank"))
    homepage = fetched(home, links=[
        {"url": "https://ecb.europa.eu.evil.example/stats/policy", "title": "Deposit rate"},
        {"url": rate, "title": "Einlagezins / deposit facility rate"},
    ])
    decision = choose_official_publisher_step(ECB_GOAL, [found, homepage])
    assert decision["action"] == "fetch_url"
    assert decision["query"] == rate
    assert choose_official_publisher_step(
        ECB_GOAL, [found, homepage, fetched(rate)]
    ) is None


def test_publisher_mismatch_gets_only_one_bounded_retry():
    poor = search(("https://restaurantrobert.de/", "Robert"))
    decision = choose_official_publisher_step(RKI_GOAL, [poor])
    assert decision["action"] == "search_web"
    assert "rki.de" in decision["query"]
    assert "site:" not in decision["query"]
    assert choose_official_publisher_step(
        RKI_GOAL, [poor, poor]
    ) is None
    assert choose_official_publisher_step(
        RKI_GOAL, [poor, fetched("https://restaurantrobert.de/")]
    ) is None


def test_real_runtime_prioritizes_named_publisher_with_no_planner():
    from test_agent_runtime import AgentRuntimeTests
    harness = AgentRuntimeTests()
    harness.setUp()
    faq = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    calls = []

    def search_web(**kwargs):
        calls.append(("search", kwargs["query"]))
        return {"provider": "SearXNG", "results": [
            {"url": faq, "title": "Influenza Symptome FAQ - RKI"},
        ]}

    def fetch_url(**kwargs):
        calls.append(("fetch", kwargs["query"]))
        return {"ok": True, "url": faq, "text":
                "Die typische Influenza beginnt plötzlich mit Fieber, Muskel- oder Kopfschmerzen. "
                "Häufig kommt später trockener Reizhusten hinzu."}

    harness.add_tool("search_web", search_web)
    harness.add_tool("fetch_url", fetch_url)
    harness.hooks = replace(
        harness.hooks,
        agent_evidence_answer=lambda goal, obs: "Source loaded; truth must still be verified",
    )
    response = harness.runtime([]).run(RKI_GOAL, mode="diagnostic")
    assert response["status"] == "completed"
    assert [item["action"] for item in response["steps"]] == [
        "search_web", "fetch_url",
    ]
    assert [c[0] for c in calls] == ["search", "fetch"]
    assert not harness.planner_limits
    assert not harness.provider.calls



def test_paired_numbered_identifiers_require_both_in_loaded_corpus():
    from agent.official_source_navigation import missing_requested_identifiers

    goal = "Vergleiche die Bit-Längen von IPv4 und IPv6 laut IETF."
    first = fetched("https://www.rfc-editor.org/info/rfc791/")
    first["result"]["text"] = "RFC 791 describes the IPv4 header and addresses."
    assert missing_requested_identifiers(goal, [first])

    second = fetched("https://www.rfc-editor.org/info/rfc8200/")
    second["result"]["text"] = (
        "IPv6 increases the IP address size from 32 bits to 128 bits."
    )
    assert not missing_requested_identifiers(goal, [first, second])
    assert not missing_requested_identifiers("Wie funktioniert IPv4?", [first])
    assert not missing_requested_identifiers(goal, [])


def test_numeric_source_windows_prioritize_exact_unit_passages():
    from agent.structured_evidence import build_evidence, _quantitative_windows

    goal = "Wie viele Bit haben IPv4- und IPv6-Adressen laut IETF-RFCs?"
    preface = "\n".join(
        f"Document navigation page {i} with many unrelated explanatory notes."
        for i in range(130)
    )
    key = "IPv6 increases the IP address size from 32 bits to 128 bits."
    body = preface + "\n" + key + "\nAdditional technical specifications."
    windows = _quantitative_windows(goal, body)
    assert _quantitative_windows("Bitte fasse die Dokumentation zusammen.", body) == []
    assert windows
    assert any(key in excerpt for _, _, excerpt in windows)
    assert all(body[start:end] == excerpt for start, end, excerpt in windows)

    source = {
        "action": "fetch_url", "status": "completed",
        "query": "https://www.rfc-editor.org/info/rfc8200/",
        "result": {"ok": True,
                   "url": "https://www.rfc-editor.org/info/rfc8200/",
                   "text": body},
    }
    bundle = build_evidence([source], goal=goal)
    assert any("-quant-" in fact.id and key in fact.evidence_excerpt
               for fact in bundle.facts)
    assert all(
        source["result"]["text"][fact.source_location[0]:fact.source_location[1]]
        == fact.evidence_excerpt for fact in bundle.facts
    )



def test_rfc_index_is_not_a_document_answer_and_does_not_trigger_numeric_crawl():
    goal = RFC_GOAL
    index = "https://www.rfc-editor.org/rfc-index/"
    first = search(
        (index, "RFC Index"),
        ("https://www.rfc-editor.org/info/rfc1/", "RFC 1"),
        ("https://www.rfc-editor.org/info/rfc2/", "RFC 2"),
    )
    decision = choose_official_publisher_step(goal, [first])
    assert decision["action"] == "search_web", decision
    assert decision["query"] != choose_official_publisher_step(goal, [])["query"]
    assert "rfc-editor.org" in decision["query"]
    assert "site:" not in decision["query"]

    indexed = fetched(index, links=[
        {"url": "https://www.rfc-editor.org/info/rfc1/", "title": "RFC 1"},
        {"url": "https://www.rfc-editor.org/info/rfc2/", "title": "RFC 2"},
        {"url": "https://www.rfc-editor.org/info/rfc3/", "title": "RFC 3"},
    ])
    assert choose_official_publisher_step(goal, [first, indexed]) is None
    assert not any(
        "info/rfc1" in str(x)
        for x in [choose_official_publisher_step(goal, [first, indexed])]
    )


def test_rfc_specific_titled_document_outscores_rfc_index():
    index = "https://www.rfc-editor.org/rfc-index/"
    article = "https://www.rfc-editor.org/info/rfc8200/"
    first = search(
        (index, "RFC Index"),
        (article, "IPv6 Specification and IPv4 address size"),
    )
    choice = choose_official_publisher_step(RFC_GOAL, [first])
    assert choice["action"] == "fetch_url"
    assert choice["query"] == article



def test_research_reads_deeper_official_faq_before_source_synthesis():
    """An RKI influenza index is navigation, not yet clinical evidence."""
    from agent.official_source_navigation import has_discovered_deeper_primary_link
    from test_agent_runtime import AgentRuntimeTests

    index = "https://www.rki.de/DE/Themen/Influenza/Influenza.html"
    faq = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    homepage = fetched(index, links=[
        {"url": faq, "title": "Influenza Krankheitsbild häufige Fragen"},
        {"url": "https://www.rki.de/DE/Verwaltung/Kontakt.html",
         "title": "Kontakt"},
    ])
    assert has_discovered_deeper_primary_link(
        RKI_GOAL, [search((index, "Influenza Überblick")), homepage]
    )
    assert not has_discovered_deeper_primary_link(
        RKI_GOAL, [search((index, "Influenza Überblick")), fetched(faq)]
    )

    harness = AgentRuntimeTests()
    harness.setUp()
    calls = []
    def do_search(**kwargs):
        return {"provider": "SearXNG", "results": [
            {"url": index, "title": "Influenza Überblick"},
        ]}
    def do_fetch(**kwargs):
        url = kwargs["query"]
        calls.append(url)
        if url == index:
            return homepage["result"]
        assert url == faq
        return {"ok": True, "url": url, "text":
                "Die Influenza beginnt oft plötzlich mit Fieber und Muskelschmerzen. "
                "Später können Kopfschmerzen und trockener Reizhusten auftreten."}
    harness.add_tool("search_web", do_search)
    harness.add_tool("fetch_url", do_fetch)
    harness.hooks = replace(
        harness.hooks,
        agent_evidence_answer=lambda goal, obs: "Fetched primary-source article",
    )
    out = harness.runtime([]).run(RKI_GOAL, mode="diagnostic")
    assert out["status"] == "completed"
    assert calls == [index, faq]
    assert [s["action"] for s in out["steps"]] == [
        "search_web", "fetch_url", "fetch_url",
    ]
    assert not harness.provider.calls



def test_missing_protocol_identifier_triggers_one_focused_search_after_fetch():
    """A fetched IPv4 RFC must not cause repeated pagination instead of IPv6."""
    page = "https://www.rfc-editor.org/rfc/rfc791.txt"
    initial = search((page, "RFC 791 - IPv4"))
    loaded = fetched(page)
    loaded["result"]["text"] = (
        "Internet Protocol Version 4 (IPv4) describes a 32 bit address field. "
        "This document does not discuss later successor protocols."
    )
    obs = [initial, loaded]
    choice = choose_official_publisher_step(RFC_GOAL, obs)
    assert choice["action"] == "search_web"
    assert "ipv6" in choice["query"].lower()
    assert "rfc-editor.org" in choice["query"]
    followup = search((
        "https://www.rfc-editor.org/info/rfc8200/",
        "RFC 8200 IPv6 Address Size 128 bits",
    ))
    choice2 = choose_official_publisher_step(RFC_GOAL, obs + [followup])
    assert choice2["action"] == "fetch_url"
    assert choice2["query"] == "https://www.rfc-editor.org/info/rfc8200/"



def test_two_rki_navigation_pages_are_not_mistaken_for_clinical_article():
    """A real FAQ linked after two RKI index pages remains navigable."""
    from agent.official_source_navigation import has_discovered_deeper_primary_link
    index = "https://www.rki.de/DE/Infektionskrankheiten/Influenza.html"
    node = "https://www.rki.de/DE/Infektionskrankheiten/influenza-node.html"
    faq = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"

    initial = search((index, "Influenza Krankheit"), (node, "Influenza Übersicht"))
    landing = fetched(index, links=[
        {"url": node, "title": "Influenza Übersicht"},
        {"url": faq, "title": "Influenza: Antworten auf häufig gestellte Fragen"},
    ])
    second = fetched(node, links=[
        {"url": index, "title": "Influenza Übersicht"},
        {"url": faq, "title": "Krankheitsbild der Influenza FAQ"},
    ])
    choice = choose_official_publisher_step(
        RKI_GOAL, [initial, landing, second],
    )
    assert choice["action"] == "fetch_url"
    assert choice["query"] == faq
    assert has_discovered_deeper_primary_link(
        RKI_GOAL, [initial, landing, second],
    )
    assert not has_discovered_deeper_primary_link(
        RKI_GOAL, [initial, landing, second, fetched(faq)],
    )


def test_two_general_index_pages_without_topical_link_do_not_loop():
    """Avoid burning an extra inference step on undifferentiated navigation."""
    from agent.official_source_navigation import has_discovered_deeper_primary_link
    index = "https://www.rki.de/DE/Infektionen/Influenza.html"
    node = "https://www.rki.de/DE/Infektionen/influenza-node.html"
    observations = [
        search((index, "Influenza")),
        fetched(index, links=[{"url": node, "title": "Influenza Übersicht"}]),
        fetched(node),
    ]
    assert not has_discovered_deeper_primary_link(RKI_GOAL, observations)
