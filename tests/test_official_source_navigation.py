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
    choice = choose_official_publisher_step(goal, [first, indexed])
    assert choice["action"] == "search_web"
    assert "ipv6" in choice["query"].casefold()
    assert not any(
        "info/rfc1" in str(x)
        for x in [choice]
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



def test_saved_rki_capture_shape_is_not_mistaken_for_a_symptom_answer():
    """An Epid Bull literature title is no disease presentation evidence."""
    from agent.official_source_navigation import (
        missing_clinical_article, clinical_presentation_question,
    )
    overview = "https://www.rki.de/DE/Themen/Infektionskrankheiten/Infektionskrankheiten-A-Z/I/Influenza/Influenza.html"
    node = "https://www.rki.de/DE/Themen/Infektionskrankheiten/Infektionskrankheiten-A-Z/I/Influenza/influenza-node.html"
    vaccination = "https://www.rki.de/SharedDocs/FAQs/DE/Impfen/Influenza/FAQ-Liste_gesamt.html"
    article = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    title = (
        "Symptomprofile, Erkrankungsraten und Sequenzierung der häufigsten "
        "Atemwegserreger auf Bevölkerungsebene, Epid Bull 35/2025"
    )
    obs = [
        search((overview, "Influenza Themenübersicht"), (node, "Influenza Index")),
        fetched(overview, links=[{"url": vaccination, "title": "Influenza-Impfung FAQ"}]),
        fetched(node, links=[{"url": vaccination, "title": "Influenza-Impfung FAQ"}]),
    ]
    for item in obs[1:]:
        item["result"]["text"] = (
            "Informationen zu Influenza und Publikationen\n" + title
        )
    assert clinical_presentation_question(RKI_GOAL)
    assert missing_clinical_article(RKI_GOAL, obs)
    next_step = choose_official_publisher_step(RKI_GOAL, obs)
    assert next_step["action"] == "search_web"
    assert "krankheitsbild" in next_step["query"].casefold()
    assert "symptomatik" in next_step["query"].casefold()
    assert not any("Impfen" in str(item) for item in [next_step])
    # Already attempted a targeted fallback: no recurring search loop.
    followup = search(
        (vaccination, "Impfreaktionen nach Influenza-Impfung"),
        (article, "Wie ist das Krankheitsbild der Influenza? FAQ"),
    )
    picked = choose_official_publisher_step(RKI_GOAL, obs + [followup])
    assert picked == {
        "action": "fetch_url",
        "query": article,
        "reason": "Tatsächlich gefundene Primärquelle öffnen",
    }
    source = fetched(article)
    source["result"]["text"] = (
        "Die Influenza-typische Symptomatik ist oft durch einen plötzlichen "
        "Erkrankungsbeginn mit Fieber, Muskel- und Kopfschmerzen gekennzeichnet."
    )
    assert not missing_clinical_article(RKI_GOAL, obs + [followup, source])
    assert not missing_clinical_article("Wie viele Bit hat IPv4 laut IETF?", obs)


def test_rki_faq_about_vaccination_is_not_selected_for_disease_symptoms():
    vaccination = "https://www.rki.de/SharedDocs/FAQs/DE/Impfen/Influenza/FAQ-Liste_gesamt.html"
    disease = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    hits = search(
        (vaccination, "FAQ Influenza Impfung und Nebenwirkungen"),
        (disease, "FAQ Influenza Krankheitsbild und Symptome"),
    )
    decision = choose_official_publisher_step(RKI_GOAL, [hits])
    assert decision["query"] == disease


def test_named_clinical_research_keeps_primary_link_without_inventing_symptoms():
    from agent.official_source_navigation import clinical_presentation_question
    query = choose_official_publisher_step(RKI_GOAL, [])
    assert "Krankheitsbild" in query["query"]
    assert "FAQ" in query["query"]
    assert "fieber" not in query["query"].casefold()
    assert clinical_presentation_question("Welche Krankheitsbild-Symptome nennt das RKI?")
    assert not clinical_presentation_question(
        "Welche Nebenwirkungen der Influenza-Impfung nennt das RKI?"
    )



def test_vaccination_adverse_effect_text_never_counts_as_disease_presentation():
    from agent.official_source_navigation import missing_clinical_article
    url = "https://www.rki.de/SharedDocs/FAQs/DE/Impfen/Influenza/FAQ-Liste_gesamt.html"
    vaccine = fetched(url)
    vaccine["result"]["text"] = (
        "Bei der Influenza-Impfung können als Nebenwirkungen Symptome "
        "wie Fieber und Gliederschmerzen auftreten."
    )
    assert missing_clinical_article(RKI_GOAL, [vaccine])
    assert not missing_clinical_article(
        "Welche Nebenwirkungen der Influenza-Impfung nennt das RKI?",
        [vaccine],
    )



def test_named_official_publisher_home_after_two_irrelevant_searches():
    """Search pollution may justify a canonical root, never a guessed article."""
    irrelevant = search(
        ("https://www.vonjacob.de/", "Wedding rings"),
        ("https://www.linguee.de/", "Dictionary"),
    )
    irrelevant["query"] = "ecb.europa.eu deposit facility key interest rates"
    retry = search(("https://www.linguee.de/", "Dictionary"))
    retry["query"] = "deposit facility rate european central bank"
    # Repeated result objects are NOT independent searches.
    assert choose_official_publisher_step(ECB_GOAL, [irrelevant, irrelevant]) is None
    decision = choose_official_publisher_step(ECB_GOAL, [irrelevant, retry])
    assert decision == {
        "action": "fetch_url",
        "query": "https://www.ecb.europa.eu/",
        "reason": "Offiziellen HTTPS-Einstiegspunkt nach irrelevanten Suchtreffern prüfen",
    }
    # The root is navigation, not rate evidence. One focused discovery
    # query is allowed afterwards, but never another root attempt.
    follow = choose_official_publisher_step(
        ECB_GOAL, [irrelevant, retry,
                   fetched("https://www.ecb.europa.eu/")]
    )
    assert follow["action"] == "search_web"
    assert "deposit facility" in follow["query"]
    # Ambiguous third-party questions cannot seed official root URLs.
    assert choose_official_publisher_step(
        "Wie hoch sind die Einlagenzinsen?",
        [irrelevant, irrelevant],
    ) is None


def test_official_root_exception_rejects_unseen_rates_subpaths_in_research():
    from agent.runtime import RuntimePolicy
    from test_agent_runtime import AgentRuntimeTests
    from unittest.mock import patch

    root = "https://www.ecb.europa.eu/"
    guessed = "https://www.ecb.europa.eu/stats/unobserved/rates.html"
    unrelated = "https://www.ecb.europa.eu.evil.example/"
    observed = [
        search(("https://vonjacob.de/", "Rings")),
        search(("https://linguee.de/", "Dictionary")),
    ]
    observed[0]["query"] = "ecb.europa.eu deposit facility key interest rates"
    observed[1]["query"] = "deposit facility rate european central bank"
    for url, allowed in ((root, True), (guessed, False), (unrelated, False)):
        harness = AgentRuntimeTests()
        harness.setUp()
        opened = []

        def fetch(**kwargs):
            opened.append(kwargs["query"])
            return {"ok": True, "url": kwargs["query"],
                    "text": "Source content with enough context for validation. " * 3}

        harness.add_tool("fetch_url", fetch)
        with patch(
            "agent.official_source_navigation.choose_official_publisher_step",
            return_value=None,
        ):
            out = harness.runtime(
                [{"action": "fetch_url", "query": url}, "Finished"],
                policy=RuntimePolicy(research_steps=1),
            ).run(ECB_GOAL, mode="research", observations=observed)
        assert opened == ([url] if allowed else [])
        assert bool([
            s for s in out["steps"] if s.get("action") == "fetch_url_allowlist_guard"
        ]) is not allowed



def test_missing_rfc_version_outranks_known_version_category_page():
    """Never load a generic IPv4 category when explicitly still missing IPv6."""
    ipv4 = "https://www.rfc-editor.org/info/rfc791/"
    ipv6 = "https://www.rfc-editor.org/info/rfc8200/"
    index = "https://www.rfc-editor.org/subjects/ipv4/"
    loaded = fetched(ipv4, links=[
        {"url": index, "title": "IPv4 RFC subject index"},
    ])
    loaded["result"]["text"] = (
        "Internet Protocol version IPv4 addressing is the subject of this RFC. " * 4
    )
    initial = search((ipv4, "Internet Protocol Version 4"))
    targeted = search(
        (index, "IPv4 RFC documents"),
        (ipv6, "IPv6 Internet Protocol Specification, IETF"),
    )
    choice = choose_official_publisher_step(RFC_GOAL, [initial, loaded, targeted])
    assert choice["action"] == "fetch_url"
    assert choice["query"] == ipv6
    no_ipv6 = search((index, "IPv4 RFC documents"))
    recovery = choose_official_publisher_step(
        RFC_GOAL, [initial, loaded, no_ipv6]
    )
    assert recovery["action"] == "search_web"
    assert "ipv6" in recovery["query"].casefold()



def test_truncated_rfc_document_continues_on_same_verified_url_once():
    """A first 18k-character slice without address-width facts is not final."""
    page = "https://www.rfc-editor.org/info/rfc791/"
    first = fetched(page)
    first["result"].update({
        "text": "Internet Protocol version IPv4 is a standard specification. " * 100,
        "offset": 0, "next_offset": 18000,
        "total_characters": 48000, "truncated": True,
    })
    discovered = search((page, "RFC 791 IPv4"))
    missing_search = search((
        "https://de.wikipedia.org/wiki/IPv6", "IPv6 introduction",
    ))
    missing_search["query"] = "ipv6 RFC Internet Protocol Specification rfc-editor.org"
    next_step = choose_official_publisher_step(
        RFC_GOAL, [discovered, first, missing_search],
    )
    assert next_step == {
        "action": "fetch_url",
        "query": page,
        "instruction": "offset=18000",
        "reason": "Fortsetzung desselben verifizierten RFC-Dokuments laden",
    }
    continuation = fetched(page)
    continuation["result"].update({
        "text": "Addresses are fixed length of four octets (32 bits). " * 3,
        "offset": 18000, "next_offset": None,
        "total_characters": 48000, "truncated": False,
    })
    recovered = choose_official_publisher_step(
        RFC_GOAL, [discovered, first, missing_search, continuation],
    )
    assert recovered is None or recovered["action"] != "fetch_url"
    assert not any(
        "offset=" in str(step) for step in [
            choose_official_publisher_step(
                RFC_GOAL, [discovered, first, missing_search, continuation],
            ),
        ]
    )


def test_rfc_addresses_from_german_question_rank_source_exact_english_lines():
    from agent.structured_evidence import _quantitative_windows
    goal = "Wie viele Bit haben IPv4- und IPv6-Adressen laut den IETF-RFCs?"
    text = (
        "Header Flags: 3 bits.\n"
        "Addresses are fixed length of four octets (32 bits).\n"
        "Source Address: 32 bits\n"
    )
    windows = _quantitative_windows(goal, text)
    assert windows
    assert any("32 bits" in snippet and "Address" in snippet for _, _, snippet in windows)
    assert all(text[start:end] == snippet for start, end, snippet in windows)



def test_rate_topic_navigation_avoids_benchmarks_and_defers_homepage_extraction():
    """Policy deposit facility != euro short-term reference rate."""
    from agent.official_source_navigation import missing_official_answer_document
    home = "https://www.ecb.europa.eu/home/html/index.en.html"
    benchmark = ("https://www.ecb.europa.eu/stats/euro-short-term-rates/"
                 "interest_rate_benchmarks/WG_euro_risk-free_rates/html/index.en.html")
    policy = ("https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
              "key_ecb_interest_rates/html/index.en.html")
    found = search((home, "European Central Bank"))
    page = fetched(home, links=[
        {"url": benchmark, "title": "Euro short-term interest rate benchmarks"},
        {"url": policy, "title": "Key ECB interest rates"},
    ])
    assert missing_official_answer_document(ECB_GOAL, [found, page])
    decision = choose_official_publisher_step(ECB_GOAL, [found, page])
    assert decision["action"] == "fetch_url"
    assert decision["query"] == policy
    article = fetched(policy)
    article["result"]["text"] = (
        "Key ECB interest rates. Deposit facility rate is determined by monetary "
        "policy decisions. The effective date and rate are listed in this table. "
    )
    assert not missing_official_answer_document(
        ECB_GOAL, [found, page, article]
    )


def test_policy_question_researches_again_instead_of_using_estr_article():
    from agent.official_source_navigation import missing_official_answer_document
    home = "https://www.ecb.europa.eu/home/html/index.en.html"
    benchmark = ("https://www.ecb.europa.eu/stats/euro-short-term-rates/"
                 "interest_rate_benchmarks/WG_euro_risk-free_rates/html/index.en.html")
    found = search((home, "European Central Bank"))
    page = fetched(home, links=[
        {"url": benchmark, "title": "Interest rate benchmarks"},
    ])
    off_topic = fetched(benchmark)
    off_topic["result"]["text"] = "€STR is an overnight wholesale benchmark. " * 5
    observations = [found, page, off_topic]
    assert missing_official_answer_document(ECB_GOAL, observations)
    decision = choose_official_publisher_step(ECB_GOAL, observations)
    assert decision["action"] == "search_web"
    assert "deposit facility" in decision["query"]
    assert choose_official_publisher_step(
        ECB_GOAL, observations + [dict(search(), query=decision["query"])]
    ) is None


def test_two_protocol_question_continues_beyond_generic_rfc_editor_homepage():
    from agent.official_source_navigation import missing_official_answer_document
    home = "https://www.rfc-editor.org/"
    observations = [
        dict(search((home, "RFC Editor")), query="rfc-editor.org IPv4 IPv6"),
        fetched(home),
    ]
    assert missing_official_answer_document(RFC_GOAL, observations)
    choice = choose_official_publisher_step(RFC_GOAL, observations)
    assert choice["action"] == "search_web"
    assert "ipv6" in choice["query"].casefold()
    assert "ipv4" not in choice["query"].casefold()
    assert "rfc-editor.org" in choice["query"]
    second = dict(search(), query=choice["query"])
    assert choose_official_publisher_step(
        RFC_GOAL, observations + [second]
    ) is None
