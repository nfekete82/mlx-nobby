from backend.news_query import normalized_news_query, filter_financial_news_results


def test_broad_news_prompts_become_retrievable_keywords():
    assert normalized_news_query("gib mir alle wichtigen news von heute") == (
        "aktuelle Nachrichten Deutschland Welt Politik Wirtschaft"
    )
    assert normalized_news_query("Nachrichten heute zusammengefasst") == (
        "aktuelle Nachrichten Deutschland Welt Politik Wirtschaft"
    )


def test_specific_news_topics_keep_their_original_search_scope():
    for query in (
        "News von heute über NVIDIA",
        "Nachrichten Göppingen heute",
        "Wetter heute in Göppingen",
        "NVIDIA Quartalszahlen",
    ):
        assert normalized_news_query(query) == query


def test_german_finance_news_search_removes_imperatives_and_keeps_topic():
    assert normalized_news_query("gib mir alle börsennews von heute") == "Börse Aktienmärkte"
    assert normalized_news_query("Aktuelle Börsen News") == "Börse Aktienmärkte"
    assert normalized_news_query("Alle Aktiennachrichten heute") == "Aktien Börse"
    assert normalized_news_query("Wichtigste Finanznews heute") == "Finanznachrichten Märkte"
    assert normalized_news_query("Wirtschaftsnews heute") == "Wirtschaft Unternehmen"
    assert normalized_news_query("NVIDIA Börsennews heute") == "NVIDIA Börsennews heute"


def test_borsennews_removes_unrelated_search_results_without_affecting_other_topics():
    rows = [
        {"title": "GIB Gibraltar Firmenregister", "url": "https://example.org/gib"},
        {"title": "DAX und Aktienmärkte legen zu", "url": "https://example.org/dax"},
        {"title": "Börse: Anleger warten auf Quartalszahlen", "url": "https://example.org/market"},
    ]
    assert [item["url"] for item in filter_financial_news_results(
        "gib mir alle börsennews von heute", rows
    )] == ["https://example.org/dax", "https://example.org/market"]
    assert filter_financial_news_results("Tesla News heute", rows) == rows
