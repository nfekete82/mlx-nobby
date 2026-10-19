"""In-memory stage comparison for the web chat prompt (opt-in).

No prompt, token IDs or fingerprints are logged or persisted.
"""
from __future__ import annotations

import logging
import os
import threading

_ENABLED = "MLX_PROMPT_STAGE_DIAG"
_LOG = logging.getLogger("nobby.prompt_stages")
_LOCK = threading.Lock()
_LAST: dict[str, str] = {}
_LIMIT = 65536


def compare(stage: str, messages: list[dict], *, extra_chars: int = 0) -> None:
    if os.getenv(_ENABLED) != "1":
        return
    system = ""
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        content = messages[0].get("content")
        if isinstance(content, str):
            system = content
    with _LOCK:
        previous = _LAST.get(stage)
        common = 0
        if previous is not None:
            for a, b in zip(previous, system):
                if a != b:
                    break
                common += 1
        _LOG.warning(
            "PROMPT_STAGE_DIAG stage=%s system_chars=%d prior_system_chars=%s "
            "common_prefix_chars=%d system_unchanged=%s messages=%d extra_chars=%d",
            stage, len(system),
            len(previous) if previous is not None else -1,
            common, previous == system if previous is not None else None,
            len(messages), extra_chars,
        )
        if len(system) <= _LIMIT:
            _LAST[stage] = system
        else:
            _LAST.pop(stage, None)
