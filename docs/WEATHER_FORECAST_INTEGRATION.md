# Weather forecast: structured provider, no generic search snippets

## Why

The local SearXNG health check on 15 October 2026 showed a healthy JSON
search backend (10 results for `Wetter Göppingen`, no unresponsive engines),
but the chat still answered that no trustworthy forecast could be found.
An HTML snippet is not an actual meteorological observation/forecast;
strict relevance filtering rightfully rejects unrelated articles.

## New flow

- For simple questions explicitly naming a location (e.g. `Wie wird das
  Wetter heute in Göppingen?`, `Wetter Göppingen morgen`), the native
  agent's `tool_search_web` now queries a dedicated read-only provider
  module instead of generic SearXNG. The direct web chat stream also
  handles these queries without requiring a full LLM inference.
- It resolves the **explicitly supplied place name** through
  `https://geocoding-api.open-meteo.com/v1/search`, then requests
  current/daily weather for the returned coordinates through
  `https://api.open-meteo.com/v1/forecast`. Open-Meteo documents both
  interfaces at https://open-meteo.com/en/docs and
  https://open-meteo.com/en/docs/geocoding-api.
- Temperatures, forecast condition codes, and daily precipitation
  probability appear only when returned as real structured fields for
  the correct location-local calendar date. The result includes the
  resolved place name, date and a direct provider source URL.
- A weather question **without any place** still asks for the city or
  postal code. The assistant does not infer a place from a profile,
  memory, system info or chat history.
- Provider/forecast failures return a brief honest status, never a
  fabricated number or generic-news fallback. Normal research/coding/
  finance/image routes remain unaffected.
- Forecast responses bypass the LLM, so they do not append 10k tokens of
  third-party search context or incur a 27B prefill. This is an
  architecture change, not a claimed measured speedup.

## Privacy and limitations

Only the explicitly requested city or postal code is shared for
geocoding, and its retrieved geographic coordinates are then sent to
Open-Meteo. **No private files, account data or conversation history**
are transmitted. No arbitrary user-provided URLs are fetched. All
provider requests are HTTPS to fixed hosts with short timeouts and a
bounded response size.

The parser deliberately supports ordinary current/tomorrow queries,
not arbitrary climate studies, weather alerts, multi-city comparison
or historical weather. Ambiguous/missing places and missing/invalid
provider data must not be answered from the model's guesswork.

Open-Meteo's public noncommercial API is suitable for personal local
testing; evaluate terms/rate limits before any business deployment.

## Validation

```bash
python3 -m pytest -q tests/test_weather_forecast.py tests/test_web_weather_reliability.py
node --test tests/test_video_job.mjs
docker compose up -d --build --no-deps mlx-web
mlx agent restart
```

Then test in **a new chat** with `Wie wird das Wetter heute?`,
`Wie wird das Wetter heute in Göppingen?`, and `Wetter Göppingen
morgen`. If the forecast provider is not accessible from the Mac/Docker,
the answer explicitly reports unavailability. The existing
`python3 -m agent.search_diagnostic` only tests SearXNG, not the
separate forecast API.
