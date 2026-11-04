#!/usr/bin/env python3
"""Opt-in daily launchd job for the narrowly allowlisted artifact cleanup."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


LABEL = "de.nobby.mlx-maintenance"
ROOT = Path(__file__).resolve().parents[1]


def make_plist(root: Path, python: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python), str(root / "scripts" / "maintenance.py"),
            "clean", "--root", str(root), "--days", "14", "--apply", "--yes",
        ],
        "StartCalendarInterval": {"Hour": 4, "Minute": 30},
        "RunAtLoad": False,
        "KeepAlive": False,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "ProcessType": "Background",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove", "status"))
    args = parser.parse_args(argv)
    destination = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    if args.action == "status":
        print(f"{destination}: {'installed' if destination.is_file() else 'not installed'}")
        return 0

    if args.action == "remove":
        if not destination.exists():
            print("No maintenance job installed.")
            return 0
        if destination.is_symlink():
            parser.error("refusing symlinked LaunchAgent")
        with destination.open("rb") as stream:
            if plistlib.load(stream).get("Label") != LABEL:
                parser.error("refusing unknown LaunchAgent")
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"],
                       capture_output=True, check=False)
        destination.unlink()
        print("Maintenance job removed; no data deleted.")
        return 0

    root = ROOT.resolve()
    if not (root / "scripts" / "maintenance.py").is_file():
        parser.error("maintenance.py is missing")
    runtime = root / "runtime-venv" / "bin" / "python"
    python = runtime if runtime.is_file() else Path(sys.executable).resolve()
    if destination.is_symlink():
        parser.error("refusing symlinked LaunchAgent")
    if destination.exists():
        with destination.open("rb") as stream:
            if plistlib.load(stream).get("Label") != LABEL:
                parser.error("refusing to overwrite unknown LaunchAgent")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = plistlib.dumps(make_plist(root, python), sort_keys=False)
    temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"],
                   capture_output=True, check=False)
    response = subprocess.run(["launchctl", "bootstrap", domain, str(destination)],
                              capture_output=True, text=True, check=False)
    if response.returncode:
        print(f"LaunchAgent saved but launchctl bootstrap failed: {response.stderr.strip()}",
              file=sys.stderr)
        return 1
    print("Installed optional daily 04:30 cleanup: only allowlisted test artifacts older than 14 days.")
    print("Legacy logs, user media, backups, models, previews and worktrees are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
