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
    assert '"rki.de"' in decision["query"]
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
