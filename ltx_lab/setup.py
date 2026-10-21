"""Build independent pinned runtimes, using cached dependencies only."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from .compatibility import git, inspect_runtime, validate_environment
from .config import COMMITS, LAB, PRODUCTION, inside_lab, runtime_path
from .telemetry import write_json


def production_fingerprint():
    return {"head": git(PRODUCTION, "rev-parse", "HEAD"),
            "status": git(PRODUCTION, "status", "--porcelain", "--untracked-files=all"),
            "files": {name: hashlib.sha256((PRODUCTION / name).read_bytes()).hexdigest()
                      for name in ("uv.lock", "pyproject.toml", ".venv/pyvenv.cfg")}}


def prepare(version, allow_source_fetch=False):
    destination = inside_lab(runtime_path(version))
    LAB.mkdir(exist_ok=True)
    before = production_fingerprint()
    baseline = LAB / "production-baseline.json"
    if baseline.exists() and json.loads(baseline.read_text()) != before:
        raise RuntimeError("Production fingerprint differs from previous lab setup; inspect before continuing")
    if not baseline.exists():
        write_json(baseline, before)
    if not destination.exists():
        subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout", str(PRODUCTION),
                        str(destination)], check=True)
    # Never reset or clean an existing checkout with user changes.
    if git(destination, "status", "--porcelain", "--untracked-files=no"):
        # A fresh --no-checkout clone has tracked deletions until its first checkout.
        if (destination / "pyproject.toml").exists():
            raise RuntimeError("Test checkout has changes; refusing checkout")
    available = subprocess.run(["git", "-C", str(destination), "cat-file", "-e", COMMITS[version]],
                               capture_output=True).returncode == 0
    if not available:
        if not allow_source_fetch:
            raise RuntimeError("Pinned source unavailable locally; use --allow-source-fetch for code only")
        subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1", "--no-tags",
                        "https://github.com/dgrauet/ltx-2-mlx.git", COMMITS[version]], check=True)
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", COMMITS[version]], check=True)
    subprocess.run(["uv", "sync", "--offline", "--frozen", "--no-dev", "--link-mode", "copy",
                    "--python", str(PRODUCTION / ".venv/bin/python")], cwd=destination, check=True)
    result = inspect_runtime(destination, version)
    result["environment"] = validate_environment(destination, version)
    result["production_unchanged"] = production_fingerprint() == before
    if not result["production_unchanged"] or not result["compatible"]:
        raise RuntimeError("Environment validation failed")
    write_json(LAB / f"compatibility-{version}.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", nargs="+", choices=COMMITS, default=list(COMMITS))
    parser.add_argument("--allow-source-fetch", action="store_true",
                        help="Allow small pinned Git source fetch; dependencies stay offline; never model downloads")
    args = parser.parse_args()
    for version in args.versions:
        result = prepare(version, args.allow_source_fetch)
        print(json.dumps({k: result[k] for k in ("version", "commit", "compatible", "production_unchanged")}))


if __name__ == "__main__":
    main()
