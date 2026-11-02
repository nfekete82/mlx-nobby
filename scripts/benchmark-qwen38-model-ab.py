#!/usr/bin/env python3
"""Opt-in, sequential 6-bit vs 4-bit+DFlash2 benchmark on an idle Apple Silicon Mac.

Default action is read-only --plan. A real run requires --confirm-restarts,
a locally available configured 4-bit target and DFlash draft, and an idle
runtime with sufficient memory headroom. The original config is restored
in a finally block. No downloads, parallel large model loads, or default
changes are performed. SIGKILL/power loss cannot be recovered automatically.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts"
MANAGED_KEYS = ("MODEL", "SPECULATIVE_TARGET", "SPECULATIVE_DRAFT_MODEL",
                "SPECULATIVE_DRAFT_KIND", "MLX_CHAT_PERFORMANCE_PROFILE")
KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z_0-9]*)\s*=")
MIN_FREE_PERCENT = 25.0
MIN_HEADROOM_GB = 8.0
MAX_SWAP_GB = 10.0


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_value(content: str, key: str) -> str:
    values = []
    for line in content.splitlines():
        match = KEY_RE.match(line)
        if match and match.group(1) == key:
            tokens = shlex.split(line.split("=", 1)[1], comments=True)
            if len(tokens) != 1:
                raise ValueError(f"Invalid {key} assignment")
            values.append(tokens[0])
    if len(values) > 1:
        raise ValueError(f"Ambiguous duplicate {key}")
    return values[0] if values else ""


def replace_values(content: str, changes: dict[str, str]) -> str:
    if any(k not in MANAGED_KEYS for k in changes):
        raise ValueError("Unsupported config key")
    # Refuse ambiguity rather than editing arbitrary shell syntax.
    for key in MANAGED_KEYS:
        config_value(content, key)
    lines = [line for line in content.splitlines(keepends=True)
             if not (KEY_RE.match(line) and KEY_RE.match(line).group(1) in changes)]
    result = "".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    for key, value in changes.items():
        result += f"{key}={json.dumps(value)}\n"
    return result


def local_model_available(value: str) -> bool:
    if not value:
        return False
    if value.startswith("/") or value.startswith("~/"):
        root = Path(value).expanduser()
        return root.is_dir() and (root / "config.json").is_file()
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*", value):
        return False
    cache = Path(os.environ.get("HF_HUB_CACHE") or (
        Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))) / "hub"))
    snapshots = cache / ("models--" + value.replace("/", "--")) / "snapshots"
    return snapshots.is_dir() and any(p.is_file() for p in snapshots.glob("*/config.json"))


def process_model(command: str) -> str:
    if not command:
        return ""
    argv = shlex.split(command)
    if "mlx_vlm" not in argv or "server" not in argv:
        return ""
    if "--model" not in argv or "--port" not in argv:
        return ""
    return argv[argv.index("--model") + 1] if (
        argv.index("--port") + 1 < len(argv) and argv[argv.index("--port") + 1] == "8000"
        and argv.index("--model") + 1 < len(argv)) else ""


def parse_vm_stat_swap_delta(output: str, seconds: int) -> dict[str, int]:
    """Read the interval row, never cumulative counters from the first row."""
    lines = [line.split() for line in output.splitlines() if line.strip()]
    header_index = next(
        (i for i, cells in enumerate(lines)
         if "swapins" in cells and "swapouts" in cells),
        None,
    )
    if header_index is None or len(lines) < header_index + 3:
        raise ValueError("vm_stat interval rows unavailable")
    header = lines[header_index]
    sample = lines[header_index + 2]
    if len(sample) != len(header):
        raise ValueError("vm_stat interval row shape changed")
    in_token = sample[header.index("swapins")]
    out_token = sample[header.index("swapouts")]
    if not in_token.isascii() or not out_token.isascii() or not (
        in_token.isdecimal() and out_token.isdecimal()
    ):
        raise ValueError("vm_stat interval counters malformed")
    return {
        "window_seconds": seconds,
        "swapins_pages": int(in_token),
        "swapouts_pages": int(out_token),
    }


def sample_swap_activity(seconds: int = 3) -> dict[str, int]:
    """Check actual recent swapping only if macOS still holds old swap pages."""
    result = subprocess.run(
        ["vm_stat", "-c", "2", str(seconds)],
        capture_output=True,
        text=True,
        check=True,
        timeout=seconds + 10,
        env={**os.environ, "LC_ALL": "C"},
    )
    return parse_vm_stat_swap_delta(result.stdout, seconds)


def memory_gate(snapshot: dict, swap_activity: dict | None = None) -> list[str]:
    errors = []
    for key in ("free_percent", "headroom_gb", "swap_used_gb"):
        val = snapshot.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            errors.append(f"{key} unavailable")
    if errors:
        return errors
    if snapshot["free_percent"] < MIN_FREE_PERCENT:
        errors.append(f"free_percent below {MIN_FREE_PERCENT:g}%")
    if snapshot["headroom_gb"] < MIN_HEADROOM_GB:
        errors.append(f"headroom_gb below {MIN_HEADROOM_GB:g}")
    if snapshot.get("pressure") != "normal":
        errors.append("memory pressure is not normal")
    if snapshot["swap_used_gb"] > MAX_SWAP_GB:
        # Swap OCCUPANCY is historical on macOS. Allow a high old allocation
        # only when a new interval contains zero outbound swap pages and ALL
        # regular memory pressure/headroom guards already pass. Missing data
        # fails closed, as does even one recent swapout.
        if not isinstance(swap_activity, dict):
            errors.append(f"swap_used_gb above {MAX_SWAP_GB:g}; swap activity not verified")
        elif (type(swap_activity.get("swapouts_pages")) is not int
              or type(swap_activity.get("window_seconds")) is not int
              or swap_activity["window_seconds"] < 2
              or swap_activity["swapouts_pages"] < 0):
            errors.append("swap activity unavailable or invalid")
        elif swap_activity["swapouts_pages"] != 0:
            errors.append("active swapouts detected")
    return errors


def memory_diagnostics(profile) -> tuple[dict, dict | None, list[str]]:
    snapshot = profile.memory_snapshot()
    activity = None
    used = snapshot.get("swap_used_gb")
    # Only run the interval probe if an otherwise acceptable memory state
    # is blocked exclusively by historical swap occupancy.
    if (type(used) in (int, float) and math.isfinite(used)
            and used > MAX_SWAP_GB
            and snapshot.get("pressure") == "normal"
            and type(snapshot.get("free_percent")) in (int, float)
            and snapshot["free_percent"] >= MIN_FREE_PERCENT
            and type(snapshot.get("headroom_gb")) in (int, float)
            and snapshot["headroom_gb"] >= MIN_HEADROOM_GB):
        try:
            activity = sample_swap_activity()
        except (OSError, ValueError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            # Never expose an upstream command or its raw output.
            activity = {"status": "unavailable"}
    return snapshot, activity, memory_gate(snapshot, activity)


def memory_blockers(profile) -> list[str]:
    return memory_diagnostics(profile)[2]


def idle_error_code(exc: BaseException) -> str:
    """Keep actionable guard reasons without leaking upstream exception payloads."""
    if isinstance(exc, RuntimeError):
        known = (
            ("Agent observatory unavailable", "observatory_unavailable"),
            ("Incomplete runtime status", "runtime_status_incomplete"),
            ("Chat/image/video workload active", "workload_active"),
            ("Media queue active", "media_queue_busy"),
            ("Invalid runtime lease status", "runtime_lease_invalid"),
            ("Runtime lease active or queued", "runtime_lease_busy"),
            ("Runtime lease waiters present", "runtime_lease_waiters"),
        )
        for prefix, code in known:
            if str(exc).startswith(prefix):
                return code
    if isinstance(exc, OSError):
        return "observatory_request_failed"
    return "idle_guard_unavailable"


def preflight(content: str, profile, candidate_model: str | None) -> tuple[dict, list[str]]:
    base = config_value(content, "MODEL")
    target = candidate_model or config_value(content, "SPECULATIVE_TARGET")
    draft = config_value(content, "SPECULATIVE_DRAFT_MODEL")
    checks = []
    if not base or not local_model_available(base):
        checks.append("Current model is not present locally")
    if not target or not local_model_available(target):
        checks.append("Configured candidate model is not present locally")
    if target == base:
        checks.append("Candidate must differ from current model")
    if target != config_value(content, "SPECULATIVE_TARGET"):
        checks.append("Candidate must equal configured DFlash2 target (no unverified drafter pairing)")
    if not draft or not local_model_available(draft):
        checks.append("Configured DFlash2 draft is missing locally")
    if config_value(content, "SPECULATIVE_DRAFT_KIND") != "dflash":
        checks.append("Configured draft kind is not dflash")
    if profile.configured_profile(content) != "default":
        checks.append("Current chat profile must be default; benchmark will not overwrite active experiments")

    status = {"original_model": base, "candidate_model": target, "draft_model": draft,
              "current_profile": profile.configured_profile(content)}
    # Independent read-only probes: a failing idle guard must still BLOCK any
    # active run, but should not hide model/memory diagnostic information.
    try:
        profile.ensure_idle()
        status["idle_check"] = "passed"
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        reason = idle_error_code(exc)
        status["idle_check"] = reason
        checks.append(f"Idle guard blocked ({reason})")

    try:
        args = profile.current_server_args()
        status["running_model"] = process_model(args)
        if process_model(args) != base:
            checks.append("Running chat process model does not match configuration")
        flags = shlex.split(args)
        if "--draft-model" in flags or "--draft-kind" in flags:
            checks.append("Baseline already has a speculative drafter")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        checks.append("Live model process inspection unavailable")

    try:
        health = profile.json_get(profile.SERVER + "/health")
        status["runtime_health"] = {
            "healthy": health.get("status") == "healthy",
            "model_loaded": bool(health.get("loaded_model")),
            "apc_enabled": health.get("apc_enabled") is True,
        }
        if health.get("status") != "healthy" or not health.get("loaded_model"):
            checks.append("Chat server not healthy or not loaded")
        if health.get("apc_enabled") is True:
            checks.append("Baseline APC is active")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        checks.append("Chat server health unavailable")

    try:
        memory, swap_activity, memory_errors = memory_diagnostics(profile)
        status["memory"] = memory
        if swap_activity is not None:
            status["swap_activity"] = swap_activity
        checks.extend(memory_errors)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        checks.append("Agent memory snapshot unavailable")
    return status, checks


def verify_process(profile, expected_model: str, *, dflash: bool) -> None:
    profile.confirm_profile("dflash" if dflash else "default")
    args = profile.current_server_args()
    if process_model(args) != expected_model:
        raise RuntimeError("Live model identity differs from expected target")
    flags = shlex.split(args)
    has_draft = "--draft-model" in flags and "--draft-kind" in flags
    if dflash:
        if not has_draft or flags[flags.index("--draft-kind") + 1] != "dflash":
            raise RuntimeError("DFlash flags absent after candidate restart")
    elif has_draft:
        raise RuntimeError("Baseline unexpectedly has draft flags")


def speed_tests(probe, model: str, samples: int, timeout: int, memory_probe=None) -> dict:
    import httpx
    result = {}
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False) as client:
        for name in ("long", "coding"):
            prompt, limit = probe.PROFILES[name]
            print(f"[model-ab] {name}: {samples} requests, token cap {limit}", file=sys.stderr, flush=True)
            rows = []
            for index in range(1, samples + 1):
                print(f"[model-ab] {name} request {index}/{samples} running...", file=sys.stderr, flush=True)
                row = probe.sample(client, model, timeout, prompt, limit)
                rows.append(row)
                print(
                    f"[model-ab] {name} request {index}/{samples} done: "
                    f"{row['completion_tokens']} tokens, {row['wall_ms']} ms",
                    file=sys.stderr, flush=True,
                )
            result[name] = {
                "samples": len(rows),
                "total_wall_ms": probe.summarize([r["wall_ms"] for r in rows]),
                "generation_tps": probe.summarize(
                    [r["generation_tps"] for r in rows], unit="tokens/s"),
                "completion_tokens": probe.summarize(
                    [r["completion_tokens"] for r in rows], unit="tokens"),
                "finish_reasons": sorted(set(str(r["finish_reason"]) for r in rows)),
                "completion_token_range": [
                    min(r["completion_tokens"] for r in rows),
                    max(r["completion_tokens"] for r in rows),
                ],
            }
            if memory_probe and memory_probe():
                raise RuntimeError("Memory admission failed during speed test")
    return result


def quality_test(output: Path, timeout: int) -> dict:
    subprocess.run(
        [sys.executable, str(SCRIPT / "benchmark-chat-quality.py"), "run",
         "--output", str(output), "--timeout", str(timeout)],
        check=True, cwd=REPO, timeout=60 * 65,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    if report.get("status") != "complete":
        raise RuntimeError("Quality benchmark not complete")
    return report


def save_private(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")


def run(args, profile, probe, quality):
    original = profile.CONFIG.read_text(encoding="utf-8")
    if args.output and (args.output.exists() or args.output.is_symlink()):
        raise FileExistsError("Report output already exists; refusing to overwrite")
    status, failures = preflight(original, profile, args.candidate_model)
    if not args.confirm_restarts:
        print(json.dumps({"plan_only": True, "ready": not failures,
                          "status": status, "blockers": failures,
                          "requires": "--confirm-restarts to run sequentially"},
                         indent=2, ensure_ascii=False))
        return 0
    if failures:
        raise RuntimeError("Preflight blocked: " + "; ".join(failures))
    target = status["candidate_model"]
    candidate = replace_values(original, {
        "MODEL": target,
        "MLX_CHAT_PERFORMANCE_PROFILE": "dflash",
    })
    # No persisted update until the baseline has completed.
    result = {
        "schema": 1, "kind": "sequential_qwen38_model_ab",
        "baseline_model": status["original_model"],
        "candidate_model": target, "draft_model": status["draft_model"],
        "quality": {"status": "not_run"},
        "notes": [
            "Models and tokenizers can differ; tokens/s alone does not establish quality.",
            "Different quantization/checkpoints; no assumption of output parity.",
            "Baseline first, candidate second; thermal/temporal drift is not controlled.",
            "Each run is sequential, no model weights or chat content written to reports.",
            "The original full config is restored, with a chat-only restart.",
        ],
    }
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Benchmark interrupted")
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in handlers:
        signal.signal(sig, interrupted)
    changed = False
    primary_error = None
    try:
        verify_process(profile, status["original_model"], dflash=False)
        profile.ensure_idle()
        result["baseline_before"] = profile.memory_snapshot()
        print("[model-ab] baseline: 6-bit speed probes starting", file=sys.stderr, flush=True)
        result["baseline_speed"] = speed_tests(
            probe, status["original_model"], args.samples, args.timeout, lambda: memory_blockers(profile))
        result["baseline_after"] = profile.memory_snapshot()
        if args.with_quality:
            with tempfile.TemporaryDirectory(prefix="nobby-quality-ab-") as workspace:
                # Capture the baseline and candidate in a secure temporary directory.
                # Keep it alive across the restart for the paired comparison.
                p = Path(workspace)
                baseline_quality = quality_test(p / "baseline.json", args.timeout)
                profile.ensure_idle()
                if memory_blockers(profile):
                    raise RuntimeError("Memory admission failed after baseline")
                if profile.CONFIG.read_text(encoding="utf-8") != original:
                    raise RuntimeError("Config changed externally before candidate")
                print("[model-ab] switching to configured 4-bit DFlash2 target", file=sys.stderr, flush=True)
                profile.write_config(candidate)
                changed = True
                profile.restart()
                verify_process(profile, target, dflash=True)
                profile.ensure_idle()
                result["candidate_before"] = profile.memory_snapshot()
                if memory_blockers(profile):
                    raise RuntimeError("Memory admission failed after candidate start")
                print("[model-ab] candidate: 4-bit DFlash2 speed probes starting", file=sys.stderr, flush=True)
                print("[model-ab] candidate: 4-bit DFlash2 speed probes starting", file=sys.stderr, flush=True)
            result["candidate_speed"] = speed_tests(probe, target, args.samples, args.timeout, lambda: memory_blockers(profile))
                result["candidate_after"] = profile.memory_snapshot()
                candidate_quality = quality_test(p / "candidate.json", args.timeout)
                result["quality"] = quality.compare(baseline_quality, candidate_quality)
        else:
            profile.ensure_idle()
            if memory_blockers(profile):
                raise RuntimeError("Memory admission failed after baseline")
            if profile.CONFIG.read_text(encoding="utf-8") != original:
                raise RuntimeError("Config changed externally before candidate")
            print("[model-ab] switching to configured 4-bit DFlash2 target", file=sys.stderr, flush=True)
            profile.write_config(candidate)
            changed = True
            profile.restart()
            verify_process(profile, target, dflash=True)
            profile.ensure_idle()
            result["candidate_before"] = profile.memory_snapshot()
            if memory_blockers(profile):
                raise RuntimeError("Memory admission failed after candidate start")
            result["candidate_speed"] = speed_tests(probe, target, args.samples, args.timeout, lambda: memory_blockers(profile))
            result["candidate_after"] = profile.memory_snapshot()
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            if changed:
                if profile.CONFIG.read_text(encoding="utf-8") != candidate:
                    raise RuntimeError("Config changed externally; refusing to clobber it during rollback")
                print("[model-ab] restoring original 6-bit configuration", file=sys.stderr, flush=True)
                profile.write_config(original)
                profile.restart()
                verify_process(profile, status["original_model"], dflash=False)
                result["original_config_restored"] = True
            else:
                result["original_config_restored"] = profile.CONFIG.read_text(encoding="utf-8") == original
        except BaseException as restore_error:
            raise RuntimeError("RESTORE FAILED: inspect config and chat server manually") from restore_error
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    if primary_error:
        raise primary_error
    if args.output:
        save_private(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


@contextmanager
def exclusive_runner_lock():
    """Prevent overlapping benchmark runners; unrelated Nobby clients remain protected by idle checks."""
    lock_path = Path.home() / ".config" / "mlx-server" / ".model-ab.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another model A/B run is already in progress") from exc
        yield
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-restarts", action="store_true",
                        help="Explicit opt-in to model switches and two chat server restarts")
    parser.add_argument("--candidate-model", help="Must equal existing configured DFlash2 target")
    parser.add_argument("--samples", type=int, choices=range(2, 11), default=3)
    parser.add_argument("--timeout", type=int, choices=range(30, 601), default=300)
    parser.add_argument("--with-quality", action="store_true",
                        help="Run full 48-case quality suite for each model")
    parser.add_argument("--output", type=Path,
                        help="Private JSON report (must not already exist)")
    args = parser.parse_args(argv)
    profile = load_module("nobby_chat_profile_ab", "chat-performance-profile.py")
    probe = load_module("nobby_chat_latency_ab", "benchmark-chat-latency.py")
    quality = load_module("nobby_chat_quality_ab", "benchmark-chat-quality.py")
    try:
        if args.confirm_restarts:
            with exclusive_runner_lock():
                return run(args, profile, probe, quality)
        return run(args, profile, probe, quality)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError,
            KeyboardInterrupt, TimeoutError) as exc:
        print(f"Model A/B halted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
