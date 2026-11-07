#!/usr/bin/env python3
"""Safely opt into or roll back the shared router gateway on this Mac.

Nothing runs automatically on a Git checkout. --enable requires a verified
private backup, idle media services, the existing dedicated 4B supervisor and
the operator's explicit approval. Only the *router* LaunchAgent is reloaded.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Direct invocation (python3 scripts/...) puts scripts/, not the repository
# root, on sys.path. Resolve local agent/runtime modules from this checkout.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONFIG = Path.home() / ".config/mlx-web"
ROUTER_PLIST = Path.home() / "Library/LaunchAgents/de.nobby.mlx-router.plist"
STATE_DIR = CONFIG / "memory-model-control"
LEGACY = STATE_DIR / "router-original.plist"
DOMAIN = f"gui/{os.getuid()}"
LABEL = "de.nobby.mlx-router"


def _json_get(port, path="/health"):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        url, timeout=5,
    ) as response:
        return json.loads(response.read(300_000))


def _idle():
    import runtime_coordinator as rc
    lease = rc.lease_state_snapshot().get("active")
    if lease:
        raise RuntimeError("Active model lease; no router change")
    for port in (8030, 8060):
        result = _json_get(port)
        if result.get("active_generation") or result.get("active_job_id") or result.get("status") in ("busy", "running"):
            raise RuntimeError(f"Media job is active on {port}")
    queue = _json_get(8010, "/api/system/job-queue?limit=1")
    if queue.get("active_count") or queue.get("waiting_count"):
        raise RuntimeError("Agent media queue is not idle")


def _reload(candidate):
    location = ROOT / "scripts/reload-launchagent.py"
    spec = importlib.util.spec_from_file_location("nobby_router_reload", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".router-", suffix=".plist", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(candidate)
        os.chmod(name, 0o600)
        return module.install(DOMAIN, LABEL, name, ROUTER_PLIST)
    finally:
        Path(name).unlink(missing_ok=True)


def _render_gateway():
    template = (ROOT / "launchd/optional/de.nobby.mlx-router.plist.template").read_text()
    replacements = {
        "__PROJECT_DIR__": str(ROOT),
        "__RUNTIME_PYTHON__": str(ROOT / "runtime-venv/bin/python"),
        "__CONFIG_DIR__": str(CONFIG),
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    result = template.encode()
    assert plistlib.loads(result)["Label"] == LABEL
    return result


def _policy(enabled):
    from agent import memory_model_coordination as ctl
    ctl._write(ctl.ON_DEMAND, {"enabled": bool(enabled)})


def _check_backup(path):
    if path is None:
        raise RuntimeError("--enable requires --backup /path/to/verified/backup")
    script = ROOT / "scripts/backup-local-state.py"
    result = subprocess.run(
        [sys.executable, str(script), "--verify", "--destination", str(path)],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError("Private backup verification failed")
    if json.loads(result.stdout).get("verified") is not True:
        raise RuntimeError("Private backup did not verify")


def _wait_gateway_ready(*, timeout=15.0):
    """Wait for the weightless gateway to bind after launchd bootstrap.

    A loaded LaunchAgent is not necessarily ready to accept HTTP requests.
    """
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while True:
        try:
            result = _json_get(8040)
            if (isinstance(result, dict)
                    and result.get("router_manager") == "shared-4b"
                    and result.get("loaded") is False):
                return result
            last_error = "unexpected router identity or loaded model weights"
        except (OSError, ValueError, TypeError) as exc:
            last_error = type(exc).__name__
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.25, remaining))
    raise RuntimeError(
        f"Shared 4B gateway not ready after {timeout:g}s ({last_error})"
    )


def enable(backup):
    from agent import memory_model_coordination as ctl
    from agent import memory_model_supervisor as sup
    import runtime_coordinator as rc
    if ROOT.resolve() != (Path.home() / "mlx-web").resolve():
        raise RuntimeError(
            "Activate only from the deployed ~/mlx-web checkout; "
            "the review worktree must never become a live LaunchAgent source"
        )
    _check_backup(backup)
    if not sup.valid_settings():
        raise RuntimeError("Dedicated memory 4B must be configured and installed")
    state = ctl.supervisor_state()
    if not state.get("owned") or state.get("state") not in ("running", "starting"):
        raise RuntimeError("Dedicated memory supervisor is not managing port 8011")
    _idle()
    if not ROUTER_PLIST.is_file() or ROUTER_PLIST.is_symlink():
        raise RuntimeError("A regular router LaunchAgent plist is required")
    before = ROUTER_PLIST.read_bytes()
    if plistlib.loads(before).get("Label") != LABEL:
        raise RuntimeError("Unexpected router LaunchAgent")
    if ctl.on_demand_enabled():
        raise RuntimeError("Already enabled; no router process was changed")
    if LEGACY.exists() and LEGACY.read_bytes() != before:
        raise RuntimeError("Previous router backup differs; review before enabling")

    # Both cross-process locks protect the handoff; no active inference is
    # terminated and the manager has no authority over other model PIDs.
    ctl.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ctl.LOCK.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with rc.runtime_lease(workload="router", timeout=5):
            _idle_without_lease()
            LEGACY.write_bytes(before)
            os.chmod(LEGACY, 0o600)
            try:
                _policy(True)
                _reload(_render_gateway())
                # launchctl confirms service registration, not listener readiness.
                _wait_gateway_ready()
            except BaseException as error:
                try:
                    # A failure after bootstrap must not leave an enabled
                    # policy paired with a missing or incorrect gateway.
                    _reload(before)
                    _policy(False)
                except BaseException as restore_error:
                    raise RuntimeError(
                        "Router switch failed AND automatic legacy restore failed; "
                        "inspect launchd/router state before further changes"
                    ) from restore_error
                raise RuntimeError(
                    "Router switch failed; original router and policy restored"
                ) from error
    return {"enabled": True, "gateway": True, "legacy_saved": str(LEGACY)}


def _idle_without_lease():
    # Called only from the new model lease; checking the lease here would see
    # this control operation itself, which is expected.
    for port in (8030, 8060):
        result = _json_get(port)
        if result.get("active_generation") or result.get("active_job_id"):
            raise RuntimeError(f"Media became busy on {port}")


def rollback():
    from agent import memory_model_coordination as ctl
    import runtime_coordinator as rc
    _idle()
    if not LEGACY.is_file() or LEGACY.is_symlink():
        raise RuntimeError("Original router LaunchAgent not available")
    original = LEGACY.read_bytes()
    if plistlib.loads(original).get("Label") != LABEL:
        raise RuntimeError("Saved router LaunchAgent label mismatch")
    with rc.runtime_lease(workload="router", timeout=5):
        _reload(original)
        _policy(False)
    return {"enabled": False, "router_restored": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--enable", action="store_true")
    modes.add_argument("--rollback", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.exit(2, "macOS required\n")
    try:
        if args.check:
            from agent import memory_model_coordination as ctl
            from agent import memory_model_supervisor as sup
            info = {
                "on_demand": ctl.on_demand_enabled(),
                "dedicated_configured": sup.valid_settings(),
                "supervisor_state": ctl.supervisor_state().get("state"),
                "gateway_healthy": False,
                "backup_present": bool(args.backup and args.backup.is_dir()),
            }
            try:
                info["gateway_healthy"] = _json_get(8040).get("router_manager") == "shared-4b"
            except (OSError, ValueError):
                pass
        elif args.enable:
            info = enable(args.backup)
        else:
            info = rollback()
    except Exception as exc:
        parser.exit(1, f"Router handoff refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps(info))


if __name__ == "__main__":
    main()
