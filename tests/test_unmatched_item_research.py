"""Fail-closed, bounded research guards for repeated off-topic searches."""
from agent.search_failure_fastpath import exhausted_unmatched_item_search


GOAL = (
    "Ist das Smartphone Asterium Cloudphone Q-98765 offiziell in "
    "Deutschland erhältlich?"
)


def search(query, *hits):
    return {
        "action": "search_web", "status": "completed", "query": query,
        "result": {"provider": "SearXNG", "provider_status": "available",
                   "results": [{"title": title, "url": url} for title, url in hits]},
    }


def test_two_distinct_offtopic_queries_stop_for_exact_model_id():
    found = [
        search("Asterium Cloudphone Q-98765",
               ("Copilot AI", "https://example.org/copilot")),
        search('"Asterium Cloudphone Q-98765"',
               ("teemer dental software", "https://example.org/dental")),
    ]
    assert exhausted_unmatched_item_search(GOAL, found)


def test_neither_one_query_nor_duplicate_query_exhausts_research():
    item = search("Asterium Cloudphone Q-98765",
                  ("Some unrelated article", "https://example.org/unrelated"))
    assert not exhausted_unmatched_item_search(GOAL, [item])
    assert not exhausted_unmatched_item_search(GOAL, [item, item])


def test_source_result_might_be_relevant_and_must_not_be_suppressed():
    first = search("Asterium Cloudphone Q-98765",
                   ("Q-98765 manufacturer page", "https://example.org/model"))
    second = search("Asterium Cloudphone Germany",
                    ("Another article", "https://example.org/other"))
    assert not exhausted_unmatched_item_search(GOAL, [first, second])


def test_no_inference_for_generic_models_or_actual_articles():
    unrelated = search("Pixel 11 official",
                       ("Old unrelated news", "https://example.org/news"))
    assert not exhausted_unmatched_item_search(
        "Welche Pixel-Smartphones sind offiziell erhältlich?", [unrelated, unrelated]
    )
    a = search("Asterium Cloudphone Q-98765",
               ("Offtopic", "https://example.org/offtopic"))
    b = search("Cloudphone Q-98765 official",
               ("Another offtopic", "https://example.org/another"))
    source = {
        "action": "fetch_url", "status": "completed",
        "query": "https://example.org/manufacturer",
        "result": {"ok": True, "url": "https://example.org/manufacturer",
                   "text": "Official manufacturer press statement. " * 6},
    }
    assert not exhausted_unmatched_item_search(GOAL, [a, b, source])


def test_empty_or_failed_searches_do_not_count_as_offtopic_results():
    first = search("Asterium Q-98765", ("Irrelevant", "https://example.org/a"))
    empty = search("Cloudphone Q-98765")
    assert not exhausted_unmatched_item_search(GOAL, [first, empty])
    failed = dict(first, status="failed")
    assert not exhausted_unmatched_item_search(GOAL, [first, failed])
