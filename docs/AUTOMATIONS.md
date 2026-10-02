# Automations and notifications

## User workflow

Open **Settings → Automations**. Create an agent task (diagnostic, research or
coding with the intended workspace) or a Model Scout search. Choose manual,
hourly, daily or weekly execution, timezone and time/minute/weekday. Enable or
disable the schedule, run it explicitly, and inspect saved runs/results.

The native agent owns scheduling and must be running. Model Scout discovery
contacts Hugging Face; scheduled discovery does not automatically download or
benchmark models. Agent tasks retain ordinary workspace and approval gates.
A pending action produces `needs_approval`, not successful unattended mutation.

## Persistence and recovery

Definitions/runs use SQLite/WAL in `~/.config/mlx-web/automations.db`.
Schedules use IANA timezones; weekly weekdays are 0 (Monday) through 6 (Sunday),
and hourly minute is 0–59. Only one queued/running run per automation is allowed;
manual overlap returns 409. The scheduler claims due tasks in bounded batches.
It does not promise execution while the Mac/agent is offline.

On scheduler startup, stale queued/running runs in its bounded recent-run scan
are marked failed with a restart notification. They are not automatically
resumed. Definitions and future schedules remain persisted. Approval state is
process-local and does not survive agent restart.

## Notifications

The notification area lists saved local results, unread count, individual Read
and Read all actions. Records live in the automation database. Best-effort macOS
delivery uses the local notification bridge and records delivery failure; the
in-app record remains available. Completion/failure/approval events can notify.
Model Scout suppresses repeat notifications without new candidates after the
initial successful discovery. Notifications are not a guaranteed external
push/email delivery service.

## Local API

Agent paths are below; web proxies use `/api/mlx/automations` in place of
`/api/automations`, preserving the suffix. JSON results are forwarded.

| Method | Agent path | Contract |
| --- | --- | --- |
| GET | `/api/automations` | `{automations}` |
| POST | `/api/automations` | Definition object → created definition, 201 |
| GET | `/api/automations/{automation_id}` | Definition or 404 |
| PUT | `/api/automations/{automation_id}` | Update definition; invalid fields/options 400 |
| DELETE | `/api/automations/{automation_id}` | `{ok: true}` or 404 |
| POST | `/api/automations/{automation_id}/run` | Accepted run, 202; active overlap 409 |
| GET | `/api/automations/runs` | Optional `automation_id`, `limit=50` (1–200) → `{runs}` |
| GET | `/api/automations/runs/{run_id}` | Run with result/status or 404 |
| GET | `/api/automations/notifications` | `limit=50` (1–200), `unread_only=false` → `{notifications, unread_count}` |
| POST | `/api/automations/notifications/read-all` | `{ok, updated, unread_count}` |
| POST | `/api/automations/notifications/{notification_id}/read` | Updated record or 404 |

Definitions include `name`, `kind=agent|model_scout`, `prompt`,
`mode=diagnostic|research|coding`, optional `workspace_id`, `enabled`, and
`schedule={type, timezone, time, weekday, minute}` as appropriate. Flat schedule
fields are also accepted. See `agent/automations.py` for validation/defaults.
Run states include queued, running, completed, failed, cancelled and
needs_approval. A run result may contain an AgentRuntime pending action;
reading a notification does not approve it.

Source: `agent/automations.py`, `agent/automation_routes.py`,
`agent/automation_notifications.py`, `backend/automation_routes.py`,
`frontend/assets/chat/automations.js` and `automation-notifications.js`.
Regression coverage: `tests/test_automations.py`,
`tests/test_automation_notifications.py` and corresponding UI tests.
