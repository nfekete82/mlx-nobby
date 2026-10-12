"""Regression: real NASA navigation survives large pages and avoids guessed URLs."""
from agent.page_navigation import same_site_html_links, _MAX_LINKS
from agent.official_source_navigation import (
    choose_official_publisher_step,
    has_discovered_deeper_primary_link,
    missing_official_answer_document,
)

GOAL = (
    "Wann landete Apollo 11 nach Angaben der NASA auf dem Mond, "
    "und wer betrat die Oberfläche zuerst?"
)
ROOT = "https://www.nasa.gov/"
INDEX = "https://www.nasa.gov/a-to-z-of-nasa-missions/"
ARTICLE = "https://www.nasa.gov/mission/apollo-11/"


def fetched(url, links=(), text="Official page navigation."):
    return {
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": True, "url": url, "text": text,
                   "page_links": list(links)},
    }


def searched(query, *hits):
    return {
        "action": "search_web", "status": "completed", "query": query,
        "result": {"provider": "SearXNG", "results": list(hits)},
    }


def test_nasa_navigation_keeps_directory_and_requested_mission_in_bounded_links():
    # Real site structure: general NASA homepage -> A-to-Z mission directory
    # -> individual mission article. Unrelated deep news links are plentiful.
    homepage_html = (
        "<nav>" + "".join(
            f'<a href="/news-release/unrelated/{i}/story/">News {i}</a>'
            for i in range(180)
        ) +
        '<a href="/a-to-z-of-nasa-missions/">A to Z List of Missions</a>'
        '<a href="https://www.nasa.gov.evil.test/mission/apollo-11/">Spoof</a>'
        "</nav>"
    )
    homepage_links = same_site_html_links(homepage_html, ROOT)
    assert len(homepage_links) == _MAX_LINKS
    assert any(l["url"] == INDEX for l in homepage_links)
    assert all("evil.test" not in l["url"] for l in homepage_links)

    directory_html = (
        "<main>" + "".join(
            f'<a href="/news-release/unrelated/{i}/story/">News {i}</a>'
            for i in range(180)
        ) + "".join(
            f'<a href="/mission/apollo-{i}/">Apollo {i}</a>'
            for i in (1, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17)
        ) + "</main>"
    )
    directory_links = same_site_html_links(directory_html, INDEX)
    assert len(directory_links) == _MAX_LINKS
    assert any(l["url"] == ARTICLE and l["title"] == "Apollo 11"
               for l in directory_links)


def test_official_nasa_index_navigation_selects_exact_numbered_mission():
    homepage = fetched(ROOT, [{"url": INDEX, "title": "A to Z List of Missions"}])
    bad = searched("nasa.gov apollo moon",
                   {"url": "https://www.apollo.de/", "title": "Apollo Optiker"})
    search_again = searched("apollo nasa moon",
                            {"url": "https://en.wikipedia.org/wiki/Apollo_11",
                             "title": "Apollo 11"})

    observations = [bad, search_again, homepage]
    directory = choose_official_publisher_step(GOAL, observations)
    assert directory["action"] == "fetch_url"
    assert directory["query"] == INDEX
    assert has_discovered_deeper_primary_link(GOAL, observations)
    assert missing_official_answer_document(GOAL, observations)

    index = fetched(INDEX, [
        {"url": "https://www.nasa.gov/mission/apollo-17/", "title": "Apollo 17"},
        {"url": "https://www.nasa.gov/mission/apollo-1/", "title": "Apollo 1"},
        {"url": "https://www.nasa.gov.evil.test/mission/apollo-11/",
         "title": "Apollo 11"},
        {"url": ARTICLE, "title": "Apollo 11"},
    ])
    observations.append(index)
    chosen = choose_official_publisher_step(GOAL, observations)
    assert chosen["action"] == "fetch_url"
    assert chosen["query"] == ARTICLE
    assert has_discovered_deeper_primary_link(GOAL, observations)
    assert missing_official_answer_document(GOAL, observations)

    observations.append(fetched(ARTICLE, text=(
        "Apollo 11's lunar module touched down on July 20, 1969. "
        "Neil Armstrong became the first human to set foot on the Moon."
    )))
    assert not missing_official_answer_document(GOAL, observations)
    assert choose_official_publisher_step(GOAL, observations) is None


def test_no_observed_mission_directory_does_not_guess_its_url():
    observations = [
        searched("nasa.gov apollo moon",
                 {"url": "https://www.apollo.io/", "title": "Apollo.io"}),
        fetched(ROOT, [{"url": "https://www.nasa.gov/news/latest/",
                        "title": "NASA News"}]),
    ]
    result = choose_official_publisher_step(GOAL, observations)
    assert result["action"] == "search_web"
    assert "https://www.nasa.gov/a-to-z-of-nasa-missions/" not in result["query"]
