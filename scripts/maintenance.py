#!/usr/bin/env python3
"""Conservative maintenance for local, generated MLX Nobby development data.

Never touches models, chat history, databases, backups, Docker volumes or
unrecognised paths. Dry-run unless --apply --yes are both supplied.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
LTX_DIR = re.compile(r"ltx-quality(?:-causes)?-20\d{6}$")
ACCEPTANCE_DIR = re.compile(r"acceptance-[A-Za-z0-9_-]+$")
LEGACY_LOG = re.compile(r"agent(?:-error)?\.log\.legacy-\d+$")
PREVIEW_PROJECT = re.compile(r"mlx-pr\d+-preview$")


@dataclass(frozen=True)
class Candidate:
    path: Path
    bytes: int
    kind: str


def inspect_tree(path: Path) -> tuple[int, float] | None:
    """Count apparent bytes and newest mtime; reject links, mounts and pins."""
    try:
        root_stat = path.lstat()
        if not path.is_dir() or path.is_symlink():
            return None
        size, newest = 0, root_stat.st_mtime
        device = root_stat.st_dev
        for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
            here = Path(current)
            for name in dirs + files:
                item = here / name
                stat = item.lstat()
                if item.is_symlink() or stat.st_dev != device:
                    return None
                if name in {".keep", ".nobby-keep"}:
                    return None
                if not (item.is_dir() or item.is_file()):
                    return None
                newest = max(newest, stat.st_mtime)
                if item.is_file():
                    size += stat.st_size
        return size, newest
    except (OSError, ValueError):
        return None


def artifact_candidates(root: Path, *, days: int, now: float) -> list[Candidate]:
    base = root / "artifacts"
    if base.is_symlink() or not base.is_dir():
        return []
    dirs: list[Path] = []
    try:
        dirs += [p for p in base.iterdir() if LTX_DIR.fullmatch(p.name)]
        acceptance = base / "acceptance"
        if acceptance.is_dir() and not acceptance.is_symlink():
            dirs += [p for p in acceptance.iterdir() if ACCEPTANCE_DIR.fullmatch(p.name)]
    except OSError:
        return []
    found = []
    for path in sorted(dirs):
        result = inspect_tree(path)
        if result is not None and now - result[1] >= days * 86400:
            found.append(Candidate(path, result[0], "test artifact"))
    return found


def legacy_candidates(root: Path, *, days: int, now: float) -> list[Candidate]:
    """Legacy files can contain private requests and require explicit opt-in."""
    found = []
    for path in root.iterdir():
        if not LEGACY_LOG.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        try:
            stat = path.stat()
            if now - stat.st_mtime >= max(30, days) * 86400:
                found.append(Candidate(path, stat.st_size, "legacy log"))
        except OSError:
            continue
    return sorted(found, key=lambda c: str(c.path))


def unused_log(path: Path) -> bool:
    """Never delete a legacy log while a process could hold it open."""
    if shutil.which("lsof") is None:
        return False
    result = subprocess.run(["lsof", "-nP", "--", str(path)],
                            capture_output=True, text=True, check=False)
    return result.returncode == 1 and not result.stdout.strip()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _docker_previews() -> dict[str, list[dict]]:
    if not shutil.which("docker"):
        return {}
    ids = _run(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project"])
    if ids.returncode or not ids.stdout.strip():
        return {}
    result = _run(["docker", "inspect", *ids.stdout.split()])
    if result.returncode:
        return {}
    grouped: dict[str, list[dict]] = {}
    for container in json.loads(result.stdout):
        labels = (container.get("Config") or {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project", "")
        if PREVIEW_PROJECT.fullmatch(project):
            grouped.setdefault(project, []).append(container)
    return grouped


def preview_report(root: Path) -> None:
    print("Docker PR previews (read-only):")
    groups = _docker_previews()
    if not groups:
        print("  none detected (or Docker unavailable)")
    for name, containers in sorted(groups.items()):
        print(f"  {name}: {len(containers)} containers; explicit removal only")
    print("Git worktrees (read-only, never removed automatically):")
    result = _run(["git", "-C", str(root), "worktree", "list", "--porcelain"])
    if result.returncode:
        print(f"  unavailable: {result.stderr.strip()}")
        return
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            location = line[len("worktree "):]
            status = _run(["git", "-C", location, "status", "--porcelain"])
            label = "clean" if status.returncode == 0 and not status.stdout else "modified/unavailable"
            print(f"  {location}: {label}")


def remove_preview(name: str, *, apply: bool, yes: bool) -> int:
    if not PREVIEW_PROJECT.fullmatch(name):
        print("Refusing non-PR Compose project name.", file=sys.stderr)
        return 2
    containers = _docker_previews().get(name, [])
    if not containers:
        print(f"No containers found for {name}.")
        return 0
    for container in containers:
        labels = (container.get("Config") or {}).get("Labels") or {}
        working_dir = labels.get("com.docker.compose.project.working_dir", "")
        if labels.get("com.docker.compose.project") != name or not working_dir:
            print("Refusing container with unexpected Compose labels.", file=sys.stderr)
            return 2
        for mount in container.get("Mounts", []):
            # External volumes or mounts outside the project's directory
            # may hold user data and must never be removed by this command.
            source = mount.get("Source", "")
            if mount.get("Type") != "bind" or not source:
                print("Refusing preview with a volume or unknown mount.", file=sys.stderr)
                return 2
            try:
                if os.path.commonpath([os.path.realpath(source), os.path.realpath(working_dir)]) != os.path.realpath(working_dir):
                    print("Refusing bind outside the preview working directory.", file=sys.stderr)
                    return 2
            except ValueError:
                return 2
    names = [item["Name"].lstrip("/") for item in containers]
    print(f"{name}: candidate containers: {', '.join(names)}")
    if not (apply and yes):
        print("DRY-RUN: to remove only these containers, use --apply --yes.")
        return 0
    result = _run(["docker", "rm", "-f", *[c["Id"] for c in containers]])
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return 1
    print(f"Removed {len(containers)} preview containers (no volumes or files removed).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="scan",
                        choices=("scan", "clean", "previews", "remove-preview"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--days", type=int, default=14, help="artifact age, minimum 7 days")
    parser.add_argument("--include-legacy-logs", action="store_true",
                        help="explicitly consider old legacy agent logs (minimum 30 days)")
    parser.add_argument("--name", help="exact Docker Compose PR preview project")
    parser.add_argument("--apply", action="store_true", help="allow explicitly scoped changes")
    parser.add_argument("--yes", action="store_true", help="required alongside --apply")
    args = parser.parse_args(argv)

    if args.action == "remove-preview":
        return remove_preview(args.name or "", apply=args.apply, yes=args.yes)
    root = args.root.expanduser().resolve()
    if not (root / "agent" / "log_rotation.py").is_file() or not (root / "scripts" / "agent-server.py").is_file():
        parser.error("--root must point to the MLX Nobby repository")
    if args.action == "previews":
        preview_report(root)
        return 0
    if args.days < 7:
        parser.error("--days must be at least 7")
    now = time.time()
    candidates = artifact_candidates(root, days=args.days, now=now)
    if args.include_legacy_logs:
        candidates += legacy_candidates(root, days=args.days, now=now)
    print(f"MLX Nobby maintenance: {len(candidates)} candidates; age >= {args.days} days")
    print("Protected: models, chats, memory, knowledge, backups, media library, Docker volumes.")
    if args.action == "scan" or not (args.apply and args.yes):
        print("DRY-RUN: no files will be deleted. Clean requires --apply --yes.")
    total = 0
    for candidate in candidates:
        # Revalidate immediately before removal: activity may have resumed.
        if candidate.kind == "test artifact":
            current = inspect_tree(candidate.path)
            safe = current is not None and now - current[1] >= args.days * 86400
        else:
            safe = (candidate.path.is_file() and not candidate.path.is_symlink()
                    and now - candidate.path.stat().st_mtime >= max(30, args.days) * 86400
                    and unused_log(candidate.path))
        if not safe:
            print(f"SKIP (changed or unsafe): {candidate.path}")
            continue
        total += candidate.bytes
        if args.action == "clean" and args.apply and args.yes:
            if candidate.kind == "test artifact":
                shutil.rmtree(candidate.path)
            else:
                candidate.path.unlink()
            print(f"REMOVED {candidate.kind}: {candidate.path}")
        else:
            print(f"CANDIDATE {candidate.kind}: {candidate.path} ({candidate.bytes / 1024**2:.1f} MiB)")
    print(f"Potential/apparent bytes: {total / 1024**3:.2f} GiB (APFS may reclaim less).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
