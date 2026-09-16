"""Local MLX embedding API, intentionally separate from the chat LLM service."""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import mlx.core as mx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from local_security import LocalRequestGuard

# mlx-embeddings >=0.1.0 uses the public huggingface_hub.errors module.
from mlx_embeddings.utils import generate, load

MODEL_ID = "mlx-community/bge-m3-mlx-4bit"
MODEL_PATH = Path(
    os.environ.get(
        "MLX_EMBEDDING_MODEL_PATH",
        str(Path.home() / "Models/bge-m3-mlx-4bit"),
    )
).expanduser()
DIMENSIONS = 1024
MODEL_ROLES_FILE = Path.home() / ".config/mlx-web/model-roles.json"
REGISTERED_MODELS_FILE = Path.home() / ".config/mlx-server/models"
MAX_LENGTH = int(os.environ.get("MLX_EMBEDDING_MAX_LENGTH", "8192"))
MAX_BATCH_SIZE = int(os.environ.get("MLX_EMBEDDING_BATCH_SIZE", "8"))
if not 1 <= MAX_LENGTH <= 8192 or not 1 <= MAX_BATCH_SIZE <= 128:
    raise ValueError("Embedding max length must be 1..8192 and batch size 1..128")
logger = logging.getLogger("mlx_embeddings")


def selected_embedding_model() -> tuple[str, Path]:
    """Read the existing role preference and registered local model path."""
    roles = json.loads(MODEL_ROLES_FILE.read_text()) if MODEL_ROLES_FILE.is_file() else {}
    if not isinstance(roles, dict):
        raise RuntimeError("Ungültige Modellrollen")
    alias = str(roles.get("embedding", "auto")).strip() or "auto"
    if alias == "auto":
        return MODEL_ID, MODEL_PATH.resolve()
    if REGISTERED_MODELS_FILE.is_file():
        for line in REGISTERED_MODELS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            registered_alias, repo = (part.strip() for part in line.split("=", 1))
            if registered_alias == alias:
                path = Path(repo).expanduser()
                if path.is_absolute():
                    return alias, path.resolve()
                if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                    from huggingface_hub import snapshot_download
                    try:
                        return alias, Path(snapshot_download(repo_id=repo, local_files_only=True)).resolve()
                    except Exception as exc:
                        raise RuntimeError("Embedding-Modell ist nicht lokal zwischengespeichert") from exc
                raise RuntimeError("Embedding-Rolle benötigt einen registrierten lokalen Modellpfad")
    raise RuntimeError(f"Embedding-Modellalias nicht registriert: {alias}")


class EmbeddingRequest(BaseModel):
    texts: Annotated[list[Annotated[str, Field(min_length=1, max_length=100_000)]], Field(min_length=1, max_length=128)]


class SingleEmbeddingRequest(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=100_000)]


class Embedder:
    def __init__(self) -> None:
        self.model = None
        self.tokenizer = None
        self.lock = asyncio.Lock()
        self.status = "starting"
        self.error: str | None = None
        self.model_id: str | None = None
        self.model_path: Path | None = None
        self.dimensions: int | None = None

    def load(self) -> None:
        try:
            model_id, model_path = selected_embedding_model()
        except Exception as exc:
            self.model = self.tokenizer = None
            self.model_id = None
            self.model_path = None
            self.dimensions = None
            self.status = "failed"
            self.error = str(exc)
            raise
        if self.status == "ready" and self.model_id == model_id and self.model_path == model_path:
            return
        self.status = "starting"
        self.error = None
        self.model = self.tokenizer = None
        self.model_id = None
        self.model_path = None
        self.dimensions = None
        try:
            if not model_path.is_dir():
                raise RuntimeError(f"Embedding model not found: {model_path}")
            self.model, self.tokenizer = load(str(model_path))
            dimensions = len(self.embed_sync(["MLX embedding service readiness check"])[0])
            if dimensions < 1:
                raise RuntimeError("Startup embedding did not have valid dimensions")
            self.model_id = model_id
            self.model_path = model_path
            self.dimensions = dimensions
            self.status = "ready"
        except Exception as exc:
            self.model = self.tokenizer = None
            self.status = "failed"
            self.error = str(exc)
            raise

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Embedding model is not loaded")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[start : start + MAX_BATCH_SIZE]
            outputs = generate(
                self.model,
                self.tokenizer,
                batch,
                max_length=MAX_LENGTH,
                padding=True,
                truncation=True,
            )

            if hasattr(outputs, "text_embeds") and outputs.text_embeds is not None:
                pooled = outputs.text_embeds
            else:
                token_embeddings = (
                    outputs.last_hidden_state
                    if hasattr(outputs, "last_hidden_state")
                    else outputs
                )

                encoded = self.tokenizer.batch_encode_plus(
                    batch,
                    return_tensors="mlx",
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                )

                mask = encoded["attention_mask"].astype(mx.float32)[..., None]
                pooled = mx.sum(token_embeddings * mask, axis=1) / mx.maximum(
                    mx.sum(mask, axis=1),
                    1e-12,
                )
            normalized = pooled / mx.maximum(mx.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            mx.eval(normalized)
            vectors.extend(normalized.tolist())
        return vectors


embedder = Embedder()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        embedder.load()
        logger.info("Embedding model ready: %s (%s dimensions)", embedder.model_id, embedder.dimensions)
    except Exception as exc:
        embedder.status = "failed"
        embedder.error = str(exc)
        logger.exception("Embedding model startup failed")
    yield


app = FastAPI(title="MLX Local Embeddings", version="1.0", lifespan=lifespan)
app.add_middleware(LocalRequestGuard)


@app.get("/health")
async def health() -> dict:
    try:
        async with embedder.lock:
            await asyncio.to_thread(embedder.load)
    except Exception:
        pass
    return {
        "ok": embedder.status == "ready",
        "status": embedder.status,
        "model": embedder.model_id,
        "dimensions": embedder.dimensions,
        "backend": "mlx",
        "device": str(mx.default_device()),
        "batch_size": MAX_BATCH_SIZE,
        **({"error": embedder.error} if embedder.error else {}),
    }


async def make_embeddings(texts: list[str]) -> dict:
    if any(not text.strip() for text in texts):
        raise HTTPException(status_code=422, detail="texts must not contain empty values")
    async with embedder.lock:
        try:
            await asyncio.to_thread(embedder.load)
            vectors = await asyncio.to_thread(embedder.embed_sync, texts)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedding failed: {exc}") from exc
    if len(vectors) != len(texts) or any(len(vector) != embedder.dimensions for vector in vectors):
        raise HTTPException(status_code=503, detail="Unexpected embedding dimensions")
    return {"model": embedder.model_id, "dimensions": embedder.dimensions, "vectors": vectors}


@app.post("/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict:
    return await make_embeddings(request.texts)


@app.post("/embedding")
async def embedding(request: SingleEmbeddingRequest) -> dict:
    return await make_embeddings([request.text])
