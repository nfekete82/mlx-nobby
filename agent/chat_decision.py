"""Central, conservative chat decision contract.

The existing semantic router remains responsible for general intent selection.
This layer only resolves *verified* required slots for capabilities with a
deterministic preflight (currently weather). Unknown cases delegate to the
existing router. Decisions are stateless and do not execute side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.weather_context import weather_context_query
from backend.weather_forecast import weather_request

DecisionKind = Literal["answer", "clarify", "execute_tool"]

_WEATHER_LOCATION_QUESTION = (
    "Für welchen Ort möchtest du das Wetter wissen? "
    "Nenne mir bitte eine Stadt oder Postleitzahl."
)


@dataclass(frozen=True)
class ChatDecision:
    kind: DecisionKind
    intent: str
    reason: str
    query: str = ""
    clarification: str = ""
    missing_slots: tuple[str, ...] = ()

    def metadata(self) -> dict:
        return {
            "kind": self.kind,
            "intent": self.intent,
            "reason": self.reason,
            "missing_slots": list(self.missing_slots),
        }

    def routing(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": 1.0,
            "requires_tools": self.kind == "execute_tool",
            "method": "slot_decision",
            "reason": self.reason,
            "decision": self.metadata(),
        }


def plan_chat_decision(prompt: str, conversation_context=None) -> ChatDecision | None:
    """Return a safe deterministic decision, or None to use the semantic router.

    A location is NEVER inferred from unrelated turns. The weather parser is
    the single authority for recognized weather phrasing. Unrecognized or
    compound prompts are left to the existing semantic router.
    """
    text = str(prompt or "").strip()
    if not text or len(text) > 180:
        return None

    resolved = weather_context_query(text, conversation_context)
    candidate = resolved or text
    weather = weather_request(candidate)
    if weather is None:
        return None

    if weather["status"] == "location_required":
        return ChatDecision(
            kind="clarify", intent="web_search",
            reason="weather_location_missing",
            clarification=_WEATHER_LOCATION_QUESTION,
            missing_slots=("location",),
        )
    return ChatDecision(
        kind="execute_tool", intent="web_search",
        reason="weather_context_resolved" if resolved else "weather_explicit_location",
        query=candidate,
    )


def decision_for_route(routing: dict) -> dict:
    """Present existing semantic routing in the same observable contract."""
    intent = str(routing.get("intent") or "normal_chat")
    kind: DecisionKind = "answer" if intent == "normal_chat" else "execute_tool"
    return {
        "kind": kind,
        "intent": intent,
        "reason": str(routing.get("reason") or "existing_router"),
        "missing_slots": [],
    }
