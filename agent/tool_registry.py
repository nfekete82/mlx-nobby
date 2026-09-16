"""Tool definitions and dispatch, independent of the agent and model provider.

Schemas, timeouts and output limits describe the handler contract. An optional
permission engine gates execution; existing handlers retain their validation
and limits. Results and exceptions pass through unchanged, including
structured results that must not be truncated into invalid JSON.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
import json
import math
import re
from typing import Any, Callable


class UnknownToolError(ValueError):
    """The requested tool is not registered."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    execute: Callable[..., Any]
    permission: str
    risks: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    output_limit_chars: int | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise ValueError("Invalid tool name")
        for label, value in (("description", self.description), ("permission", self.permission)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Tool {label} is required")
        if not callable(self.execute):
            raise TypeError("Tool execute must be callable")
        if not isinstance(self.parameters, dict) or self.parameters.get("type") != "object":
            raise ValueError("Tool parameters must describe a JSON object")
        json.dumps(self.parameters, allow_nan=False)
        if not isinstance(self.risks, tuple) or any(
            not isinstance(risk, str) or not risk.strip() for risk in self.risks
        ):
            raise ValueError("Tool risks must be a tuple of nonempty strings")
        if self.timeout_seconds is not None and (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Tool timeout must be positive and finite")
        if self.output_limit_chars is not None and (
            type(self.output_limit_chars) is not int or self.output_limit_chars <= 0
        ):
            raise ValueError("Tool output limit must be a positive integer")

    def definition(self):
        """Return detached, JSON-serializable metadata without the callable."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": deepcopy(self.parameters),
            "permission": self.permission,
            "risks": list(self.risks),
            "timeout_seconds": self.timeout_seconds,
            "output_limit_chars": self.output_limit_chars,
        }


class ToolRegistry:
    """A catalog with an optional policy gate for backward-compatible adoption."""

    def __init__(self, permission_engine=None):
        self._tools: dict[str, Tool] = {}
        self.permission_engine = permission_engine

    def register(self, tool: Tool):
        if not isinstance(tool, Tool):
            raise TypeError("Expected a Tool definition")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = replace(tool, parameters=deepcopy(tool.parameters))

    def get(self, name: str) -> Tool:
        try:
            tool = self._tools[name]
        except KeyError:
            raise UnknownToolError(f"Unknown tool: {name}") from None
        return replace(tool, parameters=deepcopy(tool.parameters))

    def names(self, permission: str | None = None) -> frozenset[str]:
        return frozenset(
            tool.name for tool in self._tools.values()
            if permission is None or tool.permission == permission
        )

    def definitions(self):
        return [tool.definition() for tool in self._tools.values()]

    def execute(self, name: str, *, run_context=None, **arguments):
        tool = self.get(name)
        if self.permission_engine is None:
            return tool.execute(**arguments)
        from agent.permissions import Decision, ToolPermissionError
        from agent.run_state import RunContext, bind_run_context, current_run_context

        context = run_context or current_run_context() or RunContext.start()
        with bind_run_context(context):
            decision = self.permission_engine.evaluate(tool, context, arguments)
            if decision.decision != Decision.ALLOW:
                raise ToolPermissionError(name, decision)
            return tool.execute(**arguments)
