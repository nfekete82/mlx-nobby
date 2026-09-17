"""Lightweight local image-safety classification via ONNX.

The classifier is intentionally independent from the VLM runtime.
It classifies image content first; vision_routing then selects the
logical MLX model role.

Model:
    OwenElliott/image-safety-classifier-l

Classes:
    NSFL, NSFW, SFW

No PyTorch or Transformers dependency is required in the agent.
"""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import hashlib
import os
import shutil
import threading
import urllib.request

from agent.vision_routing import VisionClassification


MODEL_URL = (
    "https://huggingface.co/"
    "OwenElliott/image-safety-classifier-l/"
    "resolve/main/onnx/image-safety-classifier-l.onnx"
)

DEFAULT_MODEL_PATH = (
    Path.home()
    / ".cache"
    / "mlx-web"
    / "vision"
    / "image-safety-classifier-l.onnx"
)

CLASS_NAMES = ("NSFL", "NSFW", "SFW")
MIN_MODEL_BYTES = 1_000_000

_SESSION = None
_SESSION_LOCK = threading.Lock()

_CLASSIFICATION_CACHE = OrderedDict()
_CLASSIFICATION_CACHE_LOCK = threading.Lock()
_CLASSIFICATION_CACHE_MAX = 256


class VisionClassifierError(RuntimeError):
    pass


def model_path() -> Path:
    override = str(
        os.environ.get("MLX_VISION_CLASSIFIER_MODEL") or ""
    ).strip()

    if override:
        return Path(override).expanduser().resolve()

    return DEFAULT_MODEL_PATH


def ensure_model() -> Path:
    """Return the local ONNX model, downloading it atomically if needed."""

    path = model_path()

    if path.is_file() and path.stat().st_size >= MIN_MODEL_BYTES:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".part")

    try:
        request = urllib.request.Request(
            MODEL_URL,
            headers={
                "User-Agent": "mlx-nobby-vision-classifier/1.0",
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response, temporary.open("wb") as output:
            shutil.copyfileobj(
                response,
                output,
                length=1024 * 1024,
            )

        if (
            not temporary.is_file()
            or temporary.stat().st_size < MIN_MODEL_BYTES
        ):
            raise VisionClassifierError(
                "Downloaded vision classifier is unexpectedly small"
            )

        temporary.replace(path)

    except Exception as exc:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

        if isinstance(exc, VisionClassifierError):
            raise

        raise VisionClassifierError(
            f"Vision classifier download failed: {exc}"
        ) from exc

    return path


def _session():
    """Lazily create one ONNX session for the agent process."""

    global _SESSION

    if _SESSION is not None:
        return _SESSION

    with _SESSION_LOCK:
        if _SESSION is not None:
            return _SESSION

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise VisionClassifierError(
                "onnxruntime is not installed"
            ) from exc

        path = ensure_model()

        try:
            _SESSION = ort.InferenceSession(
                str(path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise VisionClassifierError(
                f"Vision classifier could not be loaded: {exc}"
            ) from exc

        return _SESSION


def _pixels(image):
    """Convert a PIL image to the tensor expected by the ONNX graph."""

    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise VisionClassifierError(
            "numpy and Pillow are required"
        ) from exc

    resampling = getattr(
        Image,
        "Resampling",
        Image,
    ).BILINEAR

    prepared = (
        image
        .convert("RGB")
        .resize((224, 224), resampling)
    )

    array = np.asarray(
        prepared,
        dtype=np.float32,
    )

    return (
        array
        .transpose(2, 0, 1)
        [None, ...]
    )


def _classification_from_probabilities(
    probabilities,
) -> VisionClassification:
    values = [
        float(value)
        for value in probabilities
    ]

    if len(values) != len(CLASS_NAMES):
        raise VisionClassifierError(
            "Vision classifier returned an unexpected class count"
        )

    scores = {
        name.lower(): value
        for name, value in zip(
            CLASS_NAMES,
            values,
        )
    }

    winner = max(
        range(len(values)),
        key=values.__getitem__,
    )

    raw_label = CLASS_NAMES[winner]

    label = {
        "SFW": "safe",
        "NSFW": "nsfw",
        "NSFL": "nsfl",
    }[raw_label]

    return VisionClassification(
        label=label,
        confidence=values[winner],
        scores=scores,
    )


def classify_pil_image(
    image,
) -> VisionClassification:
    session = _session()
    pixels = _pixels(image)

    try:
        input_name = session.get_inputs()[0].name
        result = session.run(
            None,
            {
                input_name: pixels,
            },
        )
    except Exception as exc:
        raise VisionClassifierError(
            f"Vision classification failed: {exc}"
        ) from exc

    if (
        not result
        or len(result[0]) < 1
    ):
        raise VisionClassifierError(
            "Vision classifier returned no predictions"
        )

    return _classification_from_probabilities(
        result[0][0]
    )


def classify_image_bytes(
    data: bytes,
) -> VisionClassification:
    if not isinstance(
        data,
        (bytes, bytearray),
    ):
        raise VisionClassifierError(
            "Image data must be bytes"
        )

    raw = bytes(data)

    digest = hashlib.sha256(
        raw
    ).hexdigest()

    with _CLASSIFICATION_CACHE_LOCK:
        cached = _CLASSIFICATION_CACHE.get(
            digest
        )

        if cached is not None:
            _CLASSIFICATION_CACHE.move_to_end(
                digest
            )
            return cached

    try:
        from PIL import Image

        with Image.open(BytesIO(raw)) as image:
            result = classify_pil_image(
                image
            )

    except VisionClassifierError:
        raise

    except Exception as exc:
        raise VisionClassifierError(
            f"Image could not be decoded: {exc}"
        ) from exc

    with _CLASSIFICATION_CACHE_LOCK:
        _CLASSIFICATION_CACHE[digest] = (
            result
        )

        _CLASSIFICATION_CACHE.move_to_end(
            digest
        )

        while (
            len(_CLASSIFICATION_CACHE)
            > _CLASSIFICATION_CACHE_MAX
        ):
            _CLASSIFICATION_CACHE.popitem(
                last=False
            )

    return result

def classify_image(
    path: str | Path,
) -> VisionClassification:
    source = Path(path)

    if not source.is_file():
        raise VisionClassifierError(
            f"Image not found: {source}"
        )

    try:
        return classify_image_bytes(
            source.read_bytes()
        )

    except VisionClassifierError:
        raise

    except Exception as exc:
        raise VisionClassifierError(
            f"Image could not be read: {exc}"
        ) from exc
