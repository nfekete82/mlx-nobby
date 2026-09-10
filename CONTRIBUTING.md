# Contributing

Contributions are welcome.

## Development environment

MLX Nobby targets macOS on Apple Silicon.

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

    python3 -m venv .venv-test
    source .venv-test/bin/activate
    pip install -r requirements/test.txt

## Tests

Run the Python test suite:

    python -m unittest discover -s tests -p 'test_*.py'

Run JavaScript checks:

    node --check frontend/assets/chat.js
    node tests/test_model_console.mjs
    node tests/test_chat_scroll.mjs
    node tests/test_history_cleanup.mjs

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
