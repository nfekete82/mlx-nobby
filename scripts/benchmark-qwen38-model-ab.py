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


def memory_gate(snapshot: dict) -> list[str]:
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
    if snapshot["swap_used_gb"] > MAX_SWAP_GB:
        errors.append(f"swap_used_gb above {MAX_SWAP_GB:g}")
    if snapshot.get("pressure") != "normal":
        errors.append("memory pressure is not normal")
    return errors


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
    try:
        profile.ensure_idle()
        args = profile.current_server_args()
        status["running_model"] = process_model(args)
        if process_model(args) != base:
            checks.append("Running chat process model does not match configuration")
        if "--draft-model" in shlex.split(args) or "--draft-kind" in shlex.split(args):
            checks.append("Baseline already has a speculative drafter")
        health = profile.json_get(profile.SERVER + "/health")
        if health.get("status") != "healthy" or not health.get("loaded_model"):
            checks.append("Chat server not healthy or not loaded")
        if health.get("apc_enabled") is True:
            checks.append("Baseline APC is active")
        memory = profile.memory_snapshot()
        status["memory"] = memory
        checks.extend(memory_gate(memory))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        checks.append(f"Live preflight unavailable ({type(exc).__name__})")
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
            rows = [probe.sample(client, model, timeout, prompt, limit)
                    for _ in range(samples)]
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
            if memory_probe and memory_gate(memory_probe()):
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
        result["baseline_speed"] = speed_tests(
            probe, status["original_model"], args.samples, args.timeout, profile.memory_snapshot)
        result["baseline_after"] = profile.memory_snapshot()
        if args.with_quality:
            with tempfile.TemporaryDirectory(prefix="nobby-quality-ab-") as workspace:
                # Capture the baseline and candidate in a secure temporary directory.
                # Keep it alive across the restart for the paired comparison.
                p = Path(workspace)
                baseline_quality = quality_test(p / "baseline.json", args.timeout)
                profile.ensure_idle()
                if memory_gate(profile.memory_snapshot()):
                    raise RuntimeError("Memory admission failed after baseline")
                if profile.CONFIG.read_text(encoding="utf-8") != original:
                    raise RuntimeError("Config changed externally before candidate")
                profile.write_config(candidate)
                changed = True
                profile.restart()
                verify_process(profile, target, dflash=True)
                profile.ensure_idle()
                result["candidate_before"] = profile.memory_snapshot()
                if memory_gate(result["candidate_before"]):
                    raise RuntimeError("Memory admission failed after candidate start")
                result["candidate_speed"] = speed_tests(probe, target, args.samples, args.timeout, profile.memory_snapshot)
                result["candidate_after"] = profile.memory_snapshot()
                candidate_quality = quality_test(p / "candidate.json", args.timeout)
                result["quality"] = quality.compare(baseline_quality, candidate_quality)
        else:
            profile.ensure_idle()
            if memory_gate(profile.memory_snapshot()):
                raise RuntimeError("Memory admission failed after baseline")
            if profile.CONFIG.read_text(encoding="utf-8") != original:
                raise RuntimeError("Config changed externally before candidate")
            profile.write_config(candidate)
            changed = True
            profile.restart()
            verify_process(profile, target, dflash=True)
            profile.ensure_idle()
            result["candidate_before"] = profile.memory_snapshot()
            if memory_gate(result["candidate_before"]):
                raise RuntimeError("Memory admission failed after candidate start")
            result["candidate_speed"] = speed_tests(probe, target, args.samples, args.timeout, profile.memory_snapshot)
                result["candidate_after"] = profile.memory_snapshot()
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            if changed:
                if profile.CONFIG.read_text(encoding="utf-8") != candidate:
                    raise RuntimeError("Config changed externally; refusing to clobber it during rollback")
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
