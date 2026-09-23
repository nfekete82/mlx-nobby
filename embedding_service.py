"""Local embedding API backed by the shared mlx-serve runtime."""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from local_security import LocalRequestGuard


MODEL_ID = os.environ.get(
    "MLX_EMBEDDING_MODEL",
    "mlx-community/Qwen3-Embedding-4B-4bit-DWQ",
).strip()

DEFAULT_DIMENSIONS = 2560

MLXSERVE_URL = os.environ.get(
    "MLXSERVE_URL",
    "http://127.0.0.1:11234",
).rstrip("/")

MODEL_ROLES_FILE = (
    Path.home()
    / ".config/mlx-web/model-roles.json"
)

REGISTERED_MODELS_FILE = (
    Path.home()
    / ".config/mlx-server/models"
)

MLXSERVE_MODEL_ROOT = (
    Path.home()
    / ".mlx-serve/models"
)

REQUEST_TIMEOUT = float(
    os.environ.get(
        "MLX_EMBEDDING_REQUEST_TIMEOUT",
        "180",
    )
)

MAX_BATCH_SIZE = int(
    os.environ.get(
        "MLX_EMBEDDING_BATCH_SIZE",
        "64",
    )
)

if not 1 <= MAX_BATCH_SIZE <= 128:
    raise ValueError(
        "Embedding batch size must be 1..128"
    )


logger = logging.getLogger(
    "mlx_embedding_proxy"
)


class EmbeddingRequest(BaseModel):
    texts: Annotated[
        list[
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=100_000,
                ),
            ]
        ],
        Field(
            min_length=1,
            max_length=128,
        ),
    ]


class SingleEmbeddingRequest(BaseModel):
    text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100_000,
        ),
    ]


def _registered_models() -> dict[str, str]:
    models = {}

    if not REGISTERED_MODELS_FILE.is_file():
        return models

    for raw_line in (
        REGISTERED_MODELS_FILE
        .read_text(
            encoding="utf-8",
        )
        .splitlines()
    ):
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        alias, model = (
            part.strip()
            for part in line.split(
                "=",
                1,
            )
        )

        if alias and model:
            models[alias] = model

    return models


def _configured_embedding_alias() -> str:
    if not MODEL_ROLES_FILE.is_file():
        return "auto"

    try:
        roles = json.loads(
            MODEL_ROLES_FILE.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        ValueError,
        TypeError,
    ) as exc:
        raise RuntimeError(
            "Ungültige Modellrollen"
        ) from exc

    if not isinstance(roles, dict):
        raise RuntimeError(
            "Ungültige Modellrollen"
        )

    return (
        str(
            roles.get(
                "embedding",
                "auto",
            )
        ).strip()
        or "auto"
    )


def selected_embedding_model() -> tuple[str, str]:
    alias = _configured_embedding_alias()

    if alias == "auto":
        return MODEL_ID, MODEL_ID

    registered = _registered_models()

    if alias not in registered:
        raise RuntimeError(
            "Embedding-Modellalias "
            f"nicht registriert: {alias}"
        )

    return (
        alias,
        registered[alias],
    )


def _mlxserve_json(
    path: str,
    payload=None,
    *,
    timeout=REQUEST_TIMEOUT,
):
    data = (
        None
        if payload is None
        else json.dumps(
            payload
        ).encode("utf-8")
    )

    request = urllib.request.Request(
        MLXSERVE_URL + path,
        data=data,
        headers={
            "Accept": "application/json",
            **(
                {
                    "Content-Type":
                    "application/json"
                }
                if data is not None
                else {}
            ),
        },
        method=(
            "POST"
            if data is not None
            else "GET"
        ),
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            return json.loads(
                response
                .read()
                .decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        try:
            body = (
                exc.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )
        except Exception:
            body = ""

        raise RuntimeError(
            "mlx-serve "
            f"{path}: HTTP "
            f"{exc.code}"
            + (
                f": {body[:500]}"
                if body
                else ""
            )
        ) from exc

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "mlx-serve nicht erreichbar"
        ) from exc


def _mlxserve_models():
    payload = _mlxserve_json(
        "/v1/models",
        timeout=10,
    )

    models = payload.get(
        "data",
        [],
    )

    if not isinstance(models, list):
        return []

    return [
        item
        for item in models
        if isinstance(item, dict)
    ]


def _has_embedding_capability(
    model,
) -> bool:
    capabilities = model.get(
        "capabilities"
    )

    if isinstance(
        capabilities,
        list,
    ):
        values = {
            str(value).lower()
            for value in capabilities
        }

        if (
            "embedding" in values
            or "embeddings" in values
        ):
            return True

    if isinstance(
        capabilities,
        dict,
    ):
        for key in (
            "embedding",
            "embeddings",
        ):
            if capabilities.get(key):
                return True

    model_id = str(
        model.get("id") or ""
    ).lower()

    # mlx-serve advertises Qwen3 embedding
    # checkpoints with the embeddings
    # capability. Keep the name fallback
    # for older compatible server builds.
    return "embedding" in model_id


def _model_entry(
    model_id: str,
):
    return next(
        (
            item
            for item in _mlxserve_models()
            if item.get("id")
            == model_id
        ),
        None,
    )


def _embedding_dimensions(
    model_id: str,
    model=None,
):
    model = model or {}

    metadata = model.get(
        "meta"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        metadata = {}

    candidates = [
        model.get(
            "embedding_dimensions"
        ),
        model.get(
            "dimensions"
        ),
        metadata.get(
            "embedding_dimensions"
        ),
        metadata.get(
            "dimensions"
        ),
    ]

    for value in candidates:
        try:
            dimensions = int(value)

            if dimensions > 0:
                return dimensions
        except (
            TypeError,
            ValueError,
        ):
            pass

    config_path = (
        MLXSERVE_MODEL_ROOT
        / model_id
        / "config.json"
    )

    if config_path.is_file():
        try:
            config = json.loads(
                config_path.read_text(
                    encoding="utf-8",
                )
            )

            text_config = (
                config.get(
                    "text_config"
                )
                if isinstance(
                    config.get(
                        "text_config"
                    ),
                    dict,
                )
                else {}
            )

            for value in (
                config.get(
                    "hidden_size"
                ),
                text_config.get(
                    "hidden_size"
                ),
            ):
                try:
                    dimensions = int(
                        value
                    )

                    if dimensions > 0:
                        return dimensions
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        except (
            OSError,
            ValueError,
            TypeError,
        ):
            pass

    if model_id == MODEL_ID:
        return DEFAULT_DIMENSIONS

    return None


def embedding_model_compatible(
    alias: str,
) -> bool:
    try:
        if alias == "auto":
            model_id = MODEL_ID
        else:
            model_id = (
                _registered_models()
                .get(alias)
            )

            if not model_id:
                return False

        model = _model_entry(
            model_id
        )

        return bool(
            model
            and _has_embedding_capability(
                model
            )
            and _embedding_dimensions(
                model_id,
                model,
            )
        )

    except Exception:
        return False


def _make_embeddings_sync(
    texts: list[str],
) -> dict:
    role_model, upstream_model = (
        selected_embedding_model()
    )

    model = _model_entry(
        upstream_model
    )

    if (
        model is None
        or not _has_embedding_capability(
            model
        )
    ):
        raise RuntimeError(
            "Embedding-Modell ist in "
            "mlx-serve nicht verfügbar "
            "oder unterstützt keine "
            "Embeddings"
        )

    response = _mlxserve_json(
        "/v1/embeddings",
        {
            "model":
                upstream_model,
            "input":
                texts,
        },
    )

    items = response.get(
        "data",
        [],
    )

    if (
        not isinstance(items, list)
        or len(items) != len(texts)
    ):
        raise RuntimeError(
            "mlx-serve lieferte eine "
            "ungültige Anzahl Embeddings"
        )

    if all(
        isinstance(item, dict)
        and isinstance(
            item.get("index"),
            int,
        )
        for item in items
    ):
        items = sorted(
            items,
            key=lambda item:
                item["index"],
        )

    vectors = []

    for item in items:
        if not isinstance(
            item,
            dict,
        ):
            raise RuntimeError(
                "Ungültige "
                "Embedding-Antwort"
            )

        vector = item.get(
            "embedding"
        )

        if (
            not isinstance(
                vector,
                list,
            )
            or not vector
        ):
            raise RuntimeError(
                "Embedding-Vektor fehlt"
            )

        vectors.append(
            vector
        )

    dimensions = len(
        vectors[0]
    )

    if any(
        len(vector)
        != dimensions
        for vector in vectors
    ):
        raise RuntimeError(
            "Inkonsistente "
            "Embedding-Dimensionen"
        )

    expected_dimensions = (
        _embedding_dimensions(
            upstream_model,
            model,
        )
    )

    if (
        expected_dimensions
        and dimensions
        != expected_dimensions
    ):
        raise RuntimeError(
            "Unerwartete "
            "Embedding-Dimensionen: "
            f"{dimensions}; erwartet "
            f"{expected_dimensions}"
        )

    return {
        "model":
            role_model,
        "upstream_model":
            upstream_model,
        "dimensions":
            dimensions,
        "vectors":
            vectors,
    }


async def make_embeddings(
    texts: list[str],
) -> dict:
    if any(
        not text.strip()
        for text in texts
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "texts must not "
                "contain empty values"
            ),
        )

    try:
        return await asyncio.to_thread(
            _make_embeddings_sync,
            texts,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Embedding failed: "
                f"{exc}"
            ),
        ) from exc


app = FastAPI(
    title=(
        "MLX nobby Embedding "
        "Adapter"
    ),
    version="2.0",
)

app.add_middleware(
    LocalRequestGuard
)


@app.get("/health")
async def health() -> dict:
    try:
        role_model, upstream_model = (
            selected_embedding_model()
        )

        model = await asyncio.to_thread(
            _model_entry,
            upstream_model,
        )

        if (
            model is None
            or not _has_embedding_capability(
                model
            )
        ):
            raise RuntimeError(
                "Embedding-Modell ist "
                "in mlx-serve nicht "
                "verfügbar"
            )

        dimensions = (
            _embedding_dimensions(
                upstream_model,
                model,
            )
        )

        if not dimensions:
            raise RuntimeError(
                "Embedding-Dimensionen "
                "konnten nicht "
                "ermittelt werden"
            )

        return {
            "ok": True,
            "status": "ready",
            "model":
                role_model,
            "upstream_model":
                upstream_model,
            "dimensions":
                dimensions,
            "backend":
                "mlx-serve",
            "mlxserve_url":
                MLXSERVE_URL,
            "batch_size":
                MAX_BATCH_SIZE,
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "model": None,
            "dimensions": None,
            "backend":
                "mlx-serve",
            "mlxserve_url":
                MLXSERVE_URL,
            "error":
                str(exc),
        }


@app.get("/compatible-models")
async def compatible_models() -> dict:
    try:
        models = await asyncio.to_thread(
            _mlxserve_models
        )

        available = {
            str(
                item.get("id")
            ):
                item
            for item in models
            if item.get("id")
        }

        aliases = []

        for alias, model_id in (
            _registered_models()
            .items()
        ):
            model = available.get(
                model_id
            )

            if (
                model
                and
                _has_embedding_capability(
                    model
                )
            ):
                aliases.append(
                    alias
                )

        return {
            "aliases":
                sorted(aliases)
        }

    except Exception:
        return {
            "aliases": []
        }


@app.post("/embeddings")
async def embeddings(
    request: EmbeddingRequest,
) -> dict:
    return await make_embeddings(
        request.texts
    )


@app.post("/embedding")
async def embedding(
    request: SingleEmbeddingRequest,
) -> dict:
    return await make_embeddings(
        [request.text]
    )
