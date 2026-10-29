#!/usr/bin/env python3
"""Terminal entry to the same Agent lifecycle adapters; fail closed offline."""
import fcntl
import subprocess
import json
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_lifecycle_gate as gate


def main():
    operation = sys.argv[1]
    if operation == "run":
        gate.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (gate.ROOT / "operation.lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Eine Lifecycle-Aktion läuft bereits; später erneut versuchen")
            command = sys.argv[2:]
            name = Path(command[0]).name
            action = {"rebuild-all.sh": "reboot", "restart-all.sh": "restart-all",
                      "shutdown-ai.sh": "shutdown-ai"}.get(name)
            if name == "mlx":
                action = "restart-all" if command[1] == "restart-all" else "shutdown-ai"
            result = subprocess.call(command, env={**os.environ, "MLX_LIFECYCLE_LOCKED": "1",
                                                  "MLX_LIFECYCLE_ACTION": action or "shutdown-ai"})
            if result:
                gate.set_blocked(True, "Lifecycle helper failed")
            raise SystemExit(result)
    if operation not in {"quiesce", "verify-stopped", "resume"}:
        raise ValueError("Unsupported lifecycle operation")
    if operation == "quiesce":
        gate.set_blocked(True, "Terminal shutdown")
    request = urllib.request.Request(
        os.environ.get("MLX_NOBBY_AGENT_URL", "http://127.0.0.1:8010").rstrip("/")
        + "/api/system/ai/" + operation,
        data=json.dumps({"action": os.environ.get("MLX_LIFECYCLE_ACTION")}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    expected = {"quiesce": "quiesced", "verify-stopped": "verified", "resume": "ready"}[operation]
    if payload.get(expected) is not True:
        raise RuntimeError(f"Agent hat {operation} nicht bestätigt: {payload}")
    if operation in {"verify-stopped", "resume"} and os.environ.get("MLX_LIFECYCLE_HOLD") != "1":
        action = os.environ.get("MLX_LIFECYCLE_ACTION", "shutdown-ai" if operation == "verify-stopped" else "restart-all")
        completion = {"action": action, "state": "completed", "phase": "completed", "current": 6, "total": 6,
                      "message": "KI-Dienste verifiziert gestoppt" if operation == "verify-stopped" else "Dienste und APIs verifiziert bereit"}
        request = urllib.request.Request(os.environ.get("MLX_NOBBY_AGENT_URL", "http://127.0.0.1:8010").rstrip("/")
                                         + "/api/system/lifecycle/progress", data=json.dumps(completion).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        gate.set_blocked(True, str(exc))
        print(f"Lifecycle fehlgeschlagen, Jobannahme bleibt gesperrt: {exc}", file=sys.stderr)
        raise SystemExit(1)
