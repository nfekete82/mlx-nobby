"""Regression for the primary model server PID on macOS.

No actual MLX processes are started; listener lookup and ps are mocked in Bash.
"""
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mlx"


def _pid_function():
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^get_mlx_pid\(\) \{\n.*?^\}", source)
    assert match, "get_mlx_pid function missing"
    return match.group(0)


def _detect_pid(command, *, listening=True):
    # Intercept both commands so these tests run on Linux CI without lsof
    # and never inspect or control the developer's real model server.
    script = r'''
PORT=8000
lsof() {
    case " $* " in
        *" -tiTCP:8000 "*) if [ "$MOCK_LISTENING" = "yes" ]; then printf '4242\n'; fi ;;
        *) return 1 ;;
    esac
}
ps() {
    if [[ " $* " == *" -p 4242 "* ]]; then
        printf '%s\n' "$MOCK_COMMAND"
    else
        return 1
    fi
}
''' + _pid_function() + "\nget_mlx_pid\n"
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
        env={
            **os.environ,
            "MOCK_COMMAND": command,
            "MOCK_LISTENING": "yes" if listening else "no",
        },
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("command", [
    "/opt/runtime/bin/python -m mlx_lm.server --model /models/qwen --host 127.0.0.1 --port 8000",
    "/opt/runtime/bin/python -m mlx_vlm server --model /models/qwen-vl --host 127.0.0.1 --port 8000",
])
def test_detects_both_primary_server_backends(command):
    assert _detect_pid(command) == "4242"


@pytest.mark.parametrize("command", [
    "/opt/runtime/bin/python -m uvicorn other.app:app --port 8000",
    "/opt/runtime/bin/python -m mlx_vlm.server --port 8000",
    "/opt/runtime/bin/python -m mlx_vlm server --host 127.0.0.1 --port 8040",
])
def test_does_not_accept_other_listener_commands(command):
    # Even if a foreign process occupies port 8000, don't claim MLX is running.
    # Note: a port-8040 server cannot actually listen on port 8000; this
    # synthetic case also verifies that lookup is based on the listener.
    if "8040" in command:
        assert _detect_pid(command, listening=False) == ""
    else:
        assert _detect_pid(command) == ""


def test_no_listener_means_no_primary_model_process():
    command = "/opt/runtime/bin/python -m mlx_vlm server --port 8040"
    assert _detect_pid(command, listening=False) == ""


def test_shell_syntax_is_valid():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=5)
