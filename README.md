# MLX nobby

![Platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)
![MLX](https://img.shields.io/badge/MLX-native-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Release](https://img.shields.io/badge/release-v1.6.2-informational)


**MLX nobby** is an open-source local AI assistant and control center for Apple Silicon, built around Apple's MLX ecosystem. It brings local LLM chat, model management, RAG, coding workflows, image generation, speech transcription, and AI agents together in a single browser-based interface for macOS.

Run LLMs and AI services locally on your Mac with MLX and Metal acceleration while keeping models, conversations, documents, embeddings, and generated content under your control.

Native inference services run directly on macOS for efficient Apple Silicon acceleration. Only the web application runs in Docker, with a loopback-only local agent providing a controlled bridge between the container and host resources.

## Shorts backend

Shorts Studio offers a pre-production editor, saved drafts and History with
explicit job selection, retry and duplication. Chat creates a draft;
production starts only when you select Render Short. Autosave preserves changes
before navigation and rendering. Version-1 projects and existing scene revisions
remain supported, with retries reusing valid completed media.
See [Shorts API and production behavior](docs/SHORTS_STUDIO.md) for contracts,
voiceover timing and provider readiness. The web job queue shows media jobs,
and active Shorts jobs can be cancelled from History or the queue.

## Features

- Local [OpenAI-compatible inference API](docs/OPENAI_COMPATIBLE_API.md) for
  external clients, with virtual model roles, streaming and native tool-call
  transport, validated with real Cline 4.1.22 agent turns.

- Local LLM chat with streaming, model switching, thinking controls, and saved
  conversations
- Model aliases, Hugging Face downloads, cache inspection, and background jobs
- Coding workspaces with bounded file search, reviewable patches, and test runs
- Diagnostic, research, and file-processing agents using the central AgentRuntime
  with workspace-bound tools, permission checks, and approval/resume
- Role-based local model selection for chat, agent, coding, vision, image, and
  Qwen3 embeddings served through MLX-Serve
- Local embeddings, knowledge sources, and retrieval-augmented generation (RAG)
- Hierarchical semantic routing for chat, multimodal, research, coding, and
  creative requests
- Routing Observatory with original/final route, confidence, guard reason,
  regression feedback, and local diagnostics
- MLX-VLM routing for multimodal requests
- Speech-to-text through the native MLX Audio service
- Local text-to-speech with Serena voice and pause/resume playback in chat
- Qwen Image 2.1 generation through MLX-Serve, Qwen image editing, optional
  DiffusionKit/MFLUX/SDXL providers, and Real-ESRGAN upscaling
- Local LTX 2.5 text-to-video and image-to-video generation with preview,
  format selection, and model-aware media quality profiles
- Coordinated chat, image, and video runtimes with automatic resource handoff
- Asynchronous image jobs with real progress, cancellation, reload recovery,
  and persistent chat artifacts
- Iterative image editing that continues from the active image artifact
- Per-chat generation settings whose changes automatically become defaults for
  newly created chats
- System metrics, service health, logs, and runtime controls
- English and German chat UI with a persisted language setting

## Screenshots

### Start screen

![MLX nobby start screen](docs/screenshots/startscreen.png)

### Local AI chat

![MLX nobby chat interface](docs/screenshots/chat.png)

### Model management

![MLX nobby model management](docs/screenshots/models.png)

## Architecture

```mermaid
flowchart LR
    Browser[Browser] -->|localhost:8090| Web[Docker web app<br/>:8090]
    Web -->|host.docker.internal:8010| Agent[macOS agent<br/>:8010]
    Agent --> Runtime[MLX-LM runtime<br/>:8000]
    Agent --> Embeddings[Embedding service<br/>:8020]
    Embeddings --> MLXServe[MLX-Serve<br/>:11234]
    Agent --> Images[Image service<br/>:8030]
    Images --> MLXServe
    Agent --> Router[MLX-VLM router<br/>:8040]
    Agent --> Speech[Speech service<br/>:8050]
    Agent --> Video[Video service<br/>:8060]
```

| Port | Component | Runs in | Default exposure |
| ---: | --- | --- | --- |
| 8000 | MLX-LM runtime | macOS | `127.0.0.1` |
| 8010 | Host agent and API bridge | macOS | `127.0.0.1` |
| 8020 | Embedding service | macOS | `127.0.0.1` |
| 8030 | Image service | macOS | `127.0.0.1` |
| 8040 | MLX-VLM router | macOS | `127.0.0.1` |
| 8050 | Speech service | macOS | `127.0.0.1` |
| 8060 | Video service / LTX dispatch | macOS | `127.0.0.1` |
| 8090 | Web application | Docker | `127.0.0.1` |
| 11234 | MLX-Serve shared model endpoint | macOS | `127.0.0.1` |

MLX must remain native. Moving MLX into the Docker image would remove the
intended Apple Silicon runtime path.

Prompt writing, scripts and questions stay in chat, including with reference
images. Media jobs require explicit execution intent; attachments, adult terms
and classifier confidence cannot start them. Image chat prefers the configured
`vision_uncensored` role, falling back to `vision` when unavailable. The Routing
Observatory under **Settings → Tools** shows guarded preflight decisions and actual
chat/vision, agent and media actions in a local in-memory buffer. Prompts stay
redacted; only submitted feedback uses the existing local store. See [Routing Observatory](docs/ROUTING_OBSERVATORY.md) for the decision flow and
regression workflow.

Image chat allows 60 seconds before assistant output (text chat: 30 seconds)
and sends SSE heartbeats while waiting. Heartbeats keep the connection active
without extending recovery deadlines. The web process can override the vision
budget with `MLX_CHAT_VISION_FIRST_BYTE_TIMEOUT`; see
[Vision streaming reliability](docs/VISION_STREAMING_RELIABILITY.md).

## Requirements

- macOS on Apple Silicon (`arm64`)
- Python 3.13 and Python 3.11
- Docker with Docker Compose for the web application
- FFmpeg for speech input conversion
- Node.js when running the JavaScript checks
- Local model weights; the repository does not include models

Homebrew is optional, but is the simplest way to install the required Python
interpreters, Docker tooling, and FFmpeg.

## Quick start

Clone the repository and run the installer:

```sh
git clone https://github.com/nfekete82/mlx-nobby.git
cd mlx-nobby
./scripts/install.sh
```

After installation, open:

```text
http://127.0.0.1:8090
```

MLX nobby does not download an LLM automatically. Add or select a local
MLX-compatible model before starting your first chat.

The installer validates macOS and Apple Silicon, creates or updates the five
isolated service environments, links `~/bin/mlx` to the repository-managed
`scripts/mlx`, creates a minimal local runtime configuration if none exists,
and starts the Docker web application. The video dispatcher currently reuses
the isolated image environment rather than adding a sixth Python environment.
Existing MLX configuration and model aliases are preserved. LaunchAgent files
are installed only when the configured router model directory exists.

Useful installer variants are:

```sh
./scripts/install.sh --no-docker
./scripts/install.sh --no-launchd
./scripts/install.sh --no-python
./scripts/install.sh --no-launchd --no-docker
```

The last form is useful when you only want to install the manager and validate
an existing setup. `--no-python` expects compatible service environments to
already exist.

Add `~/bin` to `PATH` if the installer reports that it is missing:

```sh
export PATH="$HOME/bin:$PATH"
```

Set `MODEL` in `~/.config/mlx-server/config` to a local model path or an alias
defined in `~/.config/mlx-server/models`. The generated configuration starts
with an empty `MODEL`, port 8000, and thinking disabled so an incomplete first
install cannot silently select a model.

You can manage local models from the MLX nobby model interface or configure
aliases manually in:

    ~/.config/mlx-server/models

The router defaults to
`~/Models/router/Qwen3.5-4B-MLX-4bit`. To use another local router model,
install the LaunchAgents after setting its path:

```sh
MLX_ROUTER_MODEL_PATH=/absolute/path/to/router/model \
  ./scripts/install-launchd.sh
mlx restart-all
```

Then open <http://127.0.0.1:8090>. The web container reaches the native agent
through `host.docker.internal`; it does not contain the MLX runtimes.

## Help and feature documentation

Open Help from the chat sidebar for German/English instructions on images,
Shorts drafts/rendering, voice, workspace tasks, memory, automations, diagnostics
and local API integrations. Canonical technical references:

- [Workspace Agent Task Mode](docs/AGENT_TASK_MODE.md)
- [Memory](docs/MEMORY.md), [Memory Manager](docs/MEMORY_MANAGER.md) and
  [Context Inspector](docs/MEMORY_CONTEXT_INSPECTOR.md)
- [Automations and notifications](docs/AUTOMATIONS.md)
- [Image galleries](docs/IMAGE_GALLERY_VARIANTS.md) and
  [reference generation](docs/IMAGE_REFERENCE_GENERATION.md)
- [System Health](docs/SYSTEM_HEALTH.md),
  [Performance Observatory](docs/PERFORMANCE_OBSERVATORY.md) and
  [Routing Observatory](docs/ROUTING_OBSERVATORY.md)
- [OpenAI-compatible API / Cline](docs/OPENAI_COMPATIBLE_API.md)

## MLX manager

The maintained manager source is `scripts/mlx`; the installer creates
`~/bin/mlx` as a symbolic link to that repository file. This means future
`git pull` updates automatically apply to the `mlx` command without rerunning
the installer. Common commands include:

```sh
mlx status
mlx services
mlx doctor
mlx start
mlx stop
mlx restart
mlx restart-all
mlx reset
mlx models
mlx model <alias-or-huggingface-repository>
mlx model add <alias> <repository-or-local-path>
mlx download <alias-or-repository>
mlx cache
mlx thinking on
mlx thinking off
mlx chat
mlx ask "Your question"
```

For ordinary native-service recovery, use `mlx doctor`, `mlx status` and
`mlx restart-all`. `mlx restart` affects the LLM runtime only. `mlx restart-all`
retains a healthy Agent and does not rebuild/restart the Docker web application.
After pulling changed code, run the repository update helper:

```sh
./scripts/restart-all.sh
mlx doctor
```

That helper rebuilds the web frontend, reloads Agent code and checks service
revisions. It is different from a routine runtime restart.

Commands that download a Hugging Face repository require network access and
may require local Hugging Face authentication for gated models. Never put an
access token in the tracked model alias file.

## Service environments

The Python environments are intentionally separate. DiffusionKit requires a
legacy MLX combination that is incompatible with the current runtime stack.
Do not merge these requirements into one environment.

| Environment | Python | Requirements |
| --- | --- | --- |
| `agent-venv` | 3.13 | `requirements/agent.txt` |
| `runtime-venv` | 3.13 | `requirements/runtime.txt` |
| `embedding-venv` | 3.11 | `requirements/embeddings.txt` |
| `image-venv` | 3.11 | `requirements/images.txt` |
| `speech-venv` | 3.13 | `requirements/speech.txt` |

The video dispatcher on port 8060 runs from `image-venv`; it does not currently
have a separate requirements environment.

See [Dependency setup](docs/DEPENDENCIES.md) for manual installation,
constraints, tested versions, optional MFLUX setup, and offline import checks.

## Configuration

Copy `.env.example` to `.env` only when you need to override the Docker web
defaults:

```sh
cp .env.example .env
```

The web container uses `AGENT_URL`, `MLX_WEB_PORT`, and upload/host limits from
Compose. Native services do not automatically read this file. Their environment
variables and ownership are documented in `.env.example` and
`docs/DEPENDENCIES.md`.

Local configuration belongs in:

- `~/.config/mlx-server/config` for the runtime model and server settings
- `~/.config/mlx-server/models` for model aliases
- `~/.config/mlx-web/` for rendered service configuration and logs
- local ignored `.env` files for Docker overrides

Do not commit tokens, credentials, personal paths, model weights, local
databases, generated media, or configuration copied from your machine.

Generation parameters such as system prompt, preset, temperature, and maximum
token count belong to the active chat. Changes are persisted automatically as
defaults for newly created chats.

For frontend development, `./scripts/dev-web.sh` starts the Compose web
container with a read-only live mount of `frontend/`. Changes to those files
then appear without rebuilding the container.

## RAG and embeddings

Knowledge sources are indexed by the native agent through the embedding service
on port 8020. The API supports single and batched embeddings and keeps the
contract used by `agent/knowledge.py`. Source data, generated indexes, and local
knowledge directories are runtime data and are ignored by Git.

Embedding packages may contact Hugging Face when a referenced model is not
already cached. Use local model paths and the offline variables documented in
`docs/DEPENDENCIES.md` when network-free behavior is required.

## Images, video and speech

The image service supports the repository's DiffusionKit provider and an
optional, separately installed MFLUX CLI. An opt-in SDXL provider uses a local
checkpoint, and optional Real-ESRGAN presets upscale images. Image model
weights and generated outputs remain local. MFLUX and Real-ESRGAN are not
installed by the default installer.

Image generation and image editing use asynchronous jobs with explicit
`queued`, `loading`, `running`, `saving`, `completed`, `failed`, and
`cancelled` states.

The chat UI displays provider-reported progress without inventing intermediate
steps. Active jobs can be cancelled and are automatically resumed when the
browser is reloaded. The server remains the source of truth for recovered job
state.

Completed images are stored as chat artifacts. Qwen Image Edit supports
iterative editing from the active image artifact of the current session, so a
generated or edited image can be refined in subsequent prompts without
re-uploading it.

The native video dispatcher runs on port 8060 and coordinates local LTX 2.5
text-to-video and image-to-video work while reusing the isolated image Python
environment. Video jobs remain separate from the Docker web application.

Video profile `standard` is the default and uses no request LoRA. The optional
`uncensored` profile uses a local adapter configured exclusively on the server
with `LTX_MLX_UNCENSORED_LORA` and `LTX_MLX_UNCENSORED_LORA_STRENGTH` (default
`1.0`, finite number). Export these variables when running
`scripts/install-launchd.sh` to include them in the video LaunchAgent. Subsequent
installs preserve these values from `~/Library/LaunchAgents/de.nobby.mlx-video.plist`
unless explicitly overridden in the installer's environment. Export an empty
`LTX_MLX_UNCENSORED_LORA` to disable the adapter. Docker `.env` does not configure
native launchd services. The worker inherits the service environment.
The video model API reports optional profile availability using a lightweight
local file/readability check; it never loads or downloads adapters for this check.
Missing or invalid configuration rejects explicit Uncensored requests before
queueing or runtime acquisition, without automatic fallback. New video requests
start with Standard; the dialog disables Uncensored when it is not configured.
Both text-to-video and image-to-video use the existing LTX-MLX model and runtime.

The speech service uses `mlx-audio[stt,tts]` and FFmpeg. Uploaded audio is relayed
through the web application and host agent to the loopback-only speech service.
Chat messages can also be read aloud with the local Qwen3 TTS model and Serena
voice; playback can be paused and resumed.

See `IMAGE_RUNTIME.md` and `docs/DEPENDENCIES.md` for provider and runtime
details.

## Language settings

The chat interface defaults to English on a new browser profile. English and
German are selectable in Settings, and the choice is stored in browser local
storage. The `concise-de` preset deliberately instructs the model to answer in
German and is not an untranslated interface string.

Run the translation audit with:

```sh
git ls-files -z '*.py' | xargs -0 test-venv/bin/python -m py_compile
git ls-files -z '*.json' | xargs -0 -n1 python3 -m json.tool >/dev/null
python3 scripts/i18n-audit.py
```

## Privacy and network behavior

Model inference, saved chats, notes, knowledge indexes, generated images, and
service logs are designed to remain on the local machine. The services bind to
loopback by default and the web port is published on localhost.

MLX nobby is not completely offline by default:

- Model download and cache actions can contact Hugging Face.
- The local text-to-speech model can also download weights on first use.
- Research actions can query the configured SearXNG instance and fetch selected
  external pages.
- The current web pages load Tailwind CSS, Marked, DOMPurify, and Highlight.js
  assets from public CDNs.
- Docker builds and Python package installation contact their configured
  registries.

If those connections are unacceptable, place models and packages in local
caches, configure research accordingly, and vendor or block the CDN assets
before use. Review browser developer tools or network controls for the exact
behavior of your deployment.

## Security

The supplied configuration is intended for a trusted, single-user machine.
Native services and the Docker port are loopback-bound; request sizes, hosts,
origins, model references, and proxy routes are validated. Coding and knowledge
features can access explicitly configured local workspaces.

There is no authentication layer suitable for public exposure. Do not bind the
services to a LAN or the internet without adding authentication, TLS, and network
isolation. See [SECURITY.md](SECURITY.md) for reporting and operating guidance.

## Development and tests

See [Testing](docs/TESTING.md) for deterministic Chromium acceptance via
`./scripts/mlx test-e2e`, setup and failure artifacts.

See [the performance audit](docs/PERFORMANCE_AUDIT.md) for measured hotspots,
regressions, and reproducible text/vision benchmarks with
`scripts/benchmark-chat.py`.

Install the CPU-only test environment and run the local checks:

```sh
python3.13 -m venv test-venv
test-venv/bin/python -m pip install -r requirements/test.txt
test-venv/bin/python -m pytest -q
python3 scripts/i18n-audit.py
find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
for test in tests/*.mjs; do node "$test" || exit 1; done
bash -n scripts/install.sh scripts/install-launchd.sh scripts/doctor.sh \
  scripts/mlx scripts/mlx-server-start
docker compose config
git diff --check
```

The test manifest contains no MLX packages and downloads no models. Native MLX
imports require Apple Silicon and Metal and are documented separately.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md). Keep changes focused, preserve
the native-service boundary, add tests for behavior changes, and exclude local
runtime data from pull requests.

## Project status

MLX nobby is under active development. Configuration and APIs may change, and
the image stack includes a deliberately isolated legacy dependency. The project
has not been presented here as production-ready or independently security
audited.

## License

Released under the [MIT License](LICENSE).
