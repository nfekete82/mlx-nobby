"""Fixed provider adapters. Each generation owns one short-lived GPU process."""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from image_registry import FAMILIES, MODEL_ROOTS, validate_path

MFLUX_BIN = Path(os.environ.get("MLX_IMAGE_MFLUX_BIN", str(Path.home() / ".local/bin")))

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

GENERATION_TIMEOUT = 840
MAX_PROCESS_RSS_GB = 24
PROCESS_TERMINATION_TIMEOUT = 5
PROVIDER_POLL_INTERVAL = 0.5


class ProviderCancelled(RuntimeError):
    """Raised when a caller cancels an active provider process."""


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


def availability(model):
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
    return True, "Lokale Gewichte vorhanden; Provider-Kompatibilität wird bei Generierung geprüft"


def mflux_command(model, params, output):
    family = model["model_family"]

    # Qwen Image Edit has its own CLI contract. Do not pass the generic
    # text-to-image width/height/base-model/quantize arguments here.
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

    command = [
        str(MFLUX_BIN / FAMILIES[family][0]),
        "--model",
        str(model_directory(model)),
        "--base-model",
        model["base_model"],
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
        "--low-ram",
        "--mlx-cache-limit-gb",
        "2",
    ]

    if family != "z-image-turbo":
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
        raise RuntimeError(reason)
    if cancel_event is not None and cancel_event.is_set():
        raise ProviderCancelled("Image job was cancelled")
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    if model["provider"] == "diffusionkit":
        command = [sys.executable, str(Path(__file__).with_name("image_worker.py"))]
        worker_input = json.dumps({"params": params, "output": str(output), "repository": model["repository"]})
    else:
        command = mflux_command(model, params, output)
        worker_input = None
        if progress_callback is not None:
            command.append("--json-events")
    # Do not expose prompts/tokens or unfiltered provider tracebacks. Spool output.
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
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")
        if process.returncode:
            diagnostics.seek(0, 2)
            diagnostics.seek(max(0, diagnostics.tell() - 65536))
            message = diagnostics.read().decode("utf-8", errors="replace").lower()
            if "all zero" in message or "weights appear corrupt" in message:
                raise RuntimeError("Lokale Modellgewichte sind beschädigt (Nullgewichte). Es wurden keine Dateien verändert oder heruntergeladen.")
            if "unrecognized arguments" in message:
                raise RuntimeError("Installierte MFLUX-CLI ist mit den Provider-Parametern nicht kompatibel")
            raise RuntimeError(f"{model['provider']} konnte das lokale Modell/LoRA nicht ausführen (Exit {process.returncode}). Cache und Provider-Kompatibilität prüfen; es wurde nichts heruntergeladen.")
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
