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


## Diagnose: SearXNG erreichbar, aber alle Suchmaschinen blockiert

Wenn die JSON-Suche erreichbar ist, jedoch ausschließlich `degraded` und null
Suchtreffer liefert, behebt ein weiterer SearXNG-Container das Problem nicht.
Das Problem liegt dann bei den aktiven Upstream-Suchmaschinen oder ihrer
Konfiguration. Die Klassifizierungen `captcha` und `rate_limited` betreffen
die externen Suchmaschinen, nicht die JSON-Ausgabe des lokalen Dienstes.

Aktuelle Beispiel-Diagnose (2026-10-11; diese Werte sind zeitabhängig):
Brave und Google CSE: `rate_limited`; DuckDuckGo und Startpage:
`captcha`; Wikipedia: `unavailable`.

**Vor jeder Änderung** den bestehenden Container und die Quelle der
Konfiguration schreibgeschützt prüfen:

```sh
docker inspect searxng --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
docker inspect searxng --format '{{index .Config.Labels "com.docker.compose.project"}}'
docker exec searxng sh -c 'grep -n -E "^(use_default_settings:|engines:|[[:space:]]+- name:|[[:space:]]+disabled:|[[:space:]]+inactive:)" /etc/searxng/settings.yml | head -100'
```

Die Ausgabe filtert sensible Schlüssel und API-Tokens weg. Für bestehende
Installationen die tatsächlich gemountete Konfigurationsdatei sichern,
bevor Suchmaschinen verändert werden. Keine komplette `settings.yml`
durch eine Vorlage ersetzen: Darin können wichtige vorhandene Einstellungen,
Tokens und Secrets stehen. Wenn kein persistenter Mount existiert, erst die
Containerverwaltung identifizieren und die Persistenz herstellen; Änderungen
nur innerhalb des Containers wären nicht dauerhaft.

SearXNG erlaubt gezielte Overrides einzelner Engines per Namen:

```yaml
use_default_settings: true
engines:
  - name: brave
    disabled: true
  - name: duckduckgo
    disabled: true
  - name: google cse
    disabled: true
  - name: startpage
    disabled: true
```

**Das ist ein Ausschnitt, keine komplette Ersatz-Konfiguration.** Vorhandene
`use_default_settings`- und `engines`-Abschnitte sachgerecht ergänzen,
nicht duplizieren. Andere Engines gezielt testen und nur solche einschalten,
die auf dieser Maschine zuverlässig direkte Artikel-URLs zurückliefern.
`bing` und `mojeek` sind mögliche Testkandidaten, **keine zugesicherte
Lösung**; Installation, Verfügbarkeit, Nutzungsbedingungen und eventuelle
Blockierung hängen von der Instanz ab. Erst nach erfolgreichem Suchtest
über die normale Containerverwaltung neu starten und Nobby erneut prüfen.
Keine CAPTCHA-Umgehung, aggressiven Retry-Schleifen oder Proxyrotation.

Weitere Details: https://docs.searxng.org/admin/settings/settings.html


### Safe automated host-config override (existing `searxng` Compose project)

When the host mount is `~/searxng/config -> /etc/searxng`, and the original
file contains `use_default_settings: true` with **no top-level `engines:`**,
the repository provides a guarded script. It does **not** replace or print the
existing secret key or other settings. It stops if custom `engines:` overrides
already exist, makes a timestamped private backup in the same directory,
preserves permissions and writes the changes atomically.

```sh
python -m pytest -q tests/test_configure_searxng_engines.py
python scripts/configure_searxng_engines.py
python scripts/configure_searxng_engines.py --apply
docker restart searxng
python -m agent.search_diagnostic --query "Apple iPhone"
python -m agent.search_diagnostic --query "site:apple.com/newsroom iPhone"
```

The override disables Brave, DuckDuckGo, Google CSE and Startpage after
observed 429/CAPTCHA responses. It enables Bing, Qwant and Yahoo for testing,
**without guaranteeing those engines work**. Keep Wikipedia's status separate;
it may fail on the site-restricted query. If all replacement engines fail,
inspect `docker logs --tail 80 searxng`, review upstream errors, and avoid
repeated rapid retries. To restore the old configuration, copy the
timestamped `settings.yml.backup-...` back to `settings.yml` and restart
only `searxng`.

Once SearXNG returns direct search URLs, restart the Nobby agent and repeat
the live question. The 64-case semantic verifier benchmark is not a substitute
for testing real search coverage.
