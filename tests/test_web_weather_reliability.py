"""Offline checks: Docker-package imports and weather source relevance."""
import asyncio
from unittest.mock import patch

from backend.weather_search import (
    is_weather_query, is_locationless_weather_question, relevant_forecast_result,
)
from backend.web_research import needs_web_research, retrieve_web_research


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload.encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, count):
        return self.payload[:count]


def test_freshness_import_is_available_without_agent_package():
    # The production Dockerfile copies backend/, NOT agent/.
    from backend.search_freshness import requires_today_news, filter_today_news
    assert requires_today_news("News von heute") is True
    assert filter_today_news([], now=None) == []


def test_placeless_weather_does_not_trigger_web_research():
    for prompt in (
        "Wie wird das Wetter heute?",
        "Wie ist das Wetter morgen?",
        "Wetter heute?",
        "Wird es heute regnen?",
    ):
        assert is_locationless_weather_question(prompt), prompt
        assert not needs_web_research(prompt)
        assert retrieve_web_research(
            prompt, opener=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("Do not search without a place")
            )
        ) == ""


def test_place_specific_forecast_remains_searchable():
    for prompt in (
        "Wie wird das Wetter heute in Göppingen?",
        "Wetter in Stuttgart morgen",
        "Wettervorhersage für Hamburg",
    ):
        assert is_weather_query(prompt)
        assert not is_locationless_weather_question(prompt)
        assert needs_web_research(prompt)


def test_general_search_facts_not_accidentally_blocked():
    assert needs_web_research("Wer ist aktuell Bundeskanzler?")
    assert needs_web_research("Was sind die News von heute?")


def test_only_relevant_weather_domains_and_titles_pass():
    assert relevant_forecast_result(
        "Wetter Stuttgart: Vorhersage", "https://www.dwd.de/wetter/region"
    )
    assert relevant_forecast_result(
        "Weather forecast Göppingen", "https://www.meteoblue.com/de/wetter"
    )
    assert not relevant_forecast_result(
        "Geschichte der DDR", "https://www.bpb.de/geschichte/ddr"
    )
    assert not relevant_forecast_result(
        "Wetter und Klimawandel in der Politik", "https://www.bpb.de/wetter"
    )
    assert not relevant_forecast_result(
        "Bundeskanzler News", "https://www.dwd.de/"
    )


def test_weather_research_rejects_unrelated_results():
    html = (
        '<a class="result-link" href="https://www.bpb.de/themen/">'
        'Deutsche Geschichte und der Kalte Krieg</a>'
        '<a class="result-link" href="https://www.dwd.de/wetter/stuttgart">'
        'Wetter Stuttgart: Aktuelle Vorhersage</a>'
    )
    result = retrieve_web_research(
        "Wie wird das Wetter in Stuttgart heute?",
        opener=lambda _request, timeout: FakeResponse(html),
    )
    assert "Wetter Stuttgart: Aktuelle Vorhersage" in result
    assert "www.dwd.de" in result
    assert "Deutsche Geschichte" not in result
    assert "www.bpb.de" not in result


def test_weather_research_does_not_replace_failed_forecast_with_google_news():
    captured = []
    def fake_open(request, timeout):
        captured.append(request.full_url)
        return FakeResponse("<html></html>")

    result = retrieve_web_research(
        "Wetter Göppingen morgen", opener=fake_open
    )
    assert "OHNE VERIFIZIERBARE ERGEBNISSE" in result
    assert len(captured) == 1
    assert "lite.duckduckgo.com" in captured[0]
    assert not any("news.google.com" in url for url in captured)


def test_first_weather_question_requests_city_without_agent_model_or_search():
    def cannot_run(*_args, **_kwargs):
        raise AssertionError("The weather-location query must not call agent or web")
    from backend.app import ChatRequest, mlx_chat_stream

    async def collect_stream(response):
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    with patch("backend.app.agent_json_request", side_effect=cannot_run):
        response = mlx_chat_stream(ChatRequest(
            messages=[{"role": "user", "content": "Wie wird das Wetter heute?"}]
        ))
        body = asyncio.run(collect_stream(response))
    assert "Nenne mir bitte eine Stadt oder Postleitzahl" in body
    assert "event: done" in body
    assert 'data: {"type": "content"' in body
    assert "\\n\\n" not in body  # actual SSE line endings, not escaped literals


def test_native_searxng_skips_search_when_weather_place_is_missing():
    from agent.app import searxng_search_results
    with patch("agent.app.request_searxng", side_effect=AssertionError("No location")):
        data = searxng_search_results("Wie wird das Wetter heute?")
    assert data["provider_status"] == "location_required"
    assert data["count"] == 0
    assert data["results"] == []


def test_native_searxng_keeps_real_forecast_but_rejects_political_results():
    from agent.app import searxng_search_results
    response = {
        "results": [
            {
                "title": "Deutsche Geschichte und DDR",
                "url": "https://www.bpb.de/politik/ddr",
                "content": "No weather information",
            },
            {
                "title": "Wetter Stuttgart: heutige Vorhersage",
                "url": "https://www.dwd.de/wetter/stuttgart",
                "content": "Meteorological conditions",
            },
        ],
        "unresponsive_engines": [],
    }
    with patch("agent.app.request_searxng",
               return_value=(response, [{"status": "available"}])), \
         patch("agent.app.web_url_is_safe", return_value=True), \
         patch("agent.app._fallback_public_search",
               side_effect=AssertionError("RSS fallback must not be used")):
        found = searxng_search_results("Wetter Stuttgart heute")
    assert found["provider_status"] == "available"
    assert [x["title"] for x in found["results"]] == [
        "Wetter Stuttgart: heutige Vorhersage"
    ]


def test_native_search_no_meteorological_source_fails_closed_without_news_rss():
    from agent.app import searxng_search_results
    response = {
        "results": [
            {"title": "Politik und die DDR",
             "url": "https://www.bpb.de/politik/ddr"},
        ],
        "unresponsive_engines": [],
    }
    with patch("agent.app.request_searxng",
               return_value=(response, [{"status": "available"}])), \
         patch("agent.app.web_url_is_safe", return_value=True), \
         patch("agent.app._fallback_public_search",
               side_effect=AssertionError("RSS fallback must not be used")):
        found = searxng_search_results("Wetter Göppingen")
    assert found["count"] == 0
    assert found["provider_status"] == "no_relevant_weather_sources"


def test_native_search_unavailable_weather_does_not_fall_back_to_news_rss():
    from agent.app import searxng_search_results
    with patch("agent.app.request_searxng",
               return_value=(None, [{"status": "unavailable"}])), \
         patch("agent.app._fallback_public_search",
               side_effect=AssertionError("RSS fallback must not be used")):
        found = searxng_search_results("Wetter Göppingen heute")
    assert found["provider_status"] == "weather_provider_unavailable"
    assert found["count"] == 0
