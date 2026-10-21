#!/usr/bin/env python3
"""Read-only release decision for the staged LTX 0.17.0 admission upgrade.

No model imports, requests that mutate servers, service controls or GPU jobs.
A NO-GO is actionable evidence; do not disable the admission gate to force GO.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def assess(*, lab_root=None, admission_check=None, memory_check=None):
    from ltx_lab.config import COMMITS
    from ltx_lab.telemetry import preflight
    from ltx_lab.admission import Gate
    from ltx_lab.exclusive import verify_services

    lab_root = Path(lab_root or Path.home() / "mlx-web/.ltx-lab")
    report = {"status": "NO-GO", "branch": "feature/ltx-performance-lab-v017",
              "lab_root": str(lab_root), "checks": {},
              "note": "CPU/read-only diagnosis, not permission to auto-deploy or run GPU"}
    checks = report["checks"]
    for version, expected in COMMITS.items():
        runtime = lab_root / ("runtime-v" + version)
        try:
            found = subprocess.check_output(
                ["git", "-C", str(runtime), "rev-parse", "HEAD"], text=True, timeout=5).strip()
            clean = not subprocess.check_output(
                ["git", "-C", str(runtime), "status", "--porcelain", "--untracked-files=no"],
                text=True, timeout=5).strip()
            ready = (runtime / ".venv/bin/python").is_file()
            checks["runtime_" + version] = {
                "ok": found == expected and clean and ready,
                "pinned_commit": found == expected, "clean_checkout": clean,
                "venv_exists": ready}
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            checks["runtime_" + version] = {"ok": False, "reason": type(exc).__name__}
    try:
        admission_check = admission_check or (lambda: verify_services(Gate()))
        proof = admission_check()
        checks["all_listener_admission"] = {"ok": True, "verified_roles": sorted(proof)}
    except Exception as exc:
        checks["all_listener_admission"] = {"ok": False, "reason": str(exc)[:400]}
    try:
        memory_check = memory_check or preflight
        memory = memory_check()
        checks["memory_admission"] = {
            "ok": memory.get("allowed") is True,
            "reasons": memory.get("reasons", [])}
    except Exception as exc:
        checks["memory_admission"] = {"ok": False, "reason": str(exc)[:400]}
    # Note: even all static checks passing cannot prove end-to-end recovery,
    # full deployment, video quality or post-test production safety.
    report["all_readonly_checks_passed"] = all(x["ok"] for x in checks.values())
    report["remaining_requirements"] = [
        "Validated one-session exclusive admission + worker/recovery integration",
        "One real 0.16.3 vs 0.17.0 GPU A/B run with quality review",
        "Separate approved production activation and rollback verification",
    ]
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lab-root", type=Path, default=None)
    args = p.parse_args(argv)
    result = assess(lab_root=args.lab_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Return a nonzero code until the complete *manual* release gate is accepted.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
