# Dependencies and service environments

MLX runs natively on macOS and Apple Silicon. Only the web application runs in
Docker. The macOS agent remains the bridge to host resources, and the runtime is
managed through `~/bin/mlx` and `~/.config/mlx-server/config`. The maintained
copy of the manager is `scripts/mlx`.

## Isolated environments and Python versions

Each service has its own virtual environment. In particular, current MLX runtime
packages and the legacy DiffusionKit image provider require incompatible MLX
versions. Do not install these manifests into one environment.

| Environment | Manifest | Recommended and freshly tested Python |
| --- | --- | --- |
| `agent-venv` | `requirements/agent.txt` | 3.13.15 |
| `runtime-venv` | `requirements/runtime.txt` | 3.13.15 |
| `embedding-venv` | `requirements/embeddings.txt` | 3.11.15 |
| `image-venv` | `requirements/images.txt` | 3.11.15 |
| `speech-venv` | `requirements/speech.txt` | 3.13.15 |
| `test-venv` | `requirements/test.txt` | 3.13.15 |
| Web container | `requirements/web.txt` | 3.13 (`python:3.13-slim`) |
| Optional MFLUX environment | `requirements/mflux.txt` | 3.13.15 |

As of 2026-09-10, all manifests were installed from public PyPI into empty
environments on Apple Silicon (`arm64`), macOS 26.6.2, with Python 3.11.15 or
3.13.15 as shown. These are tested combinations, not a claim that no other
Python or macOS version works. Native MLX imports require Metal access and can
fail inside a restricted sandbox even when dependency resolution is correct.
MLX 0.32.2 publishes macOS wheels for macOS 14 and later; the complete stack was
tested only on the system listed above.

## Requirements and constraints

The service manifests list direct application dependencies. Embeddings, images,
and speech include a corresponding file under `requirements/constraints/`.
Pip resolves those relative paths from the requirements file.

| Constraint set | Reason |
| --- | --- |
| Embeddings: `mlx-vlm==0.7.0`, `transformers==5.17.0` | `mlx-embeddings` imports `mlx_vlm.utils` and current tokenizer/processor APIs. |
| Speech: `mlx==0.32.2`, `transformers==5.16.1` | Tested inference and tokenizer APIs for `mlx-audio==0.5.1`. |
| Images: `mlx==0.17.3`, `torch==2.14.0`, `transformers==5.16.1` | Tested import combination for the isolated DiffusionKit provider. |

Incidental HTTP, NumPy, SciPy, and utility packages are not copied from an
existing machine into the manifests. They are installed only when an upstream
package declares them. A constraint limits a version but does not install the
package by itself.

These manifests reproduce the tested direct and compatibility versions. They
are not hash-locked snapshots of every transitive package, so future resolver
output can still vary when upstream packages publish new compatible releases.

### Embeddings

`mlx-embeddings==0.1.0` is the maintained package used here. Its published wheel
imports `RepositoryNotFoundError` from the public `huggingface_hub.errors`
module and still exports `mlx_embeddings.utils.load` and `generate`.
`mlx-embeddings==0.0.1` used the removed private
`huggingface_hub.utils._errors` module and is not part of this installation.
No Hugging Face Hub downgrade or import shim is required.

The final fresh installation resolved Hugging Face Hub 1.31.0 and NumPy 2.4.6.
Library and FastAPI application imports passed. Contract tests covered
`/health`, `/embedding`, and `/embeddings` with mocked vectors and confirmed
the `model`, `dimensions` (1024), and `vectors` fields expected by
`agent/knowledge.py`. No model inference was performed.

`mlx-vlm` brings additional audio and vision packages transitively. They are
not listed as direct project dependencies because the application does not
import them directly.

### Speech

`requirements/speech.txt` installs `mlx-audio[stt]==0.5.1`. The package
metadata for the STT extra declares `sentencepiece>=0.2.0` and
`zstandard>=0.23.0`. The fresh install contained both (0.2.2 and 0.25.0), so no
manual duplicate entries are needed. The tested Python 3.13 resolver selected
NumPy 2.5.3 and SciPy 1.18.1, whose package metadata requires Python 3.12 or
later. Python 3.13 is therefore the tested recommendation.

### Images and optional MFLUX

`requirements/images.txt` contains DiffusionKit 0.5.1. Its metadata brings in
`argmaxtools`, Torch, MLX, Transformers, and conversion-related packages. A
fresh environment successfully imported `diffusionkit.mlx.FluxPipeline`.

Core ML Tools warned that Torch 2.14.0 had not been tested upstream and disabled
its scikit-learn conversion support with scikit-learn 1.9.0. The application
uses the MLX pipeline rather than those conversion paths. DiffusionKit remains a
fragile legacy provider and is isolated for that reason.

The optional standalone CLI is `mflux==0.19.1`. It is installed separately
because the image adapter invokes its console commands. All five commands used
by the repository were present and accepted the adapter's arguments. Package
installation and help checks downloaded no model weights.

## Installation

The public installer performs these steps automatically:

```sh
./scripts/install.sh
```

For manual setup, run the following commands from the repository root. Reuse an
existing environment only when it has the documented Python minor version.

```sh
python3.13 -m venv agent-venv
agent-venv/bin/python -m pip install -r requirements/agent.txt

python3.13 -m venv runtime-venv
runtime-venv/bin/python -m pip install -r requirements/runtime.txt

python3.11 -m venv embedding-venv
embedding-venv/bin/python -m pip install -r requirements/embeddings.txt

python3.11 -m venv image-venv
image-venv/bin/python -m pip install -r requirements/images.txt

python3.13 -m venv speech-venv
speech-venv/bin/python -m pip install -r requirements/speech.txt

python3.13 -m venv test-venv
test-venv/bin/python -m pip install -r requirements/test.txt
```

The native service commands and working directories are defined in
`launchd/templates/`. `scripts/install-launchd.sh` renders them for the
current checkout. All five service environments and the local router model must
exist first. Existing generated plist files are not tracked.

The runtime configuration lives at `~/.config/mlx-server/config`. The installer
creates this safe starting point only when the file does not already exist:

```sh
MODEL=""
PORT=8000
THINKING=false
```

Set `MODEL` to a local model path or configured alias before starting the MLX
runtime. Speech also requires FFmpeg. Set `FFMPEG_PATH` if it is not available
on `PATH`.

Build and start the web application only through Compose:

```sh
docker compose up -d --build
```

For optional MFLUX support:

```sh
python3.13 -m venv mflux-venv
mflux-venv/bin/python -m pip install -r requirements/mflux.txt
```

Set `MLX_IMAGE_MFLUX_BIN` in the image service's host environment to the
absolute `mflux-venv/bin` path. The image service otherwise looks under
`~/.local/bin`. MFLUX is not part of the default installer.

## Import and consistency checks

After installation, the central imports can be checked without downloading
models. Run these from the repository root with native Metal access:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 embedding-venv/bin/python -c 'from mlx_embeddings.utils import load, generate; import embedding_service'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 speech-venv/bin/python -c 'from mlx_audio.stt import load; import sentencepiece, zstandard; import speech.app'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 image-venv/bin/python -c 'from diffusionkit.mlx import FluxPipeline; import image_service'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 runtime-venv/bin/python -c 'import mlx.core, mlx_lm, mlx_vlm'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 mflux-venv/bin/mflux-generate --help
```

Run `<venv>/bin/python -m pip check` in each environment afterward. These
commands do not start service lifespans or perform inference. The fresh
dependency audit passed all library/application imports, all environment
`pip check` runs, MFLUX CLI parser checks, and the relevant unit tests. Actual
model inference and production service operation were outside that audit.

## Environment configuration

`.env.example` documents current variables. Compose reads a local `.env` for
substitution, but only values named in `docker-compose.yml` enter the
container. Native services and LaunchAgents do not automatically load this
file.

| Variable | Consumer and purpose |
| --- | --- |
| `AGENT_URL` | Web container agent address; defaults to `http://host.docker.internal:8010`. |
| `MLX_WEB_PORT` | Local Compose port; defaults to 8090. |
| `MAX_UPLOAD_SIZE_MB` | Web and native upload limit; set separately for native services. |
| `MLX_ALLOWED_HOSTS` | Host validation; Compose allows localhost values, native defaults also allow `host.docker.internal`. |
| `SPEECH_SERVICE_URL` | Agent speech service; defaults to `http://127.0.0.1:8050`. |
| `IMAGE_SERVICE_URL` | Agent image service; defaults to `http://127.0.0.1:8030`. |
| `MLX_ROUTER_MODEL_PATH` | Agent and LaunchAgent installer local router model path. |
| `MLX_EMBEDDING_MODEL_PATH` | Embedding service local model path; supports `~`. |
| `MLX_EMBEDDING_MAX_LENGTH` | Embedding length from 1 to 8192; default 8192. |
| `MLX_EMBEDDING_BATCH_SIZE` | Embedding batch size from 1 to 128; default 8. |
| `FFMPEG_PATH` | Explicit FFmpeg executable; otherwise PATH and Homebrew locations are checked. |
| `MLX_IMAGE_MFLUX_BIN` | Optional directory containing the MFLUX CLI commands. |

The old web variables `MLX_URL`, `SPEECH_URL`, and `IMAGE_URL` are no longer
read by the web backend. MLX and speech requests cross `AGENT_URL`; the agent
gets the native MLX port from `~/.config/mlx-server/config`. Speech and image
targets use the host variables listed above.
