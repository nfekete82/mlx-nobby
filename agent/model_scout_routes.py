"""Model Scout discovery, compatibility checks and local A/B benchmarks.

The discovery score is only a discovery signal. Model Scout v3 can also run an
explicit local A/B quick benchmark. It temporarily switches the single MLX
runtime to a candidate and always attempts to restore the original model.
Persistent evaluation decisions keep already-tested regressions from being
presented as fresh upgrade candidates again.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
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
import uuid

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from agent import model_evaluations


HF_API = os.environ.get("MODEL_SCOUT_HF_API", "https://huggingface.co/api/models").rstrip("/")
DEFAULT_SOURCES = tuple(
    value.strip()
    for value in os.environ.get("MODEL_SCOUT_SOURCES", "mlx-community").split(",")
    if value.strip()
)
CACHE_TTL_SECONDS = max(60, int(os.environ.get("MODEL_SCOUT_CACHE_TTL", "900")))
SCOUT_VERSION = 3
BENCHMARK_HISTORY_FILE = Path.home() / ".config/mlx-web/model-scout-benchmarks.json"
BENCHMARK_MAX_HISTORY = 20

_CACHE_LOCK = threading.Lock()
_CACHE = {"created": 0.0, "models": []}
_BENCHMARK_LOCK = threading.Lock()
_BENCHMARK_JOBS: dict[str, dict] = {}


class BenchmarkRequest(BaseModel):
    candidate_alias: str


class EvaluationRequest(BaseModel):
    model: str
    kind: str
    status: str
    reason: str
    compared_to: str | None = None
    metrics: dict | None = None
    source: str = "manual"


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
    try:
        return float(matches[0]) if matches else None
    except ValueError:
        return None


def infer_quantization_bits(model_id: str, tags: list[str] | None = None) -> float | None:
    text = " ".join([model_id, *(tags or [])]).lower()
    for pattern in (
        r"(?:^|[-_ ])(\d+(?:\.\d+)?)bit(?:[-_ ]|$)",
        r"(?:^|[-_ ])q(\d+)(?:[-_ ]|$)",
    ):
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
    return round((parameter_billions * bits / 8.0) * 1.25 + 1.5, 1)


def infer_role(model_id: str, tags: list[str] | None = None, pipeline_tag: str | None = None) -> str:
    text = " ".join([model_id, *(tags or []), pipeline_tag or ""]).lower()
    if any(token in text for token in ("vision", "vlm", "-vl-", "multimodal", "image-text-to-text")):
        return "vision"
    if any(token in text for token in ("coder", "coding", "code-", "devstral")):
        return "coding"
    return "chat"


def _license_from(model: dict) -> str | None:
    card = model.get("cardData")
    if isinstance(card, dict) and isinstance(card.get("license"), str):
        value = card["license"].strip()
        if value:
            return value
    for tag in model.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1] or None
    return None


def _parse_updated(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
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
        score += 35 if age_days <= 14 else 25 if age_days <= 60 else 15 if age_days <= 180 else 5
    downloads = max(0, int(model.get("downloads") or 0))
    likes = max(0, int(model.get("likes") or 0))
    score += min(25, int(math.log10(downloads + 1) * 6))
    score += min(20, int(math.log10(likes + 1) * 8))
    score += {"excellent": 20, "good": 15, "tight": 7, "risky": 0, "unknown": 5}.get(fit, 0)
    return min(100, score)


def _hf_cache_available(repo: str) -> bool:
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repo):
        return False
    cache_name = "models--" + repo.replace("/", "--")
    snapshots = Path.home() / ".cache/huggingface/hub" / cache_name / "snapshots"
    try:
        return any(path.is_file() for path in snapshots.glob("*/config.json"))
    except OSError:
        return False


def model_reference_available(model: dict) -> bool:
    repo = str(model.get("repo") or "").strip()
    if not repo:
        return False

    path = Path(repo).expanduser()
    if path.is_dir() and (path / "config.json").is_file():
        return True
    if isinstance(model.get("available"), bool) and model.get("available"):
        return True
    if _hf_cache_available(repo):
        return True

    if "/" in repo and not repo.startswith("/"):
        root = Path.home() / "Models" / repo.split("/")[-1]
        try:
            return (root / "config.json").is_file() or any(path.is_file() for path in root.glob("*/config.json"))
        except OSError:
            return False
    return False


def _installed_model(model_id: str, installed) -> dict | None:
    lowered = model_id.lower()
    if isinstance(installed, set):
        if lowered in installed:
            return {"alias": model_id.split("/")[-1], "repo": model_id, "available": True}
        return None
    for item in installed or []:
        if isinstance(item, dict) and str(item.get("repo") or "").strip().lower() == lowered:
            return item
    return None


def normalize_candidate(model: dict, profile: dict, installed) -> dict | None:
    model_id = str(model.get("id") or model.get("modelId") or "").strip()
    if not model_id or "/" not in model_id:
        return None

    tags = [str(tag) for tag in (model.get("tags") or []) if isinstance(tag, str)]
    parameters = infer_parameter_billions(model_id)
    bits = infer_quantization_bits(model_id, tags)
    estimated = estimate_memory_gb(parameters, bits)
    fit = _memory_fit(estimated, profile.get("memory_gb"))
    role = infer_role(model_id, tags, model.get("pipeline_tag"))
    installed_item = _installed_model(model_id, installed)
    installed_match = installed_item is not None
    name = model_id.split("/", 1)[1]
    alias = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-_")[:64] or "model"
    score = _discovery_score(model, fit)
    evaluation = model_evaluations.latest(model_id, kind=role)

    status = (
        "installed" if installed_match
        else "not_recommended" if fit == "risky"
        else "candidate" if score >= 65
        else "interesting"
    )
    if evaluation and evaluation.get("status") == "rejected":
        status = "rejected"
        score = 0

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
        "installed_alias": installed_item.get("alias") if installed_item else None,
        "benchmark_ready": model_reference_available(installed_item) if installed_item else False,
        "status": status,
        "discovery_score": score,
        "suggested_alias": alias,
        "evaluation": evaluation,
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
        headers={"User-Agent": "mlx-nobby-model-scout/3"},
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

    combined: dict[str, dict] = {}
    for source in DEFAULT_SOURCES:
        for model in _fetch_source(source, max(limit, 40)):
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

    candidates = []
    for raw in discover_raw_models(limit):
        candidate = normalize_candidate(raw, profile, installed_models)
        if candidate is not None and (role == "all" or candidate["role"] == role):
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["status"] != "rejected",
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
            "memory": "Memory is estimated from naming metadata and includes a conservative runtime reserve.",
            "benchmark": "The A/B quick benchmark runs the same timing probe and deterministic micro-suite on both models.",
            "evaluation": "Persistent local evaluations override discovery ranking; rejected models are retained for history but are not fresh upgrade candidates.",
        },
    }


QUALITY_TASKS = (
    {"id": "reasoning_sequence", "category": "reasoning", "prompt": "Setze die Folge fort: 2, 6, 12, 20, 30, ?. Antworte nur mit der Zahl.", "kind": "contains", "expected": "42"},
    {"id": "reasoning_logic", "category": "reasoning", "prompt": "Alle Ralos sind Tims. Kein Tim ist ein Vek. Kann ein Ralo ein Vek sein? Antworte nur mit ja oder nein.", "kind": "contains", "expected": "nein"},
    {"id": "coding_php", "category": "coding", "prompt": "Welcher Operator verbindet in PHP zwei Strings? Antworte ausschließlich mit dem Operatorzeichen.", "kind": "exact", "expected": "."},
    {"id": "coding_javascript", "category": "coding", "prompt": "Was ergibt JavaScript: [1,2,3].map(x => x * 2).join(',')? Antworte nur mit dem Ergebnis.", "kind": "contains", "expected": "2,4,6"},
    {"id": "german_article", "category": "german", "prompt": "Ergänze den bestimmten Artikel: ___ Mädchen. Antworte nur mit dem Artikel.", "kind": "contains", "expected": "das"},
    {"id": "german_grammar", "category": "german", "prompt": "Korrigiere den Satz und gib nur den korrigierten Satz aus: Wegen dem Regen blieb ich zuhause.", "kind": "contains", "expected": "wegen des regens"},
    {"id": "instruction_exact", "category": "instruction", "prompt": "Antworte exakt mit NOBBY_OK und mit nichts anderem.", "kind": "exact", "expected": "nobby_ok"},
    {"id": "instruction_json", "category": "instruction", "prompt": "Gib ausschließlich gültiges JSON aus: Schlüssel status mit Wert ok und Schlüssel count mit Zahl 3.", "kind": "json", "expected": {"status": "ok", "count": 3}},
)


def _normalize_answer(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", " ", str(value or ""), flags=re.IGNORECASE | re.DOTALL)
    value = value.replace("```json", "").replace("```", "")
    return " ".join(value.strip().lower().split())


def score_quality_answer(task: dict, answer: str) -> bool:
    normalized = _normalize_answer(answer)
    kind = task.get("kind")
    expected = task.get("expected")
    if kind == "exact":
        return normalized.strip() == str(expected).lower().strip()
    if kind == "contains":
        return str(expected).lower() in normalized
    if kind == "json":
        match = re.search(r"\{.*\}", answer or "", flags=re.DOTALL)
        if not match:
            return False
        try:
            return json.loads(match.group(0)) == expected
        except json.JSONDecodeError:
            return False
    return False


def summarize_quality(results: list[dict]) -> dict:
    categories: dict[str, dict[str, int | float]] = {}
    passed = 0
    for result in results:
        category = str(result.get("category") or "other")
        bucket = categories.setdefault(category, {"passed": 0, "total": 0, "score": 0.0})
        bucket["total"] = int(bucket["total"]) + 1
        if result.get("passed"):
            passed += 1
            bucket["passed"] = int(bucket["passed"]) + 1
    for bucket in categories.values():
        total = int(bucket["total"])
        bucket["score"] = round(int(bucket["passed"]) / total * 100, 1) if total else 0.0
    total = len(results)
    return {
        "passed": passed,
        "total": total,
        "score": round(passed / total * 100, 1) if total else 0.0,
        "categories": categories,
    }


def _http_json(url: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MLX API HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"MLX API nicht erreichbar: {exc}") from exc


def _runtime_model_id(port: int) -> str:
    data = _http_json(f"http://127.0.0.1:{port}/v1/models", timeout=20)
    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list) or not models:
        raise RuntimeError("MLX API liefert kein aktives Modell")
    model_id = str(models[0].get("id") or "").strip()
    if not model_id:
        raise RuntimeError("MLX API liefert keine Modell-ID")
    return model_id


def _chat_once(port: int, model_id: str, prompt: str, max_tokens: int = 96) -> dict:
    started = time.perf_counter()
    data = _http_json(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=180,
    )
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        content = ""
    usage = data.get("usage") if isinstance(data, dict) else {}
    return {
        "content": str(content),
        "usage": usage if isinstance(usage, dict) else {},
        "elapsed": time.perf_counter() - started,
    }


def _stream_timing(port: int, model_id: str, prompt: str, max_tokens: int = 128) -> dict:
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    event = json.loads(body)
                    delta = event.get("choices", [{}])[0].get("delta", {}).get("content")
                except (json.JSONDecodeError, IndexError, AttributeError):
                    continue
                if delta:
                    first_token_at = first_token_at or time.perf_counter()
                    chunks.append(str(delta))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Streaming-Benchmark fehlgeschlagen: HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Streaming-Benchmark fehlgeschlagen: {exc}") from exc

    finished = time.perf_counter()
    ttft = (first_token_at - started) if first_token_at is not None else finished - started
    return {
        "ttft_seconds": round(ttft, 4),
        "total_seconds": round(finished - started, 4),
        "content": "".join(chunks),
    }


def _runtime_rss_gb(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return round(int(result.stdout.strip()) / (1024 ** 2), 2)
    except Exception:
        return None


def benchmark_runtime(port: int, find_server_pid: Callable[[int], int | None]) -> dict:
    model_id = _runtime_model_id(port)
    _chat_once(port, model_id, "Antworte nur mit OK.", max_tokens=8)

    perf_prompt = (
        "Erkläre in ungefähr 100 Wörtern den Unterschied zwischen einem Prozess "
        "und einem Thread. Nenne dabei Speicherraum, Scheduling und Isolation."
    )
    usage_run = _chat_once(port, model_id, perf_prompt, max_tokens=128)
    timing = _stream_timing(port, model_id, perf_prompt, max_tokens=128)
    usage = usage_run.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or max(1, len(perf_prompt) // 4))
    completion_tokens = int(usage.get("completion_tokens") or max(1, len(usage_run["content"]) // 4))
    ttft = max(float(timing["ttft_seconds"]), 0.001)
    generation_seconds = max(float(timing["total_seconds"]) - ttft, 0.001)

    quality_results = []
    for task in QUALITY_TASKS:
        result = _chat_once(port, model_id, str(task["prompt"]), max_tokens=96)
        quality_results.append({
            "id": task["id"],
            "category": task["category"],
            "passed": score_quality_answer(task, result["content"]),
            "answer": result["content"][:600],
            "elapsed": round(float(result["elapsed"]), 3),
        })

    return {
        "runtime_model_id": model_id,
        "performance": {
            "ttft_seconds": round(ttft, 3),
            "effective_prefill_tps": round(prompt_tokens / ttft, 1),
            "generation_tps": round(completion_tokens / generation_seconds, 1),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "runtime_rss_gb": _runtime_rss_gb(find_server_pid(port)),
        },
        "quality": summarize_quality(quality_results),
        "quality_tasks": quality_results,
    }


def _delta_percent(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline in (None, 0):
        return None
    return round((candidate - baseline) / baseline * 100, 1)


def compare_benchmarks(baseline: dict, candidate: dict) -> dict:
    base_perf = baseline.get("performance") or {}
    cand_perf = candidate.get("performance") or {}
    quality_delta = round(
        float((candidate.get("quality") or {}).get("score") or 0)
        - float((baseline.get("quality") or {}).get("score") or 0),
        1,
    )
    generation_delta = _delta_percent(cand_perf.get("generation_tps"), base_perf.get("generation_tps"))
    prefill_delta = _delta_percent(cand_perf.get("effective_prefill_tps"), base_perf.get("effective_prefill_tps"))
    ttft_delta = _delta_percent(cand_perf.get("ttft_seconds"), base_perf.get("ttft_seconds"))
    rss_delta = _delta_percent(cand_perf.get("runtime_rss_gb"), base_perf.get("runtime_rss_gb"))

    if quality_delta >= 12.5 and (generation_delta or 0) >= 5:
        signal = "strong_candidate"
    elif quality_delta >= 0 and ((generation_delta or 0) >= 10 or (ttft_delta or 0) <= -10):
        signal = "promising"
    elif quality_delta <= -12.5:
        signal = "quality_regression"
    else:
        signal = "mixed"

    return {
        "quality_delta_points": quality_delta,
        "generation_tps_delta_pct": generation_delta,
        "prefill_tps_delta_pct": prefill_delta,
        "ttft_delta_pct": ttft_delta,
        "runtime_rss_delta_pct": rss_delta,
        "signal": signal,
    }


def _set_job(job_id: str, **updates) -> None:
    with _BENCHMARK_LOCK:
        if job_id in _BENCHMARK_JOBS:
            _BENCHMARK_JOBS[job_id].update(updates)


def _public_job(job: dict) -> dict:
    return json.loads(json.dumps(job))


def _load_history() -> list[dict]:
    try:
        data = json.loads(BENCHMARK_HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save_history(result: dict) -> None:
    history = [result, *_load_history()][:BENCHMARK_MAX_HISTORY]
    BENCHMARK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = BENCHMARK_HISTORY_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, BENCHMARK_HISTORY_FILE)


def _find_model(models: list[dict], *, alias: str | None = None, repo: str | None = None) -> dict | None:
    for model in models:
        if not isinstance(model, dict):
            continue
        if alias is not None and str(model.get("alias") or "") == alias:
            return model
        if repo is not None and str(model.get("repo") or "") == repo:
            return model
    return None


def _record_scout_evaluation(candidate_repo: str, baseline_repo: str, comparison: dict) -> dict:
    signal = str(comparison.get("signal") or "mixed")
    if signal in {"strong_candidate", "promising"}:
        status = "candidate"
    elif signal == "quality_regression":
        status = "rejected"
    else:
        status = "tested"
    return model_evaluations.record(
        candidate_repo,
        kind=infer_role(candidate_repo),
        status=status,
        reason=f"Model Scout quick A/B result: {signal}.",
        compared_to=baseline_repo,
        metrics=comparison,
        source="model-scout-quick-ab-v1",
    )


def _run_benchmark_job(
    job_id: str,
    candidate_alias: str,
    model_provider,
    config_provider,
    switch_model,
    runtime_lock,
    find_server_pid,
) -> None:
    acquired = False
    baseline_alias = None
    switched = False
    try:
        _set_job(job_id, status="running", phase="waiting_runtime", progress=3)
        acquired = runtime_lock.acquire(timeout=10)
        if not acquired:
            raise RuntimeError("Die MLX Runtime ist gerade durch eine andere Modellaktion belegt.")

        models = model_provider() or []
        config = config_provider() or {}
        baseline_repo = str(config.get("MODEL") or "").strip()
        baseline = _find_model(models, repo=baseline_repo)
        candidate = _find_model(models, alias=candidate_alias)
        if baseline is None:
            raise RuntimeError("Das aktive Modell hat keinen eindeutigen Alias und kann nicht sicher wiederhergestellt werden.")
        if candidate is None:
            raise RuntimeError("Der Benchmark-Kandidat ist nicht mehr in der Modellverwaltung vorhanden.")

        baseline_alias = str(baseline.get("alias") or "").strip()
        if not baseline_alias:
            raise RuntimeError("Aktives Modell ohne Alias.")
        if candidate_alias == baseline_alias:
            raise RuntimeError("Kandidat und aktives Modell sind identisch.")
        if not model_reference_available(candidate):
            raise RuntimeError("Der Kandidat ist noch nicht lokal verfügbar. Bitte zuerst herunterladen.")

        port = int(config.get("PORT") or 8000)
        _set_job(job_id, baseline_alias=baseline_alias, baseline_repo=baseline_repo, candidate_repo=candidate.get("repo"), phase="baseline", progress=10)
        try:
            _runtime_model_id(port)
        except RuntimeError:
            switch_model(baseline_alias)

        baseline_result = benchmark_runtime(port, find_server_pid)
        _set_job(job_id, baseline=baseline_result, phase="switching_candidate", progress=48)
        switch_model(candidate_alias)
        switched = True
        _set_job(job_id, phase="candidate", progress=56)
        candidate_result = benchmark_runtime(port, find_server_pid)
        comparison = compare_benchmarks(baseline_result, candidate_result)

        _set_job(job_id, phase="restoring", progress=94)
        switch_model(baseline_alias)
        switched = False
        finished_at = datetime.now(timezone.utc).isoformat()
        with _BENCHMARK_LOCK:
            created_at = _BENCHMARK_JOBS[job_id].get("created_at")
        result = {
            "job_id": job_id,
            "created_at": created_at,
            "finished_at": finished_at,
            "baseline_alias": baseline_alias,
            "baseline_repo": baseline_repo,
            "candidate_alias": candidate_alias,
            "candidate_repo": candidate.get("repo"),
            "baseline": baseline_result,
            "candidate": candidate_result,
            "comparison": comparison,
            "suite": {
                "name": "mlx-nobby-quick-ab-v1",
                "tasks": len(QUALITY_TASKS),
                "note": "Repeatable local micro-suite; not a general leaderboard score.",
            },
        }
        _save_history(result)
        try:
            result["evaluation"] = _record_scout_evaluation(
                str(candidate.get("repo") or ""),
                baseline_repo,
                comparison,
            )
        except Exception as exc:
            result["evaluation_error"] = str(exc)
        _set_job(job_id, status="completed", phase="completed", progress=100, finished_at=finished_at, result=result)
    except Exception as exc:
        restore_error = None
        if acquired and switched and baseline_alias:
            try:
                _set_job(job_id, phase="restoring_after_error", progress=96)
                switch_model(baseline_alias)
            except Exception as restore_exc:
                restore_error = str(restore_exc)
        message = str(exc)
        if restore_error:
            message += f" | Wiederherstellung fehlgeschlagen: {restore_error}"
        _set_job(job_id, status="failed", phase="failed", finished_at=datetime.now(timezone.utc).isoformat(), error=message)
    finally:
        if acquired:
            runtime_lock.release()


def start_benchmark(
    candidate_alias: str,
    *,
    model_provider,
    config_provider,
    switch_model,
    runtime_lock,
    find_server_pid,
) -> dict:
    candidate_alias = str(candidate_alias or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", candidate_alias):
        raise HTTPException(400, "Ungültiger Modellalias")

    with _BENCHMARK_LOCK:
        if any(job.get("status") in {"queued", "running"} for job in _BENCHMARK_JOBS.values()):
            raise HTTPException(409, "Es läuft bereits ein Model-Scout-Benchmark.")
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "candidate_alias": candidate_alias,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        }
        _BENCHMARK_JOBS[job_id] = job

    threading.Thread(
        target=_run_benchmark_job,
        args=(job_id, candidate_alias, model_provider, config_provider, switch_model, runtime_lock, find_server_pid),
        name=f"model-scout-{job_id}",
        daemon=True,
    ).start()
    return _public_job(job)


def get_benchmark_job(job_id: str) -> dict:
    with _BENCHMARK_LOCK:
        job = _BENCHMARK_JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Model-Scout-Benchmark nicht gefunden")
        return _public_job(job)


def install_routes(
    app: FastAPI,
    model_provider,
    config_provider=None,
    switch_model=None,
    runtime_lock=None,
    find_server_pid=None,
) -> None:
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

    if "/api/model-scout/evaluations" not in paths:
        @app.get("/api/model-scout/evaluations")
        def model_scout_evaluations(
            kind: str | None = Query(default=None),
            status: str | None = Query(default=None),
        ):
            return {"evaluations": model_evaluations.list_latest(kind=kind, status=status)}

        @app.post("/api/model-scout/evaluations")
        def model_scout_record_evaluation(request: EvaluationRequest):
            try:
                return model_evaluations.record(
                    request.model,
                    kind=request.kind,
                    status=request.status,
                    reason=request.reason,
                    compared_to=request.compared_to,
                    metrics=request.metrics,
                    source=request.source,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    benchmark_enabled = all(value is not None for value in (config_provider, switch_model, runtime_lock, find_server_pid))
    if benchmark_enabled and "/api/model-scout/benchmarks" not in paths:
        @app.post("/api/model-scout/benchmarks", status_code=202)
        def model_scout_start_benchmark(request: BenchmarkRequest):
            return start_benchmark(
                request.candidate_alias,
                model_provider=model_provider,
                config_provider=config_provider,
                switch_model=switch_model,
                runtime_lock=runtime_lock,
                find_server_pid=find_server_pid,
            )

        @app.get("/api/model-scout/benchmarks")
        def model_scout_benchmark_history():
            return {"benchmarks": _load_history()[:BENCHMARK_MAX_HISTORY]}

    if benchmark_enabled and "/api/model-scout/benchmarks/{job_id}" not in paths:
        @app.get("/api/model-scout/benchmarks/{job_id}")
        def model_scout_benchmark_job(job_id: str):
            return get_benchmark_job(job_id)


__all__ = [
    "benchmark_runtime",
    "compare_benchmarks",
    "discover_models",
    "estimate_memory_gb",
    "infer_parameter_billions",
    "infer_quantization_bits",
    "infer_role",
    "install_routes",
    "model_reference_available",
    "normalize_candidate",
    "score_quality_answer",
    "start_benchmark",
    "summarize_quality",
    "system_profile",
]
