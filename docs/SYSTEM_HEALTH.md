# System Health & Self-Healing v1

System Health extends the existing Advanced → Server settings view with a local diagnostic dashboard.

## Services

The dashboard checks the local MLX Nobby stack:

- LLM Runtime — 8000
- Agent — 8010
- Embeddings — 8020
- Images — 8030
- Router / Vision — 8040
- Speech — 8050
- Video — 8060
- Web UI — 8090
- MLX Serve — 11234

For each service it reports the health state, PID when available, process uptime, resident memory, health latency, current model, active job and the latest error-like line from the launchd stderr log.

## Actions

`Restart` restarts one allow-listed service. Launchd services use `launchctl kickstart -k`; the Web UI uses `docker compose restart mlx-web`. Restarting the Agent is scheduled after the HTTP response so the request can complete cleanly.

`Copy diagnosis` creates a compact plain-text snapshot suitable for bug reports without copying complete log files.

`Run self-healing`:

1. refreshes the health snapshot;
2. restarts unhealthy launchd services except the Agent currently serving the request and the Web UI currently hosting the page;
3. retries image/video media jobs that have shown no status/progress/step change for the configured stuck timeout;
4. returns old/new job mappings so the active browser session can resume polling the replacement jobs.

## Stuck-job detection

The default threshold is 90 seconds and can be changed with:

```bash
MLX_SYSTEM_HEALTH_STUCK_SECONDS=120
```

A media job is only considered stuck after the health observer has seen the exact same running progress signature for the whole threshold. Waiting jobs are not considered stuck. A progress or step change resets the timer.

## Routes

Agent:

- `GET /api/system/health-v1`
- `POST /api/system/services/{service_id}/restart`
- `POST /api/system/self-heal`

Web proxy:

- `GET /api/mlx/system/health-v1`
- `POST /api/mlx/system/services/{service_id}/restart`
- `POST /api/mlx/system/self-heal`
