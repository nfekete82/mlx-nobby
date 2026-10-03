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

## Real runtime and release acceptance

Real model inference and actual browser playback require a separate local Mac
acceptance suite. Browser CI alone does not approve a release. The real-runtime
commands and release gate will be added after the browser acceptance PR merges.
