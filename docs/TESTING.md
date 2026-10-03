# Testing

## Unit and integration

`test-venv/bin/python -m pytest -q` runs CPU-only Python tests, including
production TestClient/proxy contracts. `node --test tests/*.mjs` runs the existing
JavaScript regressions. See the Tests workflow for syntax, JSON, translation,
shell, plist, dependency and Docker checks.

## Browser acceptance

```sh
python3.13 -m venv test-venv
test-venv/bin/python -m pip install -r requirements/test.txt
test-venv/bin/python -m playwright install chromium --only-shell
./scripts/mlx test-e2e
```

On Linux install browser system dependencies with
`test-venv/bin/python -m playwright install --with-deps chromium --only-shell`.
`MLX_TEST_PYTHON` overrides the Python executable; otherwise the command uses
`test-venv/bin/python`, falling back to `python3`. Additional pytest arguments
are accepted, for example `./scripts/mlx test-e2e -k read_aloud`.

Playwright 1.63.0 drives Chromium at desktop 1440×1000 and mobile 390×844
viewports. Tests start the real `backend.entrypoint:app` and a deterministic
Agent response fixture on allocated loopback sockets. Production HTML, CSS,
JavaScript, route middleware, proxy transport and SSE handling are exercised.
No local runtime configuration, installed services, chats or models are used.
The test command never downloads models or browsers; installation is explicit.

The existing pytest and Node helpers remain the lower-level regression suite.
The browser harness adds real browser coverage rather than replacing those
contracts. PNG and PCM WAV fixtures are generated in memory with existing
Pillow and Python standard-library facilities; no media binaries are committed.
CI speech uses actual Audio objects, Fetch, Blob and object URLs with controlled
play/pause events. CI video checks control calls with the same media-layer
control. These tests do not certify actual decoding or physical playback.

Browser errors fail tests by default. Expected speech HTTP errors are allowed
only within their failure scenario. Failures retain screenshots, Playwright
traces, recorded video, console/network logs and Agent requests under
`test-results/<test-name>/`. Successful recordings are removed. GitHub uploads
failure diagnostics for seven days. View a trace with
`test-venv/bin/python -m playwright show-trace test-results/<test-name>/trace.zip`.

The Browser acceptance workflow runs on pull requests and pushes to main,
separately from the existing Tests workflow. Normal pytest runs do not collect
browser tests; the explicit `--e2e` option enables them.

## Infrastructure audit

The existing suite has pytest fixtures, FastAPI TestClient integration, SSE
chunk fixtures and Node VM/DOM doubles (including speech lifecycle, image
preview/gallery, video profile and cancellation). It has no existing browser
framework or general network Agent fixture. Existing media tests construct
small bytes/files per test; the browser suite follows this convention.

Production serves `frontend/chat.html` through `backend.entrypoint` with feature
middleware and proxies to `AGENT_URL`. Production web starts through Compose
(`./scripts/dev-web.sh`, `docker compose up -d --build mlx-web`); native services
use `./scripts/mlx` and launchd. `restart-all` and `stop-all` are operational
commands, not needed by deterministic acceptance. Production ports are 8090
(web), 8010 (Agent), 8000 (chat), 8030 (images), 8050 (speech), 8060 (video),
8020 (embeddings), 8040 (vision), and 11234 (shared endpoint). Browser acceptance
allocates separate ports and only terminates its own processes.

## Local real runtime acceptance

```sh
./scripts/mlx test-real
./scripts/mlx test-real --full   # optional one-scene Short, at least 5 seconds / 540p
./scripts/mlx test-release
```

The real suite requires Apple Silicon macOS, an already running production web
app/Agent and configured local models. It uses the existing web APIs, native
health endpoints and Chromium from browser acceptance. It never starts/stops
services, selects/downloads models, installs a runner, changes credentials,
clears caches or performs a global reset. The Chat role must already use the
loaded model. The existing production Runtime Coordinator may release idle
weights for media and restore chat afterwards; acceptance checks that the
original chat model is online again.

Preflight records service/capability readiness and refuses to run while foreign
media jobs are active. Unavailable optional services/models are SKIP; a service
advertised online that fails its probe is FAIL. Features advertised available
must pass their real requests. Missing browser installation is FAIL; missing
FFmpeg/ffprobe skips audio/video generation before creating expensive jobs.

Each run uses `acceptance-<UTC timestamp>-<random>` for its chat ID, title, job
run IDs and Shorts draft title. Only those chats/drafts and jobs are cleaned up.
The browser uses a disposable profile with the test session selected. Existing
history that would trigger production's legacy empty-chat deletion blocks the
browser check, so acceptance does not delete that user data. Native terminal
queue/job/video records follow existing service retention; no unsupported file
or queue deletion is performed. Generated media copies and diagnostics remain
under `artifacts/acceptance/<run-id>/`, excluded from Git.

Default checks cover Chat SSE with a marker and terminal `done`, stateless
Gateway completion and usage, real TTS generation/decoding, browser read-aloud
with native Audio/play/pause/resume/end, a seeded small image using the already
configured image provider, image browser preview, a standard 2-second video
Preview, native Chromium video playback, cancellation after native dispatch,
Uncensored capability/rejection without generation, and Shorts draft/read/preflight.
Only technical media quality is asserted: decoding, nonzero duration/dimensions,
image nonuniformity, video frame rate/frames, MIME, bytes and actual playback time.
Real playback never replaces `HTMLMediaElement.play()` or `pause()`.

The optional `--full` Short uses one 5-second scene at the cheapest existing
Shorts quality (540p); Shorts does not support the 2-second Preview contract.
The default release gate therefore skips full Shorts. No Uncensored output is
generated, including when its adapter becomes available.

Timeout options are `--chat-timeout` (90 seconds), `--tts-timeout` (90),
`--image-timeout` (300) and `--video-timeout` (360). HTTP calls, media probes,
browser waits, cancellation and runtime restoration also have bounded waits.
A media timeout names its service/job and last status, phase and progress.
`--url`, `--speech-url` and `--video-url` support alternate HTTP loopback ports;
remote hosts and embedded credentials are rejected.

The final table and `summary.json`/`summary.txt` list PASS/FAIL/SKIP, durations
and reasons. Browser traces/screenshots, console/network logs, media copies and
job polling snapshots and before/after service-state snapshots support diagnosis.
An actual failure returns nonzero;
all PASS or explicitly permitted SKIP returns zero. A failed generation keeps
the overall run failed even if its dependent browser check skips.

`test-release` runs each layer once: existing Python/subtests, JavaScript,
syntax/JSON/i18n/shell/plist/help/docs, pip, Compose/Docker build, diff, deterministic
browser acceptance and real acceptance. `--full` is an explicit opt-in there
also. The complete CI and both acceptance commands must additionally pass on
final main before `READY_FOR_V1_6_2=YES`; these commands never tag or release.
