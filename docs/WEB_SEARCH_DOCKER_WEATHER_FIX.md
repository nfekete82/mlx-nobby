# Web search reliability: Docker import boundary and weather relevance

## 2026-10-15 incidents

A news freshness fix introduced an import of `agent.search_freshness` inside
`backend.web_research.retrieve_web_research`. The **production Dockerfile
copies only `backend/`**, not `agent/`. Any request routed to public web
research could therefore fail with `ModuleNotFoundError: No module named
'agent'` before reaching the search provider. This included questions such as
`Wer war der erste Bundeskanzler ...?` because `Bundeskanzler` is a
time-sensitive search marker.

Separately, the user's `Wie wird das Wetter heute?` query had no location.
The general-purpose DuckDuckGo Lite search supplied unrelated bpb.de
history/politics results, which the LLM cited as purported weather evidence.

## Corrections

- The timestamp validator is now **owned by `backend.search_freshness`**.
  The native agent re-exports it via `agent.search_freshness`; web and
  agent use the exact same logic without the web depending on the agent
  package or widening the production image.
- The CI Docker job runs an **import smoke test inside the built minimal
  web container**, verifying the `agent` package is genuinely absent and
  the web research code still imports, parses News dates, and handles empty
  results.
- The common standalone question `Wie wird das Wetter heute?` without
  a location gets a concise, immediate request for a city/ZIP instead
  of web browsing, routing, or model inference. This applies to a
  **single-turn text request** only; follow-up chats retain their
  normal conversation context.
- Weather research with an explicit location accepts only
  meteorologically relevant forecast results on established weather
  domains, and rejects irrelevant politics/history articles even when
  a public search provider ranked them highly. The generic Google News
  RSS fallback is disabled for weather.
- Missing relevant forecast sources remain an **unknown outcome**, not
  evidence of sunshine, precipitation or other weather conditions.
  Research remains opt-in for public, non-private prompts; no new
  transmission of chat history/files or location to arbitrary services.

## What this fix cannot prove

This does not establish that the user's SearXNG instance on port 8081 is
healthy. Native agent tools use a **separate search path** from the web
container's guarded DuckDuckGo Lite/RSS research. Diagnose the local
search backend read-only via:

```sh
cd ~/mlx-web
python3 -m agent.search_diagnostic --query "Wetter Göppingen"
curl -sS --max-time 5 -o /dev/null -w 'SearXNG HTTP %{http_code}\n' \
  'http://127.0.0.1:8081/search?q=Wetter+G%C3%B6ppingen&format=json'
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

An actual weather forecast requires a place and a functioning
meteorological source; this patch does **not** invent temperature or
fallback to generic News content.

Also independent of search, the Observatory recorded ordinary text-chat
`chat.stream` inputs above 10,000 tokens and 13–16 s TTFT. The next
performance diagnosis should examine full system prompt/profile/context
sizes with the existing `/api/performance/observatory` telemetry.
