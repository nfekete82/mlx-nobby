#!/usr/bin/env python3
"""Block or delay local ML model loads when unified-memory admission is unsafe."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import runtime_coordinator


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", required=True)
    parser.add_argument("--reserve-gb", type=float, default=None)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser.parse_args()


def main():
    args = parse_args()
    poll = max(0.5, min(float(args.poll_seconds), 60.0))
    reported = False

    while True:
        try:
            snapshot = runtime_coordinator.ensure_model_load_allowed(
                args.workload,
                reserve_gb=args.reserve_gb,
            )
            if reported:
                free_percent = snapshot.get("free_percent")
                print(
                    "[runtime-memory] model load admitted"
                    + (
                        f"; free={float(free_percent):.1f}%"
                        if isinstance(free_percent, (int, float))
                        else ""
                    ),
                    flush=True,
                )
            return 0
        except RuntimeError as exc:
            if not args.wait:
                print(str(exc), file=sys.stderr, flush=True)
                return 75
            if not reported:
                print(
                    f"[runtime-memory] waiting before {args.workload}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                reported = True
            time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main())
