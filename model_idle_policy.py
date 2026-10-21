"""Fail-closed eligibility policy for MLX model idle unloading.

This module makes decisions only. It never calls an unload endpoint.
"""

from dataclasses import dataclass


IDLE_SECONDS = {
    "chat": 900,
    "router": 300,
}


@dataclass(frozen=True)
class IdleState:
    role: str
    now: float
    last_activity: float | None
    loaded: bool
    idle_verified: bool
    lease_free: bool
    active_requests: int
    pending_requests: int
    exclusive_session: bool
    server_identity_verified: bool


@dataclass(frozen=True)
class IdleDecision:
    allowed: bool
    reason: str


def evaluate_idle_unload(state: IdleState) -> IdleDecision:
    """Authorize only an observed, completely idle model."""

    if state.role not in IDLE_SECONDS:
        return IdleDecision(False, "unknown_role")

    if not state.loaded:
        return IdleDecision(False, "not_loaded")

    if not state.server_identity_verified:
        return IdleDecision(False, "server_not_verified")

    if not state.idle_verified:
        return IdleDecision(False, "idle_not_verified")

    if not state.lease_free:
        return IdleDecision(False, "lease_active_or_unknown")

    if state.exclusive_session:
        return IdleDecision(False, "exclusive_session")

    if type(state.active_requests) is not int or state.active_requests != 0:
        return IdleDecision(False, "active_requests_or_unknown")

    if type(state.pending_requests) is not int or state.pending_requests != 0:
        return IdleDecision(False, "pending_requests_or_unknown")

    if (
        type(state.now) not in (int, float)
        or type(state.last_activity) not in (int, float)
    ):
        return IdleDecision(False, "activity_time_unknown")

    import math

    if not (
        math.isfinite(state.now)
        and math.isfinite(state.last_activity)
    ):
        return IdleDecision(False, "activity_time_invalid")

    elapsed = state.now - state.last_activity

    if elapsed < 0:
        return IdleDecision(False, "clock_inconsistent")

    if elapsed < IDLE_SECONDS[state.role]:
        return IdleDecision(False, "idle_timeout_not_reached")

    return IdleDecision(True, "eligible")
