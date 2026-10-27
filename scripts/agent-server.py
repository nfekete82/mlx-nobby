#!/usr/bin/env python3
"""Run the native Agent with bounded stdout/stderr and normal uvicorn signals."""

from pathlib import Path
import os
import runpy
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path(os.environ.get("MLX_AGENT_LOG_DIR", str(ROOT)))
sys.path.insert(0, str(ROOT))

from agent.log_rotation import RotatingLog, capture_output


def main():
    try:
        with capture_output(1, LOG_DIR / "agent.log"), capture_output(2, LOG_DIR / "agent-error.log"):
            runpy.run_module("uvicorn", run_name="__main__", alter_sys=True)
    except Exception:
        # Setup errors must also be inspectable with launchd output at /dev/null.
        log = RotatingLog(LOG_DIR / "agent-error.log")
        try:
            log.write(traceback.format_exc().encode("utf-8"))
        finally:
            log.close()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
