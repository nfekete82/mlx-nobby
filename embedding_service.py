"""Local MLX embedding API, intentionally separate from the chat LLM service."""

import asyncio
import logging
import os
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
MAX_LENGTH = int(os.environ.get("MLX_EMBEDDING_MAX_LENGTH", "8192"))
MAX_BATCH_SIZE = int(os.environ.get("MLX_EMBEDDING_BATCH_SIZE", "8"))
if not 1 <= MAX_LENGTH <= 8192 or not 1 <= MAX_BATCH_SIZE <= 128:
    raise ValueError("Embedding max length must be 1..8192 and batch size 1..128")
logger = logging.getLogger("mlx_embeddings")


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

    def load(self) -> None:
        if not MODEL_PATH.is_dir():
            raise RuntimeError(f"Embedding model not found: {MODEL_PATH}")
        self.model, self.tokenizer = load(str(MODEL_PATH))

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
        probe = embedder.embed_sync(["MLX embedding service readiness check"])
        if len(probe) != 1 or len(probe[0]) != DIMENSIONS:
            raise RuntimeError("Startup embedding did not have the expected dimensions")
        embedder.status = "ready"
        logger.info("Embedding model ready: %s (%s dimensions)", MODEL_ID, DIMENSIONS)
    except Exception as exc:
        embedder.status = "failed"
        embedder.error = str(exc)
        logger.exception("Embedding model startup failed")
    yield


app = FastAPI(title="MLX Local Embeddings", version="1.0", lifespan=lifespan)
app.add_middleware(LocalRequestGuard)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": embedder.status == "ready",
        "status": embedder.status,
        "model": MODEL_ID,
        "dimensions": DIMENSIONS,
        "backend": "mlx",
        "device": str(mx.default_device()),
        "batch_size": MAX_BATCH_SIZE,
        **({"error": embedder.error} if embedder.error else {}),
    }


async def make_embeddings(texts: list[str]) -> dict:
    if embedder.status != "ready":
        raise HTTPException(status_code=503, detail=embedder.error or "Embedding service is not ready")
    if any(not text.strip() for text in texts):
        raise HTTPException(status_code=422, detail="texts must not contain empty values")
    async with embedder.lock:
        try:
            vectors = await asyncio.to_thread(embedder.embed_sync, texts)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedding failed: {exc}") from exc
    if len(vectors) != len(texts) or any(len(vector) != DIMENSIONS for vector in vectors):
        raise HTTPException(status_code=503, detail="Unexpected embedding dimensions")
    return {"model": MODEL_ID, "dimensions": DIMENSIONS, "vectors": vectors}


@app.post("/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict:
    return await make_embeddings(request.texts)


@app.post("/embedding")
async def embedding(request: SingleEmbeddingRequest) -> dict:
    return await make_embeddings([request.text])
