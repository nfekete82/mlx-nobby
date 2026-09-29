"""Model Scout discovery and compatibility routes.

Phase 1 deliberately focuses on safe discovery and system-fit checks. It does
not replace or activate models automatically. Candidates can be handed to the
existing model manager for download and testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import platform
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException, Query


HF_API = os.environ.get("MODEL_SCOUT_HF_API", "https://huggingface.co/api/models").rstrip("/")
DEFAULT_SOURCES = tuple(
    source.strip()
    for source in os.environ.get("MODEL_SCOUT_SOURCES", "mlx-community").split(",")
    if source.strip()
)
CACHE_TTL_SECONDS = max(60, int(os.environ.get("MODEL_SCOUT_CACHE_TTL", "900")))
SCOUT_VERSION = 1

_CACHE_LOCK = threading.Lock()
_CACHE = {"created": 0.0, "models": []}


def _system_memory_gb() -> float | None:
    override = os.environ.get("MODEL_SCOUT_MEMORY_GB")
    if override:
        try:
            value = float(override)
            return value if value > 0 else None
        except ValueError:
            pass

    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            return round(int(result.stdout.strip()) / (1024 ** 3), 1)
        except Exception:
            pass

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return round((pages * page_size) / (1024 ** 3), 1)
    except (AttributeError, OSError, ValueError):
        pass

    return None


def system_profile() -> dict:
    memory_gb = _system_memory_gb()
    return {
        "platform": platform.system().lower(),
        "architecture": platform.machine().lower(),
        "memory_gb": memory_gb,
        "mlx_native": platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"},
    }


def infer_parameter_billions(model_id: str) -> float | None:
    name = model_id.split("/")[-1]
    matches = re.findall(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)B(?:\b|[-_])", name, re.IGNORECASE)
    if not matches:
        matches = re.findall(r"(?:^|[-_])(\d+(?:\.\d+)?)B(?:[-_]|$)", name, re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[0])
    except ValueError:
        return None


def infer_quantization_bits(model_id: str, tags: list[str] | None = None) -> float | None:
    text = " ".join([model_id, *(tags or [])]).lower()
    patterns = (
        r"(?:^|[-_ ])(\d+(?:\.\d+)?)bit(?:[-_ ]|$)",
        r"(?:^|[-_ ])q(\d+)(?:[-_ ]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                value = float(match.group(1))
                if 1 <= value <= 16:
                    return value
            except ValueError:
                pass
    if "bf16" in text or "bfloat16" in text or "fp16" in text:
        return 16.0
    if "8bit" in text or "int8" in text:
        return 8.0
    if "4bit" in text or "int4" in text:
        return 4.0
    return None


def estimate_memory_gb(parameter_billions: float | None, bits: float | None) -> float | None:
    if not parameter_billions or not bits:
        return None
    weights = parameter_billions * bits / 8.0
    # KV cache/runtime overhead varies by architecture and context length. A
    # conservative fixed + percentage reserve is more useful than pretending
    # to know an exact number from model-card metadata alone.
    return round(weights * 1.25 + 1.5, 1)


def infer_role(model_id: str, tags: list[str] | None = None, pipeline_tag: str | None = None) -> str:
    text = " ".join([model_id, *(tags or []), pipeline_tag or ""]).lower()
    if any(token in text for token in ("vision", "vlm", "-vl-", "multimodal", "image-text-to-text")):
        return "vision"
    if any(token in text for token in ("coder", "coding", "code-", "devstral")):
        return "coding"
    return "chat"


def _license_from(model: dict) -> str | None:
    card = model.get("cardData")
    if isinstance(card, dict):
        value = card.get("license")
        if isinstance(value, str) and value.strip():
            return value.strip()
    for tag in model.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1] or None
    return None


def _parse_updated(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _memory_fit(estimated_gb: float | None, memory_gb: float | None) -> str:
    if estimated_gb is None or memory_gb is None:
        return "unknown"
    ratio = estimated_gb / memory_gb
    if ratio <= 0.60:
        return "excellent"
    if ratio <= 0.75:
        return "good"
    if ratio <= 0.90:
        return "tight"
    return "risky"


def _discovery_score(model: dict, fit: str) -> int:
    score = 0
    updated = _parse_updated(model.get("lastModified"))
    if updated:
        age_days = max(0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).days)
        if age_days <= 14:
            score += 35
        elif age_days <= 60:
            score += 25
        elif age_days <= 180:
            score += 15
        else:
            score += 5

    downloads = max(0, int(model.get("downloads") or 0))
    likes = max(0, int(model.get("likes") or 0))
    score += min(25, int(math.log10(downloads + 1) * 6))
    score += min(20, int(math.log10(likes + 1) * 8))
    score += {"excellent": 20, "good": 15, "tight": 7, "risky": 0, "unknown": 5}.get(fit, 0)
    return min(100, score)


def _installed_repos(models: list[dict]) -> set[str]:
    repos = set()
    for item in models or []:
        if not isinstance(item, dict):
            continue
        repo = item.get("repo")
        if isinstance(repo, str) and repo.strip():
            repos.add(repo.strip().lower())
    return repos


def normalize_candidate(model: dict, profile: dict, installed: set[str]) -> dict | None:
    model_id = str(model.get("id") or model.get("modelId") or "").strip()
    if not model_id or "/" not in model_id:
        return None

    tags = [str(tag) for tag in (model.get("tags") or []) if isinstance(tag, str)]
    parameters = infer_parameter_billions(model_id)
    bits = infer_quantization_bits(model_id, tags)
    estimated = estimate_memory_gb(parameters, bits)
    fit = _memory_fit(estimated, profile.get("memory_gb"))
    role = infer_role(model_id, tags, model.get("pipeline_tag"))
    installed_match = model_id.lower() in installed

    name = model_id.split("/", 1)[1]
    alias = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-_")[:64] or "model"
    score = _discovery_score(model, fit)

    if installed_match:
        status = "installed"
    elif fit == "risky":
        status = "not_recommended"
    elif score >= 65:
        status = "candidate"
    else:
        status = "interesting"

    return {
        "id": model_id,
        "name": name,
        "author": model_id.split("/", 1)[0],
        "url": "https://huggingface.co/" + model_id,
        "last_modified": model.get("lastModified"),
        "downloads": int(model.get("downloads") or 0),
        "likes": int(model.get("likes") or 0),
        "license": _license_from(model),
        "role": role,
        "pipeline_tag": model.get("pipeline_tag"),
        "library_name": model.get("library_name"),
        "parameter_billions": parameters,
        "quantization_bits": bits,
        "estimated_memory_gb": estimated,
        "memory_fit": fit,
        "installed": installed_match,
        "status": status,
        "discovery_score": score,
        "suggested_alias": alias,
        "tags": tags[:24],
    }


def _fetch_source(author: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "author": author,
        "sort": "lastModified",
        "direction": -1,
        "limit": limit,
        "full": "true",
    })
    request = urllib.request.Request(
        HF_API + "?" + params,
        headers={"User-Agent": "mlx-nobby-model-scout/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, "Hugging Face model search failed") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Hugging Face model search is currently unavailable") from exc

    return data if isinstance(data, list) else []


def discover_raw_models(limit: int) -> list[dict]:
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE["models"] and now - float(_CACHE["created"]) < CACHE_TTL_SECONDS:
            return list(_CACHE["models"])

    per_source = max(limit, 40)
    combined: dict[str, dict] = {}
    for source in DEFAULT_SOURCES:
        for model in _fetch_source(source, per_source):
            model_id = str(model.get("id") or model.get("modelId") or "")
            if model_id:
                combined[model_id] = model

    models = list(combined.values())
    with _CACHE_LOCK:
        _CACHE["created"] = now
        _CACHE["models"] = list(models)
    return models


def discover_models(model_provider, *, limit: int = 30, role: str = "all") -> dict:
    profile = system_profile()
    try:
        installed_models = model_provider() or []
    except Exception:
        installed_models = []
    installed = _installed_repos(installed_models)

    candidates = []
    for raw in discover_raw_models(limit):
        candidate = normalize_candidate(raw, profile, installed)
        if candidate is None:
            continue
        if role != "all" and candidate["role"] != role:
            continue
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["installed"],
            item["discovery_score"],
            item.get("last_modified") or "",
        ),
        reverse=True,
    )

    return {
        "version": SCOUT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": list(DEFAULT_SOURCES),
        "profile": profile,
        "count": min(limit, len(candidates)),
        "candidates": candidates[:limit],
        "notes": {
            "score": "Discovery score measures freshness, popularity and local fit; it is not a quality benchmark.",
            "memory": "Memory is estimated from model naming metadata and includes a conservative runtime reserve.",
        },
    }


def install_routes(app: FastAPI, model_provider) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/model-scout/profile" not in paths:
        @app.get("/api/model-scout/profile")
        def model_scout_profile():
            return {"version": SCOUT_VERSION, "profile": system_profile(), "sources": list(DEFAULT_SOURCES)}

    if "/api/model-scout/discover" not in paths:
        @app.get("/api/model-scout/discover")
        def model_scout_discover(
            limit: int = Query(default=30, ge=1, le=100),
            role: str = Query(default="all", pattern="^(all|chat|coding|vision)$"),
        ):
            return discover_models(model_provider, limit=limit, role=role)


__all__ = [
    "discover_models",
    "estimate_memory_gb",
    "infer_parameter_billions",
    "infer_quantization_bits",
    "infer_role",
    "install_routes",
    "normalize_candidate",
    "system_profile",
]
