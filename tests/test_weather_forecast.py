"""Offline regression tests for structured current/tomorrow forecasts."""
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

from backend.weather_forecast import weather_request, forecast_for_question


NOW = datetime(2026, 10, 15, 8, 20, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.value[:size]


def fake_provider(*, no_results=False, bad_forecast=False):
    calls = []
    geo = {"results": [{
        "name": "Göppingen",
        "country": "Deutschland",
        "country_code": "DE",
        "admin1": "Baden-Württemberg",
        "latitude": 48.7015,
        "longitude": 9.6521,
        "timezone": "Europe/Berlin",
        "population": 58000,
        "postcodes": ["73033", "73035"],
    }]}
    forecast = {
        "daily": {
            "time": ["2026-10-15", "2026-10-16", "2026-10-17"],
            "weather_code": [3, 61, 0],
            "temperature_2m_max": [16.5, 14.0, 17.0],
            "temperature_2m_min": [7.0, 6.0, 8.0],
            "precipitation_probability_max": [35, 75, 5],
        },
        "current": {
            "time": "2026-10-15T10:15", "temperature_2m": 12.1,
            "weather_code": 3,
        },
    }
    def opener(request, timeout):
        assert request.full_url.startswith("https://")
        assert timeout <= 6
        calls.append(request.full_url)
        if urlparse(request.full_url).hostname == "geocoding-api.open-meteo.com":
            return FakeResponse({"results": []} if no_results else geo)
        return FakeResponse({"daily": {"time": []}} if bad_forecast else forecast)
    return opener, calls


def test_parses_german_weather_questions_but_not_unrelated_prompts():
    for prompt in (
        "Wie wird das Wetter heute in Göppingen?",
        "Wetter in Göppingen heute",
        "Wettervorhersage für Göppingen",
        "Wetter Göppingen morgen",
    ):
        assert weather_request(prompt)["city"] == "Göppingen"
    assert weather_request("Wetter Göppingen morgen")["offset"] == 1
    assert weather_request("Wie wird das Wetter heute?")["status"] == "location_required"
    assert weather_request("Was ist 50 x 50?") is None
    assert weather_request("Schreibe Python-Code für Wetter in Göppingen") is None
    assert weather_request("Wetter 73033 morgen")["city"] == "73033"


def test_forecast_today_grounded_correct_date_and_values():
    opener, calls = fake_provider()
    result = forecast_for_question(
        "Wie wird das Wetter heute in Göppingen?", opener=opener, now=NOW
    )
    assert result["status"] == "available"
    assert "Göppingen, Baden-Württemberg, Deutschland" in result["answer"]
    assert "15.10.2026" in result["answer"]
    assert "aktuell 12.1 °C" in result["answer"]
    assert "7–16.5 °C" in result["answer"]
    assert "35 % Regenwahrscheinlichkeit" in result["answer"]
    assert "Open-Meteo" in result["answer"]
    assert result["target_date"] == "2026-10-15"
    assert len(calls) == 2
    assert parse_qs(urlparse(calls[0]).query)["name"] == ["Göppingen"]


def test_tomorrow_uses_correct_forecast_day_without_todays_temperature():
    opener, _ = fake_provider()
    result = forecast_for_question(
        "Wetter Göppingen morgen", opener=opener, now=NOW
    )
    assert result["status"] == "available"
    assert "16.10.2026" in result["answer"]
    assert "leichter Regen" in result["answer"]
    assert "6–14 °C" in result["answer"]
    assert "75 % Regenwahrscheinlichkeit" in result["answer"]
    assert "aktuell" not in result["answer"]


def test_unknown_city_and_provider_failure_are_not_fabricated():
    opener, calls = fake_provider(no_results=True)
    result = forecast_for_question("Wetter Göppingen", opener=opener, now=NOW)
    assert result["status"] == "location_unknown"
    assert len(calls) == 1
    opener, _ = fake_provider(bad_forecast=True)
    result = forecast_for_question("Wetter Göppingen", opener=opener, now=NOW)
    assert result["status"] == "unavailable"
    assert "keine Vorhersage erfinden" in result["answer"]
    def offline(*args, **kwargs):
        raise OSError("offline")
    result = forecast_for_question("Wetter Göppingen", opener=offline, now=NOW)
    assert result["status"] == "unavailable"


def test_missing_place_never_calls_external_provider():
    def reject(*_args, **_kwargs):
        raise AssertionError("do not send unlocated prompt to provider")
    result = forecast_for_question("Wie wird das Wetter heute?", opener=reject)
    assert result["status"] == "location_required"


def test_native_search_tool_uses_forecast_without_searxng():
    from agent.app import tool_search_web
    from types import SimpleNamespace
    with patch("backend.weather_forecast.forecast_for_question",
               return_value={"status": "available", "answer": "Wettertest"}), \
         patch("agent.app.searxng_search_results",
               side_effect=AssertionError("SearXNG not needed")):
        result = tool_search_web(SimpleNamespace(
            prompt="Wie wird das Wetter heute in Göppingen?"
        ))
    assert result["weather_forecast"]["answer"] == "Wettertest"
    assert result["provider"] == "Open-Meteo"
    assert result["count"] == 0


def test_direct_chat_weather_response_skips_chat_model():
    from backend.app import ChatRequest, mlx_chat_stream
    async def get_body(stream):
        chunks = []
        async for chunk in stream.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    with patch("backend.weather_forecast.forecast_for_question", return_value={
            "status": "available", "answer": "12 °C von Open-Meteo",
        }), patch("backend.app.agent_json_request",
                   side_effect=AssertionError("Do not run model")):
        stream = mlx_chat_stream(ChatRequest(messages=[
            {"role": "user", "content": "Wetter in Göppingen heute"}
        ]))
        body = asyncio.run(get_body(stream))
    assert "12 °C von Open-Meteo" in body
    assert "event: done" in body
    assert "\\n\\n" not in body


def test_postcode_uses_geocoder_postcode_even_when_result_has_city_name():
    opener, urls = fake_provider()
    result = forecast_for_question("Wetter 73033", opener=opener, now=NOW)
    assert result["status"] == "available"
    assert "Göppingen" in result["answer"]
    assert parse_qs(urlparse(urls[0]).query)["name"] == ["73033"]
