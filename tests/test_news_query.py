from backend.news_query import normalized_news_query


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
        "Aktuelle Börsen News",
        "Nachrichten Göppingen heute",
        "Wetter heute in Göppingen",
        "NVIDIA Quartalszahlen",
    ):
        assert normalized_news_query(query) == query
