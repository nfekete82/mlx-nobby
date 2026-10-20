#!/usr/bin/env python3
"""Explicit model-candidate registration; never download/switch/restart services.

Candidate metadata is frozen here, while existing 'mlx model add' remains the
single implementation that writes MLX-Nobby's user-local aliases.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

CANDIDATES = {
    "dark-scarlett": {
        "alias": "dark-scarlett-27b",
        "repository": "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp",
        "model_page": "https://huggingface.co/jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp",
    },
}


def alias_file(home: Path) -> Path:
    return home / ".config" / "mlx-server" / "models"


def registered_repo(path: Path, alias: str) -> str | None:
    """Read existing alias without following a potentially unsafe symlink."""
    if path.is_symlink():
        raise ValueError("Model alias file is a symlink; registration refused")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("Model alias file is not a regular bounded file")
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == alias:
            matches.append(value)
    if len(matches) > 1:
        raise ValueError("Alias is defined more than once; resolve this manually")
    return matches[0] if matches else None


def prepare(name: str, action: str, *, home: Path | None = None,
            launcher: Path | None = None) -> int:
    info = CANDIDATES[name]
    path = alias_file(home if home is not None else Path.home())
    configured = registered_repo(path, info["alias"])
    if configured is not None and configured != info["repository"]:
        raise ValueError("Alias is already assigned to a different model; no changes made")
    if action == "status":
        label = "registered" if configured else "not registered"
        print(f"{name}: {label}")
    elif action == "register":
        if configured == info["repository"]:
            print("Candidate already registered; no changes made")
        else:
            launcher = launcher or Path(__file__).resolve().parent / "mlx"
            # Existing alias API; never call 'mlx model <alias>' (which switches).
            completed = subprocess.run(
                ["bash", str(launcher), "model", "add", info["alias"], info["repository"]],
                check=False, capture_output=True, text=True, timeout=30,
            )
            if completed.returncode != 0:
                raise RuntimeError("Existing MLX model-alias command failed")
            if registered_repo(path, info["alias"]) != info["repository"]:
                raise RuntimeError("Alias was not confirmed after registration")
            print(f"Registered {info['alias']} -> {info['repository']}")
    else:
        raise ValueError("Unsupported operation")
    print("The active/default chat model, model weights and runtime are unchanged.")
    print("Source: " + info["model_page"])
    print("Optional, deliberate next step: ./scripts/mlx download " + info["alias"])
    print("Do NOT switch until you have checked runtime compatibility and memory headroom.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=sorted(CANDIDATES))
    parser.add_argument("action", choices=("status", "register"), nargs="?", default="status")
    args = parser.parse_args(argv)
    try:
        return prepare(args.candidate, args.action)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Candidate operation failed: " + type(exc).__name__
              + " (alias/configuration unchanged unless external command reported failure)",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
