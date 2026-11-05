"""Read-only, privacy-safe resource decisions for the existing Performance Observatory.

Never starts/stops AI services or probes model endpoints. Reuses the already
captured macOS unified-memory budget and the 4B supervisor's bounded state.
The decisions are advisory; media's actual runtime coordinator remains the
authority for allocation and release.
"""
from __future__ import annotations

import math

import runtime_coordinator
from agent import memory_model_coordination

KNOWN_SUPERVISOR_STATES = frozenset({
    "running", "starting", "draining", "external", "disabled",
    "suspended_media", "suspended_pressure", "waiting_for_memory",
    "startup_failed", "supervisor_error",
})
MEMORY_4B_MODEL_LABEL = "Qwen3.5-4B"


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _memory4b_runtime():
    state = memory_model_coordination.supervisor_state()
    raw = state.get("state")
    raw = raw if raw in KNOWN_SUPERVISOR_STATES else "not_installed"
    managed = state.get("owned") is True
    pause = state.get("pause_extraction") is True
    # A supervisor heartbeat is not proof of a currently loaded MLX model:
    # report its self-declared state separately from an actual inference.
    return {
        "state": "warm" if raw == "running" and managed else
                 ("cold" if raw in KNOWN_SUPERVISOR_STATES - {"external"} else
                  "unavailable"),
        "model": MEMORY_4B_MODEL_LABEL,
        "supervisor_state": raw,
        "managed": managed,
        "paused": pause,
        "available": raw == "running" and managed,
        "loaded": raw == "running" and managed,
        "active": False,  # no source-grounded instantaneous inference counter
        "role": "memory",
    }


def _admission(memory, workload):
    """Explain current headroom, without claiming media can load immediately."""
    reserve = runtime_coordinator.model_load_reserve_gb(workload)
    headroom_min = (runtime_coordinator.VIDEO_MIN_HEADROOM_GB if workload == "video"
                    else runtime_coordinator.MEDIA_MIN_HEADROOM_GB)
    if not isinstance(memory, dict) or not _finite(memory.get("free_percent")):
        return {"state": "unknown", "reserve_gb": round(reserve, 2)}
    projected_hard = runtime_coordinator.projected_memory_hard_limit_reached(
        memory, reserve
    )
    relief = runtime_coordinator.memory_relief_needed(memory, headroom_min)
    return {
        "state": "release_required" if projected_hard or relief else "headroom_ok",
        "reserve_gb": round(reserve, 2),
        "minimum_headroom_gb": round(headroom_min, 2),
        "projected_hard_limit": bool(projected_hard),
        "release_recommended": bool(relief or projected_hard),
    }


def snapshot(memory):
    """No private paths, chat messages, raw jobs or model content in output."""
    try:
        model = _memory4b_runtime()
    except (OSError, ValueError, TypeError):
        model = {
            "state": "unavailable", "model": MEMORY_4B_MODEL_LABEL,
            "supervisor_state": "unavailable", "managed": False,
            "paused": False, "available": False, "loaded": False,
            "active": False, "role": "memory",
        }
    return {
        "memory4b": model,
        "admission": {
            "image": _admission(memory, "image"),
            "video": _admission(memory, "video"),
        },
        "note": "Advisory estimates; native image/video preflight decides actual admission.",
    }
