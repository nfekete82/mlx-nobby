"""Bounded, read-only disk-usage scanning for approved local paths."""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path


DEFAULT_LIMIT = 20
DEFAULT_MIN_SIZE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_DEPTH = 5
DEFAULT_MAX_ENTRIES = 50_000
DEFAULT_DEADLINE_SECONDS = 8.0
MAX_LIMIT = 100
MAX_DEPTH = 12


def _bounded_int(value, default, minimum, maximum, name):
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return parsed


def _allowed_root(path, roots):
    return any(path == root or path.is_relative_to(root) for root in roots)


def resolve_scan_root(path=None, *, home=None, allowed_roots=None):
    """Resolve a scan root and require it to remain inside an approved root."""
    home = Path(home or Path.home()).resolve()
    roots = [home]
    for item in allowed_roots or ():
        root = Path(item).expanduser().resolve()
        if root not in roots:
            roots.append(root)

    if path in {None, ""}:
        candidate = home
    else:
        raw = str(path).strip()
        if not raw:
            candidate = home
        else:
            requested = Path(raw)
            if not requested.is_absolute():
                raise ValueError("disk_usage path must be absolute")
            if ".." in requested.parts:
                raise ValueError("disk_usage path traversal is not allowed")
            candidate = requested.resolve()

    if not _allowed_root(candidate, roots):
        raise ValueError("disk_usage path is outside approved roots")
    if not candidate.exists():
        raise ValueError("disk_usage path does not exist")
    if not candidate.is_dir():
        raise ValueError("disk_usage path must be a directory")
    return candidate


def scan_disk_usage(
    options=None,
    *,
    home=None,
    allowed_roots=None,
    max_entries=DEFAULT_MAX_ENTRIES,
    deadline_seconds=DEFAULT_DEADLINE_SECONDS,
    monotonic=time.monotonic,
):
    """Return bounded file and recursive directory-size rankings.

    Directory sizes are the sum of unique regular files reached during this
    scan. They are incomplete whenever a permission or traversal limit is hit.
    Directory symlinks are never followed.
    """
    options = dict(options or {})
    supported = {
        "path",
        "mode",
        "limit",
        "min_size_bytes",
        "max_depth",
        "include_hidden",
    }
    unknown = set(options) - supported
    if unknown:
        raise ValueError(
            "Unknown disk_usage options: " + ", ".join(sorted(unknown))
        )

    root = resolve_scan_root(
        options.get("path"),
        home=home,
        allowed_roots=allowed_roots,
    )
    mode = str(options.get("mode") or "both").strip().lower()
    if mode not in {"files", "directories", "both"}:
        raise ValueError("disk_usage mode must be files, directories, or both")

    limit = _bounded_int(
        options.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT, "limit"
    )
    min_size = _bounded_int(
        options.get("min_size_bytes"),
        DEFAULT_MIN_SIZE_BYTES,
        0,
        1 << 63,
        "min_size_bytes",
    )
    max_depth = _bounded_int(
        options.get("max_depth"),
        DEFAULT_MAX_DEPTH,
        0,
        MAX_DEPTH,
        "max_depth",
    )
    include_hidden = options.get("include_hidden", True)
    if not isinstance(include_hidden, bool):
        raise ValueError("include_hidden must be a boolean")

    max_entries = _bounded_int(
        max_entries,
        DEFAULT_MAX_ENTRIES,
        1,
        1_000_000,
        "max_entries",
    )
    try:
        deadline_seconds = float(deadline_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("deadline_seconds must be a positive number") from exc
    if deadline_seconds <= 0:
        raise ValueError("deadline_seconds must be a positive number")

    started = monotonic()
    stack = [(root, 0)]
    scanned_entries = 0
    permission_errors = 0
    scan_errors = 0
    skipped_symlinks = 0
    duplicate_files = 0
    partial_reasons = set()
    seen_files = set()
    files = []
    directory_sizes = {root: 0}

    while stack:
        if scanned_entries >= max_entries:
            partial_reasons.add("entry_limit")
            break
        if monotonic() - started >= deadline_seconds:
            partial_reasons.add("deadline")
            break

        directory, depth = stack.pop()
        try:
            iterator = os.scandir(directory)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                permission_errors += 1
                partial_reasons.add("permission")
            else:
                scan_errors += 1
                partial_reasons.add("scan_error")
            continue

        try:
            with iterator:
                for entry in iterator:
                    if scanned_entries >= max_entries:
                        partial_reasons.add("entry_limit")
                        stack.clear()
                        break
                    if monotonic() - started >= deadline_seconds:
                        partial_reasons.add("deadline")
                        stack.clear()
                        break

                    scanned_entries += 1
                    if not include_hidden and entry.name.startswith("."):
                        continue

                    try:
                        if entry.is_symlink():
                            skipped_symlinks += 1
                            continue

                        entry_path = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            directory_sizes.setdefault(entry_path, 0)
                            if depth < max_depth:
                                stack.append((entry_path, depth + 1))
                            else:
                                partial_reasons.add("max_depth")
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue

                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        if exc.errno in {errno.EACCES, errno.EPERM}:
                            permission_errors += 1
                            partial_reasons.add("permission")
                        else:
                            scan_errors += 1
                            partial_reasons.add("scan_error")
                        continue

                    identity = (stat_result.st_dev, stat_result.st_ino)
                    if identity in seen_files:
                        duplicate_files += 1
                        continue
                    seen_files.add(identity)

                    size = max(0, int(stat_result.st_size))
                    if mode in {"files", "both"} and size >= min_size:
                        files.append({
                            "path": str(entry_path),
                            "size_bytes": size,
                        })

                    parent = entry_path.parent
                    while parent == root or parent.is_relative_to(root):
                        directory_sizes[parent] = (
                            directory_sizes.get(parent, 0) + size
                        )
                        if parent == root:
                            break
                        parent = parent.parent
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                permission_errors += 1
                partial_reasons.add("permission")
            else:
                scan_errors += 1
                partial_reasons.add("scan_error")

    files.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    directories = [
        {"path": str(path), "size_bytes": size}
        for path, size in directory_sizes.items()
        if path != root and size >= min_size
    ]
    directories.sort(key=lambda item: (-item["size_bytes"], item["path"]))

    warnings = []
    if "entry_limit" in partial_reasons:
        warnings.append(f"Scan stopped after {max_entries} entries.")
    if "deadline" in partial_reasons:
        warnings.append("Scan stopped at its time limit.")
    if "max_depth" in partial_reasons:
        warnings.append(
            f"Directories below depth {max_depth} were not scanned."
        )
    if permission_errors:
        warnings.append(
            f"{permission_errors} unreadable paths were skipped."
        )
    if scan_errors:
        warnings.append(f"{scan_errors} paths could not be scanned.")

    return {
        "root": str(root),
        "partial": bool(partial_reasons),
        "partial_reasons": sorted(partial_reasons),
        "scanned_entries": scanned_entries,
        "permission_errors": permission_errors,
        "scan_errors": scan_errors,
        "skipped_symlinks": skipped_symlinks,
        "duplicate_files_skipped": duplicate_files,
        "directory_size_method": "sum_of_scanned_unique_regular_files",
        "largest_files": files[:limit] if mode in {"files", "both"} else [],
        "largest_directories": (
            directories[:limit]
            if mode in {"directories", "both"}
            else []
        ),
        "warnings": warnings,
    }
