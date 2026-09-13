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
    for test in tests/*.mjs; do node "$test" || exit 1; done

Validate shell scripts:

    bash -n scripts/install.sh
    bash -n scripts/mlx
    bash -n scripts/doctor.sh
    bash -n scripts/install-launchd.sh

Validate Docker Compose:

    docker compose config

## Pull requests

Please keep pull requests focused and avoid unrelated refactors.

Before submitting a pull request:

- run the relevant tests
- run `git diff --check`
- do not include local configuration or secrets
- document behavior changes when appropriate
- keep public documentation in English
- keep English and German translation keys in sync
