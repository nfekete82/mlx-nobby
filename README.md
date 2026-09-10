# MLX Nobby

Local AI platform for Apple Silicon built around MLX, FastAPI and native macOS services.

MLX Nobby combines local language models, coding agents, multimodal models, speech, embeddings/RAG and image generation in a unified local interface.

## Highlights

- Native MLX inference on macOS / Apple Silicon
- Local LLM chat and model switching
- Coding workspace with read/write tooling
- Diagnostic and research agents
- Multimodal VLM support
- Speech-to-text
- Local embeddings and RAG
- Image generation
- FastAPI-based service architecture
- Dockerized web frontend/backend
- Native MLX services remain outside Docker
- Loopback-only service binding by default
- Request-size and host validation

## Architecture

    Browser
      |
      v
    Docker Web Service :8090
      |
      v
    Native Agent :8010
      |
      +--> MLX / MLX-VLM Runtime :8040
      +--> Speech Service :8050
      +--> Image Service :8030
      +--> Embeddings / RAG

The web layer can run in Docker, while MLX inference stays native on macOS to retain Apple Silicon / Metal performance.

## Requirements

- macOS
- Apple Silicon
- Python 3.13 for most services
- Python 3.11 for the isolated DiffusionKit environment
- Docker / Docker Compose for the web service
- Node.js for frontend tests

## Python environments

The project intentionally uses separate Python environments because some MLX-related packages require different dependency versions.

See:

- `docs/DEPENDENCIES.md`
- `requirements/`

## Testing

Create a clean test environment:

    python3 -m venv .venv-test
    source .venv-test/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements/test.txt

Run the tests:

    python -m unittest discover -s tests -p 'test_*.py'
    node --check frontend/assets/chat/models.js
    node tests/test_model_console.mjs

Current verification:

- 107 Python tests passed
- JavaScript model runtime tests passed
- `pip check` passed
- `docker compose config` passed
- `git diff --check` passed

## Docker web service

Start the web service:

    docker compose up --build

By default the web interface is published only on localhost:

    http://127.0.0.1:8090

The Docker container connects to the native agent service through `host.docker.internal`.

## Configuration

Copy the example configuration:

    cp .env.example .env

Then adjust the values as needed.

Do not commit credentials, tokens, private keys or machine-specific secrets.

## Security model

MLX Nobby is designed primarily as a local application.

Relevant safeguards include:

- loopback-only native service listeners
- localhost-only Docker port publishing
- Host validation
- same-origin request validation
- request body size limits
- upload size limits
- restricted service proxy routes
- validation of model references
- no arbitrary user-controlled backend proxy URLs

These protections are not a replacement for authentication if the services are exposed beyond localhost.

## Dependencies

Dependency installation has been verified in fresh virtual environments.

See `docs/DEPENDENCIES.md` for compatibility details and environment-specific requirements.

## Project status

MLX Nobby is under active development.

APIs, configuration and architecture may still change.

## License

MIT License

## MLX Manager

MLX Nobby includes the command-line manager in:

`scripts/mlx`

Install it locally with:

    mkdir -p ~/bin
    cp scripts/mlx ~/bin/mlx
    chmod +x ~/bin/mlx

Useful commands:

    mlx start
    mlx stop
    mlx restart
    mlx restart-all
    mlx status
    mlx services
    mlx agent status
    mlx agent restart
    mlx memory
    mlx serverargs
    mlx doctor

The manager uses `~/.config/mlx-server/config`,
`~/.config/mlx-server/models` and the native macOS LaunchAgents.
