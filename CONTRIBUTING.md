# Contributing

Contributions are welcome.

## Development environment

MLX nobby targets macOS on Apple Silicon.

Recommended tools:

- Python 3.13
- Node.js
- Docker
- FFmpeg
- Homebrew

## Setup

Run:

    ./scripts/install.sh --no-launchd --no-docker

For test dependencies:

    python3.13 -m venv test-venv
    test-venv/bin/python -m pip install -r requirements/test.txt

The installer creates the native service environments by default. Pass
`--no-python` as well when they already exist and you only want to validate the
bootstrap steps.

## Tests

Run the Python test suite:

    test-venv/bin/python -m pytest -q

Run Python, translation, and JSON checks:

    git ls-files -z '*.py' | xargs -0 test-venv/bin/python -m py_compile
    python3 scripts/i18n-audit.py
    git ls-files -z '*.json' | xargs -0 -n1 python3 -m json.tool >/dev/null

Run JavaScript checks:

    find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
    node --test tests/*.mjs

Validate shell scripts:

    bash -n scripts/install.sh
    bash -n scripts/mlx
    bash -n scripts/doctor.sh
    bash -n scripts/install-launchd.sh

Validate Docker Compose:

    docker compose config

## Releases

The canonical release procedure is documented in
[docs/RELEASING.md](docs/RELEASING.md).

## Code organization

Keep `agent/app.py` focused on application composition and route wiring. New
substantial features should live in focused modules under `agent/` and be
imported into the application instead of growing `agent/app.py` further.
Prefer small, feature-oriented modules with explicit boundaries over unrelated
large refactors.

Frontend feature loading should live in the shared bootstrap layer rather than
inside unrelated feature modules. Avoid adding global `window.fetch` wrappers
unless the behavior genuinely needs to intercept every matching request; prefer
dedicated request helpers for new functionality.

## Pull requests

Please keep pull requests focused and avoid unrelated refactors.

Before submitting a pull request:

- start from an up-to-date `main`
- run the relevant tests
- run `git diff --check`
- do not include local configuration or secrets
- document behavior changes when appropriate
- keep public documentation in English
- keep English and German translation keys in sync
- merge short-lived feature branches promptly and delete them after merge
