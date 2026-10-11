# MLX-Nobby: reliable local web-search backend

The agent expects a working SearXNG **JSON** search API at
`http://127.0.0.1:8081/search` unless its process environment overrides
`SEARXNG_URL`.

If this endpoint is unavailable, returns HTTP 403 (JSON format disabled), or
its engines consistently fail, MLX-Nobby falls back to Google News RSS. RSS
search entries are not article text and typically cannot establish current
manufacturer product lists or sales status. A successful agent run with zero
verified claims is a *research coverage failure*, not a good factual answer.

## Diagnose before installing anything

From the repository root, run:

```sh
python -m agent.search_diagnostic --query "Apple iPhone"
python -m agent.search_diagnostic --query "site:apple.com/newsroom iPhone"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

The diagnostic checks configured SearXNG instances with one read-only search.
It prints provider statuses, number of usable results, sample URL **hosts**,
and the names and **classified** failure types of unresponsive engines.
Raw engine error strings, full result URLs and fetched page content are omitted.
Compare the broad query with the site-restricted query: if only the restricted
query fails, the search engines' site-filter support may be the issue.
A `degraded` result with five unresponsive engines and zero results means
SearXNG's JSON endpoint is reachable but the *configured engines* failed;
do not install a second SearXNG container over an existing one. If `json_search_usable` is false,
inspect the `provider_attempts` and Docker logs. Failure causes include
stopped service, unavailable port, missing JSON permission, rate limits, and
all search engines being degraded.

Note: the diagnostic runs from your shell. If you set `SEARXNG_URL` only in
the agent's launchd configuration, pass the same endpoint explicitly with
`--endpoint` or inspect the agent's environment first.

## Optional private SearXNG instance

Only if port **8081 is free** and you do not already maintain a suitable
instance, start the isolated Compose file. Existing MLX-Nobby services are not
changed. Docker Desktop must be running.

```sh
python - <<'PY'
from pathlib import Path
import secrets
Path(".env.search").open("x", encoding="utf-8").write(
    "SEARXNG_SECRET=" + secrets.token_hex(32) + "\n"
)
PY
docker compose --project-name mlx-nobby-search \
  --env-file .env.search -f docker-compose.search.yml up -d
python -m agent.search_diagnostic
```

`.env.search` is Git-ignored; do not commit or share its content. The search
container binds only to `127.0.0.1:8081`, not all network interfaces.
The shipped local `search/searxng-settings.yml` enables both `html` and
`json` and disables the public-instance limiter for one local user. Do not
expose this configuration to the Internet.

If diagnostics show `403`, the running SearXNG may not have JSON output
enabled. SearXNG requires `search.formats` to contain `json`; this is
an explicit upstream documented setting.

If `json_search_usable` is still false, inspect:

```sh
docker compose --project-name mlx-nobby-search \
  --env-file .env.search -f docker-compose.search.yml logs --tail=60 searxng
```

After a healthy direct search, restart the local agent with
`mlx agent restart`, then evaluate one **unseen** research prompt and inspect
both the provenance and verified answer. A nonempty search result list is not
proof of correct retrieval or complete product coverage.

This optional instance uses the upstream container's rolling image tag;
review image updates before changing production infrastructure.

Upstream references:
- https://docs.searxng.org/admin/installation-docker
- https://docs.searxng.org/dev/search_api.html
- https://docs.searxng.org/admin/settings/settings.html
