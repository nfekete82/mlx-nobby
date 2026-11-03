#!/usr/bin/env python3
"""Read-only on-device MLX Nobby status report.

Uses localhost GETs and Git metadata only. Never prints prompts, job IDs,
model paths, credentials, full HTTP payloads or local untracked file names.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    ("Web", 8090, "/api/health", True),
    ("Agent", 8010, "/api/status", True),
    ("Images", 8030, "/health", True),
    ("Video", 8060, "/health", True),
    ("Router", 8040, "/health", False),
    ("Embeddings", 8020, "/health", False),
    ("Speech", 8050, "/health", False),
)
OPTIONAL_SERVICES = (
    ("MLX runtime", 8000, "/v1/models", False),
)


def local_json(port: int, path: str, timeout: float = 3.0):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read(512 * 1024 + 1)
        if len(content) > 512 * 1024:
            return None, "response too large"
        parsed = json.loads(content.decode("utf-8"))
        if not isinstance(parsed, dict):
            return None, "unexpected JSON structure"
        return parsed, None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
        # Never include exception URLs or bodies in the public-facing summary.
        if isinstance(exc, urllib.error.HTTPError):
            return None, f"HTTP {exc.code}"
        return None, "unreachable/invalid JSON"


def service_healthy(payload, error):
    """HTTP 200 alone is not evidence that a native service is healthy."""
    if error is not None or not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return False
    state = str(payload.get("status") or "").strip().lower()
    if state in {"failed", "error", "unhealthy", "down", "offline"}:
        return False
    return True


def git_value(*args):
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def git_summary():
    head = git_value("rev-parse", "--short=12", "HEAD")
    branch = git_value("branch", "--show-current") or "(detached)"
    porcelain = git_value("status", "--porcelain", "--untracked-files=no")
    untracked = git_value("ls-files", "--others", "--exclude-standard").splitlines()
    upstream = git_value("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead = behind = None
    if upstream:
        diverge = git_value("rev-list", "--left-right", "--count", "HEAD...@{upstream}").split()
        if len(diverge) == 2 and all(x.isdecimal() for x in diverge):
            ahead, behind = map(int, diverge)
    return {
        "branch": branch,
        "commit": head or "unknown",
        "tracked_changes": len(porcelain.splitlines()) if porcelain else 0,
        "untracked_files": len(untracked),
        "ahead": ahead,
        "behind": behind,
        "upstream_configured": bool(upstream),
    }


REVISION_SERVICES = frozenset({"agent", "web", "embeddings", "images", "speech", "video"})


def _safe_service_names(values):
    if not isinstance(values, list):
        return []
    return sorted({name for name in values if isinstance(name, str) and name in REVISION_SERVICES})


def _revision_differs(loaded, checkout):
    """Compare genuine SHA prefixes, not arbitrary environment build labels."""
    import re

    if not isinstance(loaded, str) or not isinstance(checkout, str):
        return False
    if not (re.fullmatch(r"[a-f0-9]{7,40}", loaded) and re.fullmatch(r"[a-f0-9]{7,40}", checkout)):
        return False
    return not (loaded.startswith(checkout) or checkout.startswith(loaded))



# Deliberately narrow allowlist: these files do not run inside existing
# service processes. Treat all other files, including operational scripts,
# frontend assets and prompt documentation, as potentially runtime-relevant.
NON_RUNTIME_PREFIXES = (".github/", "tests/")
NON_RUNTIME_FILES = frozenset({
    ".gitignore", "LICENSE", "scripts/mlx", "scripts/local-health.py",
    "scripts/check-public-privacy.py", "docs/LOCAL_INTEGRATION_20261102.md",
})


def runtime_code_changed(old_revision, checkout_revision):
    """True: restart relevant; False: only inert files changed; None: unverified.

    Check the actual Git tree delta, never merely compare build labels.
    Require the loaded revision to be an ancestor of the checkout.
    """
    import re

    pattern = r"[a-f0-9]{7,40}"
    if not (isinstance(old_revision, str) and isinstance(checkout_revision, str)):
        return None
    if not (re.fullmatch(pattern, old_revision) and re.fullmatch(pattern, checkout_revision)):
        return None
    try:
        old = subprocess.check_output(
            ["git", "rev-parse", "--verify", old_revision + "^{commit}"],
            cwd=ROOT, stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        new = subprocess.check_output(
            ["git", "rev-parse", "--verify", checkout_revision + "^{commit}"],
            cwd=ROOT, stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        if old == new:
            return False
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", old, new],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True, timeout=5,
        )
        paths = subprocess.check_output(
            ["git", "diff", "--name-only", "-z", old, new, "--"],
            cwd=ROOT, stderr=subprocess.DEVNULL, timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    for raw_path in paths.split(b"\0"):
        if not raw_path:
            continue
        filename = raw_path.decode("utf-8", errors="replace")
        if filename not in NON_RUNTIME_FILES and not filename.startswith(NON_RUNTIME_PREFIXES):
            return True
    return False


def revision_summary(data, checkout_revision=None, diff_checker=runtime_code_changed):
    if not isinstance(data, dict):
        return {"reachable": False, "stale_count": None, "unknown_count": None}
    stale = data.get("stale_services")
    unknown = data.get("unknown_services")
    if not isinstance(stale, list) or not isinstance(unknown, list):
        return {"reachable": False, "stale_count": None, "unknown_count": None}

    # The Agent compares child processes with its OWN captured build revision.
    # That alone can report consistency while the Agent is behind the checkout.
    services = data.get("services") or []
    checkout_stale = []
    runtime_stale = []
    metadata_only = []
    unverified = []
    checked_services = set()
    cached_diffs = {}
    if isinstance(services, list):
        for item in services:
            if not isinstance(item, dict):
                continue
            name = item.get("service")
            if name not in REVISION_SERVICES:
                continue
            checked_services.add(name)
            revision = item.get("revision")
            if not _revision_differs(revision, checkout_revision):
                continue
            checkout_stale.append(name)
            if revision not in cached_diffs:
                cached_diffs[revision] = diff_checker(revision, checkout_revision)
            impact = cached_diffs[revision]
            if impact is True:
                runtime_stale.append(name)
            elif impact is False:
                metadata_only.append(name)
            else:
                unverified.append(name)

    # An Agent-reported mismatch with no verifiable service revision
    # must not be silently treated as harmless.
    for name in _safe_service_names(stale):
        if name not in checked_services:
            unverified.append(name)

    return {
        "reachable": True,
        "stale_count": len(stale),
        "unknown_count": len(unknown),
        "stale_services": _safe_service_names(stale),
        "unknown_services": _safe_service_names(unknown),
        "checkout_stale_services": sorted(set(checkout_stale)),
        "checkout_stale_count": len(set(checkout_stale)),
        "runtime_stale_services": sorted(set(runtime_stale)),
        "runtime_stale_count": len(set(runtime_stale)),
        "metadata_only_services": sorted(set(metadata_only)),
        "metadata_only_count": len(set(metadata_only)),
        "unverified_revision_services": sorted(set(unverified)),
        "unverified_revision_count": len(set(unverified)),
    }

def queue_summary(data):
    if not isinstance(data, dict):
        return {"reachable": False, "active": None, "waiting": None}
    active, waiting = data.get("active_count"), data.get("waiting_count")
    if not all(type(n) is int and n >= 0 for n in (active, waiting)):
        return {"reachable": False, "active": None, "waiting": None}
    return {"reachable": True, "active": active, "waiting": waiting}


def collect(include_runtime=False, request=local_json):
    results = []
    for name, port, path, required in SERVICES + (OPTIONAL_SERVICES if include_runtime else ()):
        payload, error = request(port, path)
        results.append({
            "name": name, "port": port,
            "reachable": service_healthy(payload, error),
            "required": required or (include_runtime and name == "MLX runtime"),
        })
    revisions, rev_error = request(8010, "/api/system/revisions")
    queue, queue_error = request(8010, "/api/system/job-queue")
    git = git_summary()
    return {
        "git": git,
        "services": results,
        "revisions": revision_summary(
            revisions if rev_error is None else None, checkout_revision=git["commit"]
        ),
        "queue": queue_summary(queue if queue_error is None else None),
    }


def findings(report, strict=False):
    failures, warnings = [], []
    for item in report["services"]:
        if not item["reachable"]:
            category = failures if item["required"] or strict else warnings
            category.append(f'{item["name"]} (port {item["port"]}) unreachable')
    r = report["revisions"]
    if not r["reachable"]:
        warnings.append("service revisions unavailable")
    else:
        if "runtime_stale_count" in r:
            if r["runtime_stale_count"]:
                names = ", ".join(r.get("runtime_stale_services") or [])
                failures.append(
                    f'{r["runtime_stale_count"]} services have changed runtime code'
                    + (f' ({names})' if names else '')
                )
            if r.get("unverified_revision_count"):
                names = ", ".join(r.get("unverified_revision_services") or [])
                warnings.append(
                    f'{r["unverified_revision_count"]} revision differences need review'
                    + (f' ({names})' if names else '')
                )
        else:
            # Legacy/synthetic reports without a source-diff are conservative.
            if r["stale_count"] or r.get("checkout_stale_count"):
                failures.append("unclassified service revision mismatch")
        if r["unknown_count"]:
            names = ", ".join(r.get("unknown_services") or [])
            warnings.append(f'{r["unknown_count"]} services have unknown revision' + (f' ({names})' if names else ''))
    if not report["queue"]["reachable"]:
        warnings.append("job queue unavailable")
    g = report["git"]
    if g["tracked_changes"]:
        warnings.append(f'{g["tracked_changes"]} tracked files modified')
    if g["behind"]:
        warnings.append(f'local branch is {g["behind"]} commits behind its configured upstream')
    return failures, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="only sanitized JSON")
    parser.add_argument("--strict", action="store_true", help="treat optional services as required")
    parser.add_argument("--runtime", action="store_true", help="also query optional MLX runtime model listing")
    args = parser.parse_args(argv)
    report = collect(include_runtime=args.runtime)
    failures, warnings = findings(report, strict=args.strict)
    report["result"] = "FAIL" if failures else "WARN" if warnings else "PASS"
    report["failures"] = failures
    report["warnings"] = warnings
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        g = report["git"]
        print(f'MLX Nobby read-only check — {report["result"]}')
        print(f'Git: {g["branch"]} @ {g["commit"]} | tracked changes: {g["tracked_changes"]} | untracked: {g["untracked_files"]}')
        if g["upstream_configured"]:
            print(f'Git upstream divergence (cached): ahead={g["ahead"]}, behind={g["behind"]}')
        for item in report["services"]:
            print(f'  {"OK" if item["reachable"] else "WARN" if not item["required"] and not args.strict else "FAIL"}  {item["name"]}: {item["port"]}')
        r, q = report["revisions"], report["queue"]
        print(
            f'Revision labels: different vs Agent={r["stale_count"]}, '
            f'older than checkout={r["checkout_stale_count"]}, '
            f'runtime changes={r.get("runtime_stale_count")}, '
            f'non-runtime-only={r.get("metadata_only_count")}, '
            f'unverified={r.get("unverified_revision_count")}, unknown={r["unknown_count"]}'
            if r["reachable"] else 'Revisions: unavailable'
        )
        print(f'Jobs: active={q["active"]}, waiting={q["waiting"]}' if q["reachable"] else 'Jobs: unavailable')
        for item in failures:
            print(f'  FAIL: {item}')
        for item in warnings:
            print(f'  WARN: {item}')
        print("Read-only: no models, jobs, chats or files changed.")
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
