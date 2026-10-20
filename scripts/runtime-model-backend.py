#!/usr/bin/env python3
"""Identify MLX LM/VLM backend from locally available model metadata only.

A Hugging Face repo ID may reference a fully cached VLM checkpoint. Never
classify it as LM solely because the ID is not an absolute directory path.
This helper does no network requests and never loads model weights.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REVISION = re.compile(r"^[a-fA-F0-9]{40,64}$")


def cached_config(model: str, environ: dict[str, str] | None = None,
                  home: Path | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    if not _REPOSITORY.fullmatch(model):
        return None
    root = Path(env.get("HF_HUB_CACHE") or
                (Path(env.get("HF_HOME") or ((home or Path.home()) / ".cache/huggingface")) / "hub"))
    repository = root / ("models--" + model.replace("/", "--"))
    snapshots = repository / "snapshots"
    if not snapshots.is_dir():
        return None

    # Hugging Face's refs/main is the authoritative downloaded revision.
    main_ref = repository / "refs" / "main"
    if main_ref.is_file():
        revision = main_ref.read_text(encoding="utf-8").strip()
        if _REVISION.fullmatch(revision):
            config = snapshots / revision / "config.json"
            if config.is_file():
                return config
        return None

    # Older or pinned caches without refs/main: a single unambiguous revision.
    entries = [item for item in snapshots.iterdir()
               if item.is_dir() and _REVISION.fullmatch(item.name)
               and (item / "config.json").is_file()]
    if len(entries) == 1:
        return entries[0] / "config.json"
    return None


def locate_config(model: str, environ: dict[str, str] | None = None,
                  home: Path | None = None) -> Path | None:
    expanded = model
    if model.startswith("~/"):
        expanded = str((home or Path.home()) / model[2:])
    config = Path(expanded) / "config.json"
    if config.is_file():
        return config
    return cached_config(model, environ=environ, home=home)


def detect(model: str, environ: dict[str, str] | None = None,
           home: Path | None = None) -> str:
    config = locate_config(model, environ=environ, home=home)
    if config is None:
        # Preserve previous behavior for unknown/not-yet-cached LM model IDs.
        return "lm"
    with config.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("Invalid local model configuration")
    architectures = data.get("architectures") or []
    text = " ".join(map(str, architectures)).lower()
    model_type = str(data.get("model_type", "")).lower()
    has_vision = (
        data.get("vision_config") is not None
        or "vision" in text
        or "conditionalgeneration" in text
        or "_vl" in text or "-vl" in text
        or "_vl" in model_type or "-vl" in model_type
    )
    return "vlm" if has_vision else "lm"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        print("Usage: runtime-model-backend.py <model reference>", file=sys.stderr)
        return 2
    try:
        print(detect(args[0]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print("Cannot read cached model configuration; refusing to guess backend",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
