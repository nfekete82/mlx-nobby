"""Direct isolated benchmark controller; dry-run by default, no service endpoints."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .compatibility import inspect_runtime, validate_environment
from .config import COMMITS, DEFAULT_PROMPT, LAB, MODEL, PROFILES, PROJECT, experiment_environment, inside_lab, runtime_path
from .quality import compare
from .runner import input_fingerprint, validate_model
from .setup import production_fingerprint
from .telemetry import preflight, write_json

NEGATIVE = ("deformed mouth, warped lips, extra teeth, duplicated teeth, unstable teeth, "
            "distorted face, identity drift, exaggerated mouth opening, rubbery face, "
            "flicker, jitter, camera movement, zoom, scene change, extra people")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--versions", choices=COMMITS, nargs="+", default=["0.16.3", "0.17.0"])
    p.add_argument("--profiles", choices=PROFILES, nargs="+", default=["production-control"])
    p.add_argument("--pipeline", choices=("t2v", "i2v", "a2v-classic", "a2v-distilled"), default="t2v")
    p.add_argument("--model", type=Path, default=MODEL)
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--prompt-file", type=Path, help="UTF-8 prompt, identical for all versions/profiles")
    p.add_argument("--negative-prompt", default=NEGATIVE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=704)
    p.add_argument("--frames", type=int, default=121)
    p.add_argument("--fps", type=float, default=24)
    p.add_argument("--image", type=Path)
    p.add_argument("--audio", type=Path)
    p.add_argument("--warm-runs", type=int, default=3)
    p.add_argument("--start-mode", choices=("both", "cold", "warm"), default="both",
                   help="both: one cold plus N warm; cold: N+1 fresh processes; warm: cold warmup plus N warm")
    p.add_argument("--min-available-gib", type=float, default=20)
    p.add_argument("--timeout", type=float, default=1800, help="Timeout per generation, seconds")
    p.add_argument("--check", action="store_true", help="Static API and venv metadata checks only")
    p.add_argument("--preflight", action="store_true", help="Read-only resource check; no MLX imports")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approve-gpu", action="store_true", help="Explicit authorization for GPU generation")
    p.add_argument("--compare", nargs=2, metavar=("REFERENCE_JSON", "CANDIDATE_JSON"))
    return p


def request_from_args(args):
    if args.width <= 0 or args.height <= 0 or args.width % 64 or args.height % 64:
        raise ValueError("Two-stage geometry must be positive multiples of 64; no implicit snapping")
    if args.frames < 9 or (args.frames - 1) % 8 or not math.isfinite(args.fps) or args.fps <= 0:
        raise ValueError("Frames must be >=9 and 8n+1; FPS must be positive")
    if (not 0 <= args.seed < 2**31 or not 0 <= args.warm_runs <= 10
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        raise ValueError("Invalid seed, warm run count or timeout")
    if args.start_mode == "warm" and args.warm_runs < 1:
        raise ValueError("Warm mode requires at least one measured warm run")
    if args.pipeline != "t2v" and not args.image:
        raise ValueError("I2V and talking photo tests require --image")
    if args.pipeline.startswith("a2v") and not args.audio:
        raise ValueError("A2V requires --audio")
    if args.pipeline == "t2v" and args.image:
        raise ValueError("Use --pipeline i2v for image-conditioned generation")
    if not args.pipeline.startswith("a2v") and args.audio:
        raise ValueError("Audio input is only supported by A2V")
    for path in (args.image, args.audio, args.prompt_file):
        if path and not path.is_file():
            raise ValueError(f"Input file not found: {path}")
    return {"pipeline": args.pipeline, "model": str(validate_model(args.model)),
            "prompt": args.prompt_file.read_text() if args.prompt_file else args.prompt,
            "negative_prompt": args.negative_prompt, "seed": args.seed,
            "width": args.width, "height": args.height, "frames": args.frames, "fps": args.fps,
            "stage1_steps": 15 if args.pipeline == "a2v-classic" else 8, "stage2_steps": 3,
            "image": str(args.image.resolve()) if args.image else None,
            "audio": str(args.audio.resolve()) if args.audio else None,
            "min_available_gib": args.min_available_gib}


def launch_child(command, environment, log_path, timeout):
    """Only this newly created process group may be cancelled, never production services."""
    with Path(log_path).open("x") as log:
        process = subprocess.Popen(command, cwd=PROJECT, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            raise


def execute(args, base, checks):
    if not args.approve_gpu:
        raise ValueError("--execute requires explicit --approve-gpu; nothing started")
    admission = preflight(args.min_available_gib)
    if not admission["allowed"]:
        raise RuntimeError(f"Resource admission refused: {admission['reasons']}")
    suite = inside_lab(LAB / "results" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]))
    suite.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 1, "status": "running", "input_fingerprint": input_fingerprint(base),
               "admission": admission, "checks": checks, "children": [],
               "nobby_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
               "nobby_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
               "start_mode": args.start_mode, "quality_accepted": None}
    before = production_fingerprint()
    with (LAB / "gpu.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for version in args.versions:
                for profile in args.profiles:
                    if args.pipeline == "a2v-classic" and PROFILES[profile]["sparse"]:
                        raise ValueError("Classic A2V does not use distilled sparse Stage 2")
                    groups = [1] * (args.warm_runs + 1) if args.start_mode == "cold" else [args.warm_runs + 1]
                    for group, count in enumerate(groups):
                        name = f"{version}-{profile}-{group:02d}"
                        request = dict(base, version=version, profile=profile, runtime=str(runtime_path(version)),
                                       output=str(suite / name), runs=count,
                                       first_run_role="warmup" if args.start_mode == "warm" else "measurement")
                        request_file = suite / f"{name}.request.json"
                        write_json(request_file, request)
                        environment = experiment_environment(profile, LAB / "cache")
                        code = [str(runtime_path(version) / ".venv/bin/python"), "-B", "-m", "ltx_lab.runner",
                                "--request-file", str(request_file), "--approve-gpu"]
                        started = time.perf_counter()
                        code_result = launch_child(code, environment, suite / f"{name}.log", args.timeout * count)
                        summary["children"].append({"name": name, "exit_code": code_result,
                                                    "process_wall_seconds": time.perf_counter() - started,
                                                    "results": str(suite / name / "results.json")})
                        write_json(suite / "suite.json", summary)
                        if code_result:
                            raise RuntimeError(f"Child failed; see {suite / (name + '.log')}")
            summary["status"] = "completed"
        except BaseException as exc:
            summary.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            summary["production_unchanged"] = production_fingerprint() == before
            write_json(suite / "suite.json", summary)
    return {"suite": str(suite / "suite.json"), "status": summary["status"]}


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.execute and not args.approve_gpu:
        p.error("--execute requires --approve-gpu; no GPU imports or generation performed")
    if args.preflight:
        print(json.dumps(preflight(args.min_available_gib), indent=2))
        return
    if args.compare:
        output = LAB / "comparisons" / uuid.uuid4().hex
        print(json.dumps(compare(*args.compare, output), indent=2))
        return
    if args.pipeline == "a2v-classic" and any(PROFILES[p]["sparse"] for p in args.profiles):
        p.error("Sparse profiles unsupported for classic A2V")
    checks = {}
    for version in args.versions:
        runtime = runtime_path(version)
        report = inspect_runtime(runtime, version)
        report["environment"] = validate_environment(runtime, version)
        if not report["compatible"]:
            raise ValueError(f"API compatibility check failed: {version}")
        for profile in args.profiles:
            if not report["profiles"][profile]:
                raise ValueError(f"Unsupported profile: {version}/{profile}")
        checks[version] = report
    if args.check:
        print(json.dumps(checks, indent=2))
        return
    base = request_from_args(args)
    if args.execute:
        print(json.dumps(execute(args, base, checks), indent=2))
    else:
        print(json.dumps({"mode": "dry-run", "gpu_started": False, "versions": args.versions,
                          "profiles": args.profiles, "parameters": base,
                          "next": "Run --preflight; execute only after explicit user approval"}, indent=2))


if __name__ == "__main__":
    main()
