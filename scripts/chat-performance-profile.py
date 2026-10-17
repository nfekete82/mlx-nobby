#!/usr/bin/env python3
"""Opt-in local chat performance profiles and reversible A/B benchmarking.

Profiles are overlays applied ONLY by scripts/mlx-server-start. Switching modes
changes one standalone key in the user's local config and restarts ONLY the
chat model server through the existing mlx CLI (including its RAM guard).
No model downloads, media restarts, or settings PATCH to the model server.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
from urllib.request import urlopen


REPO = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / ".config" / "mlx-server" / "config"
KEY = "MLX_CHAT_PERFORMANCE_PROFILE"
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?MLX_CHAT_PERFORMANCE_PROFILE\s*=")
AGENT = "http://127.0.0.1:8010"
SERVER = "http://127.0.0.1:8000"
PROFILES = ("default", "dflash", "apc")


def configured_profile(content: str) -> str:
    found = [line for line in content.splitlines() if ASSIGNMENT.match(line)]
    if len(found) > 1:
        raise ValueError("Multiple performance profile settings; refusing to edit")
    if not found:
        return "default"
    value = found[0].split("=", 1)[1].strip()
    try:
        parts = shlex.split(value, comments=True)
    except ValueError as exc:
        raise ValueError("Invalid performance profile value") from exc
    if len(parts) != 1 or parts[0] not in PROFILES:
        raise ValueError("Unknown/invalid performance profile: refusing to edit")
    return parts[0]


def updated_config(content: str, mode: str) -> str:
    if mode not in PROFILES:
        raise ValueError("Unknown profile")
    configured_profile(content)  # validates single managed key
    lines = [line for line in content.splitlines(keepends=True)
             if not ASSIGNMENT.match(line)]
    clean = "".join(lines)
    if mode == "default":
        return clean
    if clean and not clean.endswith("\n"):
        clean += "\n"
    return clean + f'{KEY}="{mode}"\n'


def write_config(content: str, config: Path = CONFIG) -> None:
    """Atomic, user-only replacement preserving file permission bits."""
    mode = stat.S_IMODE(config.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=".chat-profile-", dir=config.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, config)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_get(url: str, timeout: int = 12) -> dict:
    if not (url.startswith(AGENT + "/") or url.startswith(SERVER + "/")):
        raise ValueError("Only local known Nobby API endpoints are permitted")
    with urlopen(url, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Unexpected Nobby API response")
    return data


def ensure_idle() -> None:
    snapshot = json_get(AGENT + "/api/performance/observatory?limit=1")
    if snapshot.get("ok") is not True:
        raise RuntimeError("Agent observatory unavailable; no profile change made")
    system = snapshot.get("system") or {}
    runtimes = system.get("runtimes")
    if not isinstance(runtimes, dict) or any(
        kind not in runtimes for kind in ("chat", "image", "video")
    ):
        raise RuntimeError("Incomplete runtime status; refusing profile change")
    if any((runtimes[kind] or {}).get("active") for kind in ("chat", "image", "video")):
        raise RuntimeError("Chat/image/video workload active; wait before switching")
    media = snapshot.get("media") or {}
    if int(media.get("active_count") or 0) or int(media.get("waiting_count") or 0):
        raise RuntimeError("Media queue active; wait before switching")
    lease = system.get("runtime_lease") or {}
    if not isinstance(lease, dict):
        raise RuntimeError("Invalid runtime lease status")
    if lease.get("active") or int(lease.get("waiting_count") or 0):
        raise RuntimeError("Runtime lease active or queued; wait before switching")
    if lease.get("waiting"):
        raise RuntimeError("Runtime lease waiters present")


def current_server_args() -> str:
    result = subprocess.run(
        ["ps", "-axo", "command"], capture_output=True, text=True, check=True
    )
    return next((line for line in result.stdout.splitlines()
                 if "mlx_vlm server" in line and
                 re.search(r"--port\s+8000(?:\s|$)", line)), "")


def preflight(mode: str) -> None:
    if mode == "default":
        return
    args = current_server_args()
    if not args:
        raise RuntimeError("Chat server must be running mlx_vlm on port 8000")
    health = json_get(SERVER + "/health")
    if health.get("status") != "healthy" or not health.get("loaded_model"):
        raise RuntimeError("Chat server must have an active model")
    if mode == "dflash":
        if "--draft-model" not in args or "--draft-kind dflash" not in args:
            # Requiring a live DFlash starter avoids silently selecting a
            # non-working draft or accepting model role drift.
            # The comparison starts with known-working DFlash.
            raise RuntimeError("DFlash2 must already be active for first selection")


def confirm_profile(mode: str) -> None:
    health = json_get(SERVER + "/health")
    if health.get("status") != "healthy" or not health.get("loaded_model"):
        raise RuntimeError("Restart returned no healthy loaded model")
    if mode == "apc":
        if health.get("apc_enabled") is not True:
            raise RuntimeError("APC not enabled after restart")
        if "--draft-model" in current_server_args():
            raise RuntimeError("Unexpected speculative model still active")
    if mode == "dflash":
        if health.get("apc_enabled") is True:
            raise RuntimeError("APC still enabled in DFlash2 mode")
        args = current_server_args()
        if "--draft-model" not in args or "--draft-kind dflash" not in args:
            raise RuntimeError("DFlash2 not active after restart")


def restart() -> None:
    subprocess.run(["bash", str(REPO / "scripts" / "mlx"), "restart"],
                   check=True, cwd=REPO)


def switch_profile(mode: str, *, verify_idle: bool = True) -> bool:
    """On failure revert the entire original config, then restart safely."""
    if mode not in PROFILES:
        raise ValueError("Unknown profile")
    original = CONFIG.read_text(encoding="utf-8")
    prior = configured_profile(original)
    if prior == mode:
        return False
    if verify_idle:
        ensure_idle()
    if mode != "default":
        # On transitions from the other profile, validate server health; on
        # first selection of DFlash require existing verified live drafter.
        if prior == "default":
            preflight(mode)
        elif not current_server_args():
            raise RuntimeError("Chat server not running; refusing mode change")
    write_config(updated_config(original, mode))
    try:
        restart()
        confirm_profile(mode)
    except BaseException:
        print("Profile change failed; restoring previous configuration...", file=sys.stderr)
        try:
            write_config(original)
            restart()
            confirm_profile(prior)
        except Exception as rollback_error:
            print(f"Automatic recovery also failed: {type(rollback_error).__name__}. "
                  "Inspect the MLX server and config.", file=sys.stderr)
        raise
    return True


def profile_status() -> None:
    mode = configured_profile(CONFIG.read_text(encoding="utf-8"))
    print("Configured chat profile:", mode)
    try:
        health = json_get(SERVER + "/health")
        args = current_server_args()
        print("Model loaded:", bool(health.get("loaded_model")))
        print("APC enabled:", health.get("apc_enabled"))
        print("DFlash2 process flag:", "--draft-kind dflash" in args and
              "--draft-model" in args)
        if health.get("apc_enabled"):
            cache = json_get(SERVER + "/v1/cache/stats")
            print("APC exact hits:", cache.get("exact_hits"))
            print("APC matched tokens:", cache.get("matched_tokens"))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Server status unavailable: {type(exc).__name__}: {exc}")


def load_benchmark():
    location = REPO / "scripts" / "benchmark-chat-experience.py"
    spec = importlib.util.spec_from_file_location("chat_experience", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compact_result(report: dict) -> dict:
    return {
        "short": {
            "first_content_ms": report["short"]["first_content_ms"],
            "total_ms": report["short"]["total_ms"],
            "output_characters": report["short"]["samples"][-1]["output_characters"],
        },
        "contexts": [
            {
                "nominal_context_tokens": experiment["nominal_context_tokens"],
                "priming": experiment["priming"],
                "same_prefix_followup": experiment["same_prefix_followup"],
                "different_prefix_control": experiment["different_prefix_control"],
            } for experiment in report["contexts"]
        ],
    }


def compare(args) -> dict:
    previous = configured_profile(CONFIG.read_text(encoding="utf-8"))
    ensure_idle()
    # Check the running server is the expected currently configured mode.
    # This may be called only when a working DFlash process is active, because
    # enabling DFlash on a different unknown model would not be safe.
    preflight("dflash")
    benchmark = load_benchmark()
    original_signal = {}
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGINT):
        original_signal[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupted)
    results = {}
    try:
        for profile in ("dflash", "apc"):
            print(f"\nTesting {profile} (long answers)...", file=sys.stderr, flush=True)
            switch_profile(profile)
            # Use the same public synthetic workload, and don't save
            # completion text, traces, or user messages.
            report = benchmark.run(
                AGENT, args.context_sizes, args.samples,
                args.max_tokens, args.timeout, answer_profile="long"
            )
            results[profile] = compact_result(report)
    finally:
        try:
            if configured_profile(CONFIG.read_text(encoding="utf-8")) != previous:
                switch_profile(previous)
        finally:
            for signum, previous_handler in original_signal.items():
                signal.signal(signum, previous_handler)
    return {
        "schema": 1,
        "kind": "opt_in_chat_profile_comparison",
        "max_tokens": args.max_tokens,
        "nominal_context_sizes": args.context_sizes,
        "starting_profile_restored": previous,
        "results": results,
        "notes": [
            "DFlash2 ON+APC OFF versus APC ON+DFlash2 OFF; model switches not requested.",
            "Reports contain synthetic latency metadata only, never model text.",
            "Answers may terminate before max_tokens; report output characters, not exact token counts.",
            "Long-context sizes are estimated, not model-tokenizer exact.",
            "Order is fixed and cannot isolate thermal drift; repeat with controls.",
            "APC exact-cache resident memory is not captured by blockpool resident_bytes.",
            "Profile switching restarts ONLY the chat server through the existing guard.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "default", "dflash", "apc"):
        commands.add_parser(name)
    compare_cmd = commands.add_parser("compare")
    compare_cmd.add_argument("--context-sizes", type=load_benchmark().context_sizes,
                             default=[4000])
    compare_cmd.add_argument("--samples", type=int, choices=range(1, 7), default=2)
    compare_cmd.add_argument("--max-tokens", type=int, choices=range(128, 769),
                             default=384)
    compare_cmd.add_argument("--timeout", type=int, default=300)
    compare_cmd.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    try:
        if options.command == "status":
            profile_status()
        elif options.command == "compare":
            if not (10 <= options.timeout <= 900):
                raise ValueError("--timeout must be between 10 and 900 seconds")
            report = compare(options)
            if options.output:
                load_benchmark().save_private(options.output, report)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            changed = switch_profile(options.command)
            print(("Activated: " if changed else "Already active: ") + options.command)
            profile_status()
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        print(f"Profile operation stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
