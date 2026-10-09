"""Fixed provider adapters with isolated native model processes."""
import importlib.util
import json
import math
import os
import re
import secrets
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import runtime_coordinator
from image_registry import FAMILIES, MODEL_ROOTS, validate_path
from mflux_capabilities import probe_mflux_cli, mflux_contract, mflux_weight_contract

MFLUX_BIN = Path(os.environ.get("MLX_IMAGE_MFLUX_BIN", str(Path.home() / ".local/bin")))
MLXGEN_BIN = Path(os.environ.get("MLX_IMAGE_MLXGEN_BIN", str(Path.home() / ".local/share/mlx-gen-venv/bin/mlxgen")))

MLXSERVE_URL = os.environ.get(
    "MLX_IMAGE_MLXSERVE_URL",
    "http://" + "127.0.0.1:11234",
).rstrip("/")
MLXSERVE_HEALTH_TIMEOUT = 3

REALESRGAN_BIN = Path(
    os.environ.get(
        "MLX_IMAGE_REALESRGAN_BIN",
        str(Path.home() / ".local/bin/realesrgan-ncnn-vulkan"),
    )
)

REALESRGAN_MODELS = Path(
    os.environ.get(
        "MLX_IMAGE_REALESRGAN_MODELS",
        str(Path.home() / ".local/share/realesrgan/models"),
    )
)

REALESRGAN_PRESETS = {
    "photo-2x": {
        "model": "realesrgan-x4plus",
        "scale": 2,
    },
    "photo-4x": {
        "model": "realesrgan-x4plus",
        "scale": 4,
    },
    "anime-4x": {
        "model": "realesrgan-x4plus-anime",
        "scale": 4,
    },
}

MFLUX_PERFORMANCE_HEADROOM_GB = 16.0
MFLUX_BALANCED_HEADROOM_GB = 8.0
MFLUX_PERFORMANCE_CACHE_GB = 8
MFLUX_BALANCED_CACHE_GB = 4
MFLUX_LOW_RAM_CACHE_GB = 2
QUALITY_UPSCALE_PRESET = "photo-2x"


def _float_env(name, default):
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _int_env(name, default, *, minimum=1, maximum=32):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)
    return max(minimum, min(maximum, value))


def mflux_memory_policy(snapshot=None):
    """Resolve a conservative MFLUX memory/cache policy for Apple unified RAM.

    ``auto`` keeps low-RAM mode for constrained/unknown conditions, but lets
    higher-memory Macs use a larger MLX cache and the normal execution path
    when there is enough reclaimable headroom. Explicit modes are available
    for benchmarking and troubleshooting.
    """
    mode = str(os.environ.get("MLX_IMAGE_MFLUX_MODE", "auto")).strip().lower()
    aliases = {
        "high": "performance",
        "fast": "performance",
        "normal": "balanced",
        "safe": "low-ram",
        "low": "low-ram",
        "low_ram": "low-ram",
    }
    mode = aliases.get(mode, mode)
    if mode not in {"auto", "performance", "balanced", "low-ram"}:
        mode = "auto"

    performance_cache = _int_env(
        "MLX_IMAGE_MFLUX_PERFORMANCE_CACHE_GB",
        MFLUX_PERFORMANCE_CACHE_GB,
    )
    balanced_cache = _int_env(
        "MLX_IMAGE_MFLUX_BALANCED_CACHE_GB",
        MFLUX_BALANCED_CACHE_GB,
    )
    low_cache = _int_env(
        "MLX_IMAGE_MFLUX_LOW_RAM_CACHE_GB",
        MFLUX_LOW_RAM_CACHE_GB,
    )

    if mode == "performance":
        return {
            "mode": "performance",
            "low_ram": False,
            "cache_gb": performance_cache,
            "snapshot": snapshot,
        }
    if mode == "balanced":
        return {
            "mode": "balanced",
            "low_ram": True,
            "cache_gb": balanced_cache,
            "snapshot": snapshot,
        }
    if mode == "low-ram":
        return {
            "mode": "low-ram",
            "low_ram": True,
            "cache_gb": low_cache,
            "snapshot": snapshot,
        }

    if snapshot is None:
        try:
            snapshot = runtime_coordinator.memory_budget_snapshot()
        except Exception:
            snapshot = {}

    pressure = str((snapshot or {}).get("pressure") or "unknown").lower()
    headroom = (snapshot or {}).get("headroom_gb")
    performance_headroom = max(
        1.0,
        _float_env(
            "MLX_IMAGE_MFLUX_PERFORMANCE_HEADROOM_GB",
            MFLUX_PERFORMANCE_HEADROOM_GB,
        ),
    )
    balanced_headroom = max(
        1.0,
        _float_env(
            "MLX_IMAGE_MFLUX_BALANCED_HEADROOM_GB",
            MFLUX_BALANCED_HEADROOM_GB,
        ),
    )

    if pressure in {"elevated", "critical"}:
        resolved_mode = "low-ram"
    elif isinstance(headroom, (int, float)) and not isinstance(headroom, bool):
        if float(headroom) >= performance_headroom:
            resolved_mode = "performance"
        elif float(headroom) >= balanced_headroom:
            resolved_mode = "balanced"
        else:
            resolved_mode = "low-ram"
    else:
        resolved_mode = "balanced"

    return {
        "mode": resolved_mode,
        "low_ram": resolved_mode != "performance",
        "cache_gb": {
            "performance": performance_cache,
            "balanced": balanced_cache,
            "low-ram": low_cache,
        }[resolved_mode],
        "snapshot": snapshot,
    }


def realesrgan_command(
    source,
    output,
    *,
    preset="photo-2x",
    tile=0,
):
    try:
        config = REALESRGAN_PRESETS[preset]
    except KeyError as exc:
        raise ValueError(
            f"Unbekanntes Real-ESRGAN-Preset: {preset}"
        ) from exc

    source = Path(source)
    output = Path(output)

    if not REALESRGAN_BIN.is_file():
        raise RuntimeError(
            "Real-ESRGAN-Binary ist nicht installiert"
        )

    if not os.access(REALESRGAN_BIN, os.X_OK):
        raise RuntimeError(
            "Real-ESRGAN-Binary ist nicht ausführbar"
        )

    model_name = config["model"]

    for suffix in (".param", ".bin"):
        model_file = (
            REALESRGAN_MODELS
            / f"{model_name}{suffix}"
        )
        if not model_file.is_file():
            raise RuntimeError(
                f"Real-ESRGAN-Modell fehlt: {model_file.name}"
            )

    if tile < 0:
        raise ValueError(
            "Real-ESRGAN tile muss 0 oder größer sein"
        )

    return [
        str(REALESRGAN_BIN),
        "-i",
        str(source),
        "-o",
        str(output),
        "-m",
        str(REALESRGAN_MODELS),
        "-n",
        model_name,
        "-s",
        str(config["scale"]),
        "-t",
        str(tile),
        "-f",
        "png",
        "-v",
    ]


def quality_upscale_mode():
    """Return ``off``, ``auto`` or ``required`` for Quality+ post-processing."""
    value = str(os.environ.get("MLX_IMAGE_QUALITY_UPSCALE", "auto")).strip().lower()
    aliases = {
        "0": "off",
        "false": "off",
        "no": "off",
        "1": "auto",
        "true": "auto",
        "on": "auto",
        "force": "required",
    }
    value = aliases.get(value, value)
    return value if value in {"off", "auto", "required"} else "auto"


def quality_upscale_available(preset=QUALITY_UPSCALE_PRESET):
    """Check whether the local Real-ESRGAN Quality+ runtime is complete."""
    try:
        realesrgan_command(
            Path("quality-probe-input.png"),
            Path("quality-probe-output.png"),
            preset=preset,
        )
    except (OSError, RuntimeError, ValueError):
        return False
    return True

GENERATION_TIMEOUT = 840
MAX_PROCESS_RSS_GB = 24
PROCESS_TERMINATION_TIMEOUT = 5
PROVIDER_POLL_INTERVAL = 0.5
DEFAULT_SDXL_IDLE_TIMEOUT = 600.0


class ProviderCancelled(RuntimeError):
    """Raised when a caller cancels an active provider process."""


class ProviderFailure(RuntimeError):
    def __init__(self, message, *, error_code='IMAGE_PROVIDER_FAILED', provider=None, model=None, detail=None):
        super().__init__(message)
        self.diagnosis = {'error_code': error_code, 'error_provider': provider,
                          'error_model': model, 'error_detail_safe': detail or message}


def _read_runtime_events(stream, remainder, callback, expected_steps):
    chunk = stream.read()

    if not chunk and not remainder:
        return remainder

    text = remainder + (
        chunk.decode("utf-8", errors="replace")
        if chunk
        else ""
    )
    lines = re.split(r"[\r\n]", text)
    remainder = lines.pop()

    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue

        if event.get("type") != "runtime":
            continue

        step = event.get("step")
        total_steps = event.get("total_steps")

        if not isinstance(step, int) or not isinstance(total_steps, int):
            step = None
            total_steps = None
        elif (
            step < 0
            or total_steps <= 0
            or step > total_steps
            or (
                expected_steps is not None
                and total_steps != expected_steps
            )
        ):
            step = None
            total_steps = None

        callback({
            "phase": str(event.get("phase") or ""),
            "step": step,
            "total_steps": total_steps,
        })

    return remainder[-65536:]


def model_directory(model):
    if model.get("local_path"):
        return Path(validate_path(model["local_path"]))
    cache = repository_cache(model["repository"])
    ref = cache / "refs/main"
    if ref.is_file():
        revision = ref.read_text().strip()
        if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
            return cache / "snapshots" / revision
    return None


def repository_cache(repository):
    """Map an HF repository reference to its local cache without resolving it."""
    repo = str(repository or "").split(":", 1)[0]
    return MODEL_ROOTS[1] / ("models--" + repo.replace("/", "--"))


def repository_is_available(repository):
    """Check an optional LoRA repository in offline mode, without downloading."""
    repo, separator, filename = str(repository or "").partition(":")
    cache = repository_cache(repo)
    ref = cache / "refs/main"
    if not ref.is_file():
        return False
    revision = ref.read_text(encoding="utf-8").strip()
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        return False
    root = cache / "snapshots" / revision
    if not root.is_dir():
        return False
    if separator and filename:
        return (root / filename).is_file()
    return any(root.rglob("*.safetensors"))


def resolve_lora_file(lora):
    """Resolve one configured LoRA to an absolute local .safetensors path."""

    local_path = lora.get("path")
    if local_path:
        candidate = Path(validate_path(local_path, file=True))
        if not candidate.is_file():
            raise RuntimeError("Eine aktivierte lokale LoRA-Datei fehlt")
        return candidate

    repository = str(lora.get("repository") or "")
    repo, separator, filename = repository.partition(":")
    if not repo:
        raise ValueError("LoRA benötigt einen lokalen Pfad oder ein Repository")

    cache = repository_cache(repo)
    ref = cache / "refs/main"
    if not ref.is_file():
        raise RuntimeError(
            "Eine aktivierte LoRA ist nicht im lokalen Hugging-Face-Cache vorhanden"
        )

    revision = ref.read_text(encoding="utf-8").strip()
    if (
        len(revision) != 40
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise RuntimeError("Ungültiger Hugging-Face-Cache für eine aktivierte LoRA")

    root = cache / "snapshots" / revision
    if not root.is_dir():
        raise RuntimeError("Lokaler Hugging-Face-Snapshot einer LoRA fehlt")

    if separator and filename:
        candidate = root / filename
        if not candidate.is_file():
            raise RuntimeError(
                "Die konfigurierte LoRA-Datei fehlt im lokalen Hugging-Face-Cache"
            )
        return candidate

    candidates = sorted(root.rglob("*.safetensors"))
    if len(candidates) != 1:
        raise RuntimeError(
            "LoRA-Repository muss genau eine .safetensors-Datei enthalten "
            "oder als org/model:datei.safetensors angegeben werden"
        )

    return candidates[0]


def _mlxserve_json(path, *, timeout=MLXSERVE_HEALTH_TIMEOUT):
    request = urllib.request.Request(
        MLXSERVE_URL + path,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(
                f"MLX-Serve antwortete mit HTTP {response.status}"
            )
        return json.loads(response.read().decode("utf-8"))


def availability(model):
    if model["provider"] == "mlxgen":
        root = model_directory(model)
        if not root or not root.is_dir() or not (root / "text_encoder").is_dir() or not (root / "transformer").is_dir() or not (root / "vae").is_dir():
            return False, "MLX-Gen: lokaler Qwen-Image-Edit-Cache fehlt oder ist unvollständig"
        if not any(root.rglob("*.safetensors")):
            return False, "MLX-Gen: lokale Modellgewichte fehlen"
        if not MLXGEN_BIN.is_file() or not os.access(MLXGEN_BIN, os.X_OK):
            return False, "MLX-Gen fehlt: bitte die isolierte MLX-Gen-Umgebung installieren"
        return True, "Lokaler MLX-Gen-Runner und Qwen-Image-Edit-Gewichte vorhanden (Ladefähigkeit erst beim Render geprüft)"
    if model["provider"] == "mlxserve":
        try:
            health = _mlxserve_json("/health")
            if health.get("status") != "ok":
                return False, "MLX-Serve meldet keinen betriebsbereiten Status"

            payload = _mlxserve_json("/v1/models")
            models = payload.get("data", [])
            model_id = model.get("repository")

            if not any(
                isinstance(item, dict)
                and item.get("id") == model_id
                for item in models
            ):
                return (
                    False,
                    "Qwen Image 2.1 ist in MLX-Serve nicht verfügbar",
                )

            for lora in model.get("loras", []):
                if not lora.get("enabled"):
                    continue
                try:
                    resolve_lora_file(lora)
                except (RuntimeError, ValueError) as exc:
                    return False, str(exc)
        except (
            OSError,
            TimeoutError,
            ValueError,
            urllib.error.URLError,
            urllib.error.HTTPError,
        ):
            return (
                False,
                f"MLX-Serve ist unter {MLXSERVE_URL} nicht erreichbar",
            )

        return True, "Qwen Image 2.1 ist über den lokalen MLX-Serve verfügbar"

    if model["provider"] == "sdxl":
        if not importlib.util.find_spec("diffusers"):
            return False, "Diffusers ist in der Image-Umgebung nicht installiert"
        if not importlib.util.find_spec("torch"):
            return False, "PyTorch ist in der Image-Umgebung nicht installiert"
        try:
            sdxl_files(model)
        except (RuntimeError, ValueError) as exc:
            return False, str(exc)
        return True, "Lokaler SDXL-Checkpoint und lokale Runtime-Konfiguration vorhanden"
    if model["provider"] == "mflux":
        command = MFLUX_BIN / FAMILIES[model["model_family"]][0]
        if not command.is_file() or not os.access(command, os.X_OK):
            return False, "MFLUX-CLI nicht installiert"
    root = model_directory(model)
    if not root or not root.is_dir() or not any(root.rglob("*.safetensors")):
        return False, "Lokale Modellgewichte fehlen; keine automatischen Downloads"
    for index in root.rglob("*.safetensors.index.json"):
        try:
            shards = set(json.loads(index.read_text())["weight_map"].values())
            if any(not (index.parent / name).is_file() for name in shards):
                return False, "Modellcache unvollständig: Gewichts-Shards fehlen"
        except (ValueError, KeyError):
            return False, "Ungültiger Gewichtsindex"
    for lora in model["loras"]:
        if not lora["enabled"]:
            continue
        if lora.get("path") and not Path(validate_path(lora["path"], file=True)).is_file():
            return False, "Eine aktivierte lokale LoRA-Datei fehlt"
        if lora.get("repository") and not repository_is_available(lora["repository"]):
            return False, "Eine aktivierte LoRA ist nicht im lokalen Hugging-Face-Cache vorhanden"
    if model['provider'] == 'mflux':
        compatible, reason = mflux_weight_contract(model, root)
        if not compatible:
            return False, reason
        return mflux_contract(model, command)
    return True, "Lokale Gewichte vorhanden"


def sdxl_files(model):
    """Resolve one local SDXL checkpoint and its offline Diffusers config."""
    root = model_directory(model)
    if not root:
        raise RuntimeError("Lokaler SDXL-Modellpfad fehlt")
    if root.is_file():
        checkpoints = [root] if root.suffix.lower() == ".safetensors" else []
        directory = root.parent
    else:
        directory = root
        checkpoints = sorted(directory.glob("*.safetensors")) if directory.is_dir() else []
    if len(checkpoints) != 1:
        raise RuntimeError("SDXL benötigt genau einen lokalen .safetensors-Checkpoint")
    config = directory / "config"
    if not (config / "model_index.json").is_file():
        raise RuntimeError("Lokale SDXL-Diffusers-Konfiguration fehlt unter config/model_index.json")
    validate_path(str(checkpoints[0]))
    validate_path(str(config))
    return checkpoints[0], config


def mflux_command(model, params, output):
    family = model["model_family"]
    executable = MFLUX_BIN / FAMILIES[family][0]
    ready, reason = mflux_contract(model, executable)
    if not ready:
        raise ProviderFailure(reason, error_code='IMAGE_PROVIDER_INCOMPATIBLE', provider='mflux', model=model.get('id'))
    flags = probe_mflux_cli(str(executable))['supported_flags']

    # Source aspect is already resolved by the service into width/height.
    # Qwen Edit 0.19.1/0.20.0 have no --canvas-policy; quantize only on request.
    if family == "qwen-image-edit":
        source_path = params.get("source_path")

        if not source_path:
            raise RuntimeError(
                "Für Bildbearbeitung fehlt das Quellbild"
            )

        command = [
            str(MFLUX_BIN / FAMILIES[family][0]),
            "--model",
            str(model_directory(model)),
            "--image-paths",
            source_path,
            "--prompt",
            params["prompt"],
            "--width",
            str(params["width"]),
            "--height",
            str(params["height"]),
            "--steps",
            str(params["steps"]),
            "--guidance",
            str(params["guidance"]),
            "--seed",
            str(params["seed"]),
            "--output",
            str(output),
        ]

        quantization = model.get("quantization")
        if (
            model.get("quantize_on_load") is True
            and quantization
            and quantization != "none"
        ):
            command += [
                "--quantize",
                quantization[1:],
            ]

        loras = [
            lora
            for lora in model["loras"]
            if lora["enabled"]
        ]

        if loras:
            command += (
                ["--lora-paths"]
                + [
                    lora.get("path")
                    or lora["repository"]
                    for lora in loras
                ]
            )

            command += (
                ["--lora-scales"]
                + [
                    str(lora["scale"])
                    for lora in loras
                ]
            )

        return command

    memory_policy = mflux_memory_policy()
    command = [
        str(MFLUX_BIN / FAMILIES[family][0]),
        "--model",
        str(model_directory(model)),
    ]

    if family not in {"qwen-image21", "boogu"}:
        command += [
            "--base-model",
            model["base_model"],
        ]

    command += [
        "--prompt=" + params["prompt"],
        "--width",
        str(params["width"]),
        "--height",
        str(params["height"]),
        "--steps",
        str(params["steps"]),
        "--seed",
        str(params["seed"]),
        "--output",
        str(output),
    ]

    if '--mlx-cache-limit-gb' in flags:
        command += ['--mlx-cache-limit-gb', str(memory_policy['cache_gb'])]
    if memory_policy["low_ram"] and '--low-ram' in flags:
        command.append("--low-ram")

    if family not in {"z-image-turbo", "boogu"}:
        command += [
            "--guidance",
            str(params["guidance"]),
        ]

    if model["quantization"] != "none":
        command += [
            "--quantize",
            model["quantization"][1:],
        ]

    loras = [
        lora
        for lora in model["loras"]
        if lora["enabled"]
    ]

    if loras:
        command += (
            ["--lora-paths"]
            + [
                lora.get("path")
                or lora["repository"]
                for lora in loras
            ]
        )

        command += (
            ["--lora-scales"]
            + [
                str(lora["scale"])
                for lora in loras
            ]
        )

    return command


def terminate_process_tree(process):
    """Stop a provider process group without waiting indefinitely."""
    if process.poll() is not None:
        return

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Image-Modellprozess konnte nach Abbruch nicht beendet werden"
        ) from exc


def _configured_sdxl_idle_timeout():
    try:
        timeout = float(os.environ.get(
            "MLX_IMAGE_SDXL_IDLE_TIMEOUT",
            DEFAULT_SDXL_IDLE_TIMEOUT,
        ))
    except (TypeError, ValueError):
        return DEFAULT_SDXL_IDLE_TIMEOUT
    return (
        timeout
        if math.isfinite(timeout) and timeout > 0
        else DEFAULT_SDXL_IDLE_TIMEOUT
    )


class SDXLWorkerManager:
    """Own one serialized, restartable SDXL worker with idle shutdown."""

    def __init__(self, *, worker_path=None, idle_timeout=None, monitor_rss=True):
        self.worker_path = Path(worker_path or Path(__file__).with_name("sdxl_worker.py"))
        self.idle_timeout = (
            _configured_sdxl_idle_timeout()
            if idle_timeout is None
            else float(idle_timeout)
        )
        self.monitor_rss = monitor_rss
        self._lock = threading.Lock()
        self._process = None
        self._diagnostics = None
        self._idle_timer = None
        self._idle_generation = 0

    def _cancel_idle_timer_locked(self):
        self._idle_generation += 1
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _stop_locked(self):
        self._cancel_idle_timer_locked()
        process = self._process
        diagnostics = self._diagnostics

        if process is not None:
            try:
                terminate_process_tree(process)
            except Exception as exc:
                raise RuntimeError(
                    "SDXL worker could not be terminated"
                ) from exc

            self._process = None
            self._diagnostics = None

            for stream in (process.stdin, process.stdout):
                if stream is None:
                    continue
                try:
                    stream.close()
                except Exception:
                    pass
        else:
            self._process = None
            self._diagnostics = None

        if diagnostics is not None:
            try:
                diagnostics.close()
            except Exception:
                pass

    def _start_locked(self, environment):
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._stop_locked()
        diagnostics = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen(
                [sys.executable, str(self.worker_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=diagnostics,
                bufsize=0,
                env=environment,
                shell=False,
                start_new_session=True,
            )
        except Exception:
            diagnostics.close()
            raise
        self._process = process
        self._diagnostics = diagnostics
        return process

    def _schedule_idle_shutdown_locked(self):
        self._cancel_idle_timer_locked()
        generation = self._idle_generation

        def shutdown_if_idle():
            with self._lock:
                if generation == self._idle_generation:
                    self._stop_locked()

        timer = threading.Timer(self.idle_timeout, shutdown_if_idle)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _failure_message_locked(self, process):
        diagnostics = self._diagnostics
        if diagnostics is not None:
            diagnostics.flush()
            diagnostics.seek(0, 2)
            diagnostics.seek(max(0, diagnostics.tell() - 65536))
            message = diagnostics.read().decode("utf-8", errors="replace").lower()
            if "all zero" in message or "weights appear corrupt" in message:
                return "Lokale Modellgewichte sind beschädigt (Nullgewichte). Es wurden keine Dateien verändert oder heruntergeladen."
        return f"sdxl konnte den lokalen Worker nicht ausführen (Exit {process.poll()}). Cache und Provider-Kompatibilität prüfen; es wurde nichts heruntergeladen."

    def generate(
        self,
        checkpoint,
        config,
        params,
        output,
        *,
        environment,
        cancel_event=None,
        process_callback=None,
        progress_callback=None,
    ):
        with self._lock:
            self._cancel_idle_timer_locked()
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderCancelled("Image job was cancelled")
            process = self._start_locked(environment)
            request_id = secrets.token_hex(16)
            request = {
                "request_id": request_id,
                "checkpoint": str(checkpoint),
                "config": str(config),
                "params": params,
                "output": str(output),
            }
            succeeded = False
            if process_callback is not None:
                process_callback(process)
            try:
                try:
                    process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    raise RuntimeError(self._failure_message_locked(process)) from exc

                deadline = time.monotonic() + GENERATION_TIMEOUT
                response_buffer = b""
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise ProviderCancelled("Image job was cancelled")
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Image-Auftrag hat das Zeitlimit überschritten; Modellprozess wurde beendet")
                        if process.poll() is not None:
                            raise RuntimeError(self._failure_message_locked(process))
                        if self.monitor_rss and sys.platform == "darwin":
                            usage = subprocess.run(
                                ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                                capture_output=True,
                                text=True,
                                timeout=3,
                            )
                            if usage.stdout.strip().isdigit() and int(usage.stdout) > MAX_PROCESS_RSS_GB * 1024**2:
                                raise RuntimeError("Image-Modell überschreitet das 24-GB-Prozessbudget. Ein kleineres oder vorquantisiertes Modell verwenden.")
                        events = selector.select(PROVIDER_POLL_INTERVAL)
                        if not events:
                            continue
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError(self._failure_message_locked(process))
                        response_buffer += chunk
                        while b"\n" in response_buffer:
                            line, response_buffer = response_buffer.split(b"\n", 1)
                            try:
                                event = json.loads(line)
                            except (TypeError, ValueError):
                                continue
                            if event.get("request_id") != request_id:
                                continue
                            if event.get("type") == "runtime":
                                if progress_callback is not None:
                                    step = event.get("step")
                                    total_steps = event.get("total_steps")
                                    expected_steps = params.get("steps")
                                    if (
                                        not isinstance(step, int)
                                        or not isinstance(total_steps, int)
                                        or step < 0
                                        or total_steps <= 0
                                        or step > total_steps
                                        or (
                                            expected_steps is not None
                                            and total_steps != expected_steps
                                        )
                                    ):
                                        step = None
                                        total_steps = None
                                    progress_callback({
                                        "phase": str(event.get("phase") or ""),
                                        "step": step,
                                        "total_steps": total_steps,
                                    })
                            elif event.get("type") == "error":
                                error_type = str(
                                    event.get("error_type") or "unknown error"
                                )
                                error_message = str(
                                    event.get("message") or ""
                                ).replace("\n", " ").replace("\r", " ").strip()

                                if len(error_message) > 1500:
                                    error_message = error_message[:1500] + "..."

                                detail = error_type
                                if error_message:
                                    detail += ": " + error_message

                                raise RuntimeError(
                                    "SDXL worker failed: " + detail
                                )
                            elif event.get("type") == "complete":
                                succeeded = True
                                break
                        if succeeded:
                            break
            finally:
                if process_callback is not None:
                    process_callback(None)
                if succeeded:
                    self._schedule_idle_shutdown_locked()
                else:
                    self._stop_locked()

    def is_running(self):
        with self._lock:
            return (
                self._process is not None
                and self._process.poll() is None
            )

    def close(self):
        with self._lock:
            self._stop_locked()


_sdxl_worker_manager = SDXLWorkerManager()


def sdxl_worker_running():
    """Return whether the warm SDXL worker is currently running."""
    return _sdxl_worker_manager.is_running()


def shutdown_sdxl_worker():
    """Release the warm SDXL worker during image-service shutdown."""
    _sdxl_worker_manager.close()


def _validate_provider_output(params, output):
    from PIL import Image

    with Image.open(output) as image:
        if image.format != "PNG":
            raise RuntimeError(
                "Provider lieferte kein gültiges PNG"
            )

        # Text-to-image requests have an explicitly requested canvas.
        # Image-edit requests intentionally inherit the source dimensions
        # unless the edit backend is told to resize/reframe.
        if "source_path" not in params:
            expected_size = (
                params["width"],
                params["height"],
            )

            if image.size != expected_size:
                raise RuntimeError(
                    "Provider lieferte kein PNG in der "
                    "angeforderten Auflösung"
                )

        image.verify()


def _quality_progress_callback(progress_callback, percent):
    if progress_callback is None:
        return
    progress_callback({
        "phase": "upscaling",
        "progress": min(0.995, max(0.9, 0.9 + (percent / 1000))),
    })


def _maybe_quality_upscale(
    params,
    output,
    *,
    cancel_event=None,
    process_callback=None,
    progress_callback=None,
):
    """Apply optional Real-ESRGAN 2x refinement to text-to-image quality jobs."""
    if params.get("quality") != "quality" or "source_path" in params:
        return False

    mode = quality_upscale_mode()
    if mode == "off":
        return False
    if not quality_upscale_available():
        if mode == "required":
            raise RuntimeError(
                "Quality+ benötigt eine vollständige lokale Real-ESRGAN-Installation"
            )
        return False

    output = Path(output)
    temporary = output.with_name(
        f".{output.stem}-quality-{secrets.token_hex(4)}.png"
    )
    command = realesrgan_command(
        output,
        temporary,
        preset=QUALITY_UPSCALE_PRESET,
    )
    process = None
    lines = []
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        if process_callback is not None:
            process_callback(process)
        deadline = time.monotonic() + GENERATION_TIMEOUT
        if progress_callback is not None:
            progress_callback({"phase": "upscaling", "progress": 0.9})

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderCancelled("Image job was cancelled")

            line = process.stdout.readline()
            if line:
                clean = line.strip()
                lines.append(clean)
                if len(lines) > 100:
                    lines = lines[-100:]
                match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", clean)
                if match:
                    _quality_progress_callback(
                        progress_callback,
                        min(100.0, max(0.0, float(match.group(1)))),
                    )

            returncode = process.poll()
            if returncode is not None:
                if process.stdout is not None:
                    remainder = process.stdout.read()
                    if remainder:
                        lines.extend(
                            item.strip()
                            for item in remainder.splitlines()
                            if item.strip()
                        )
                break

            if time.monotonic() >= deadline:
                raise RuntimeError("Quality+ Upscaling hat das Zeitlimit überschritten")
            if not line:
                time.sleep(0.05)

        if process.returncode != 0 or not temporary.is_file():
            detail = "\n".join(lines[-50:]).strip()
            raise RuntimeError(
                detail[-3000:]
                or "Quality+ konnte das Bild nicht hochskalieren"
            )

        os.replace(temporary, output)
        from PIL import Image
        with Image.open(output) as image:
            params["width"], params["height"] = image.size
        params["quality_upscale"] = True
        params["upscale_preset"] = QUALITY_UPSCALE_PRESET
        if progress_callback is not None:
            progress_callback({"phase": "upscaling", "progress": 0.995})
        return True
    except ProviderCancelled:
        raise
    except Exception as exc:
        if mode == "required":
            raise
        print(
            f"[image-quality] Quality+ fallback to base image: {exc}",
            flush=True,
        )
        return False
    finally:
        temporary.unlink(missing_ok=True)
        if process is not None and process.poll() is None:
            terminate_process_tree(process)
        if process_callback is not None:
            process_callback(None)


def run_provider(
    model,
    params,
    output,
    *,
    cancel_event=None,
    process_callback=None,
    progress_callback=None,
):
    ready, reason = availability(model)
    if not ready:
        raise ProviderFailure(reason, error_code='IMAGE_PROVIDER_INCOMPATIBLE', provider=model['provider'], model=model['id'])
    if cancel_event is not None and cancel_event.is_set():
        raise ProviderCancelled("Image job was cancelled")
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    if model["provider"] == "sdxl":
        checkpoint, config = sdxl_files(model)
        _sdxl_worker_manager.generate(
            checkpoint,
            config,
            params,
            output,
            environment=environment,
            cancel_event=cancel_event,
            process_callback=process_callback,
            progress_callback=progress_callback,
        )
        _validate_provider_output(params, output)
        _maybe_quality_upscale(
            params,
            output,
            cancel_event=cancel_event,
            process_callback=process_callback,
            progress_callback=progress_callback,
        )
        return
    if model["provider"] == "mlxgen":
        source = params.get("source_path")
        if not source:
            raise ProviderFailure("Bildbearbeitung benötigt ein Quellbild", provider="mlxgen", model=model["id"])
        # MLX-Gen 0.38.0 detects the edit handler from the known repo ID.
        # The absolute snapshot path routes incorrectly to latent img2img.
        # HF_HUB_OFFLINE=1 ensures repository lookup stays local.
        command = [str(MLXGEN_BIN), "generate", "--model", model["repository"],
                   "--image", str(source), "--prompt", params["prompt"],
                   "--width", str(params["width"]), "--height", str(params["height"]),
                   "--steps", str(params["steps"]), "--guidance", str(params["guidance"]),
                   "--seed", str(params["seed"]), "--output", str(output), "--low-ram"]
        worker_input = None
        if progress_callback is not None:
            progress_callback({"phase": "generating"})
    elif model["provider"] == "mlxserve":
        command = [
            sys.executable,
            str(Path(__file__).with_name("mlxserve_image_worker.py")),
        ]

        loras = []
        for lora in model.get("loras", []):
            if not lora.get("enabled"):
                continue
            loras.append({
                "path": str(resolve_lora_file(lora)),
                "scale": float(lora.get("scale", 1.0)),
            })

        worker_input = json.dumps({
            "params": params,
            "output": str(output),
            "repository": model["repository"],
            "base_url": MLXSERVE_URL,
            "loras": loras,
        })
    elif model["provider"] == "diffusionkit":
        command = [sys.executable, str(Path(__file__).with_name("image_worker.py"))]
        worker_input = json.dumps({"params": params, "output": str(output), "repository": model["repository"]})
    else:
        command = mflux_command(model, params, output)
        worker_input = None
        if progress_callback is not None and '--json-events' in probe_mflux_cli(command[0])['supported_flags']:
            command.append("--json-events")
        elif progress_callback is not None:
            progress_callback({'phase': 'generating'})
    # Phase-4 provider telemetry is opt-in to MLX-Gen jobs and contains no prompts.
    mlxgen_started = time.monotonic() if model["provider"] == "mlxgen" else None
    with tempfile.NamedTemporaryFile() as diagnostics, open(
        diagnostics.name,
        "rb",
    ) as progress_stream:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True, stdout=diagnostics,
                                   stderr=diagnostics, env=environment, shell=False,
                                   start_new_session=True)
        if process_callback is not None:
            process_callback(process)
        deadline = time.monotonic() + GENERATION_TIMEOUT
        progress_remainder = ""
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ProviderCancelled("Image job was cancelled")
                try:
                    process.communicate(
                        input=worker_input,
                        timeout=PROVIDER_POLL_INTERVAL,
                    )
                    break
                except subprocess.TimeoutExpired:
                    worker_input = None
                if progress_callback is not None:
                    progress_remainder = _read_runtime_events(
                        progress_stream,
                        progress_remainder,
                        progress_callback,
                        params.get("steps"),
                    )
                if cancel_event is not None and cancel_event.is_set():
                    raise ProviderCancelled("Image job was cancelled")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Image-Auftrag hat das Zeitlimit überschritten; Modellprozess wurde beendet")
                if sys.platform == "darwin":
                    usage = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(process.pid)], capture_output=True, text=True, timeout=3)
                    if usage.stdout.strip().isdigit() and int(usage.stdout) > MAX_PROCESS_RSS_GB * 1024**2:
                        raise RuntimeError("Image-Modell überschreitet das 24-GB-Prozessbudget. Ein kleineres oder vorquantisiertes Modell verwenden.")
        finally:
            terminate_process_tree(process)
            if process_callback is not None:
                process_callback(None)
        if progress_callback is not None:
            _read_runtime_events(
                progress_stream,
                progress_remainder + "\n",
                progress_callback,
                params.get("steps"),
            )
        if mlxgen_started is not None and progress_callback is not None:
            progress_callback({"provider_timing": {
                "schema": 1,
                "process_wall_ms": round((time.monotonic() - mlxgen_started) * 1000, 1),
                "exit_code": process.returncode,
                "steps": params.get("steps"),
                "width": params.get("width"),
                "height": params.get("height"),
                "low_ram": True,
                "note": "Process duration includes MLX-Gen loading and generation; does not isolate weight load or GPU compute.",
            }})
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")
        if process.returncode:
            diagnostics.seek(0, 2)
            diagnostics.seek(max(0, diagnostics.tell() - 65536))
            message = diagnostics.read().decode("utf-8", errors="replace").lower()
            # Full output stays local. API diagnostics omit prompts and private paths.
            diagnostics.seek(0)
            try:
                log = Path(output).with_suffix('.provider.log')
                with open(log, 'wb', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                    stream.write(diagnostics.read())
            except OSError:
                pass  # Logging must not mask the provider failure.
            if "all zero" in message or "weights appear corrupt" in message:
                raise RuntimeError("Lokale Modellgewichte sind beschädigt (Nullgewichte). Es wurden keine Dateien verändert oder heruntergeladen.")
            if "unrecognized arguments" in message:
                # Only retain flag names, never CLI values, prompts or private paths.
                rejected = sorted(set(re.findall(r'--[a-z][a-z0-9-]*', message.split('unrecognized arguments:', 1)[-1])))
                raise ProviderFailure("Installierte MFLUX-CLI ist mit den Provider-Parametern nicht kompatibel",
                                      error_code='IMAGE_PROVIDER_INCOMPATIBLE', provider=model['provider'], model=model['id'],
                                      detail=f"{Path(command[0]).name}: Exit {process.returncode}; unbekannte Argumente: {', '.join(rejected)}")
            raise ProviderFailure(f"{model['provider']} konnte das lokale Modell/LoRA nicht ausführen (Exit {process.returncode}). Cache und Provider-Kompatibilität prüfen; es wurde nichts heruntergeladen.",
                                  provider=model['provider'], model=model['id'], detail=f'{Path(command[0]).name}: Exit {process.returncode}')
    _validate_provider_output(params, output)
    _maybe_quality_upscale(
        params,
        output,
        cancel_event=cancel_event,
        process_callback=process_callback,
        progress_callback=progress_callback,
    )
