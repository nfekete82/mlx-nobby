#!/usr/bin/env python3
"""Run the staged 0.18.0 persistent Nobby worker in isolation.

Tests Nobby's real worker HTTP generation path with optional two keyframes.
Does not restart launchd, change model files, or select a new production runtime.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request


STAGED_ROOT = Path.home() / ".local/share/mlx-nobby/ltx-2-mlx-v0.18.0"
MODEL_ROOT = Path.home() / ".local/share/mlx-nobby/models/ltx-2.5-mlx-q4"
PRODUCTION_HEALTH = "http://127.0.0.1:8060/health"


def request(url, token=None, payload=None, timeout=5):
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    encoded = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=encoded, headers=headers,
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def ensure_idle():
    try:
        status = request(PRODUCTION_HEALTH)
    except Exception as exc:
        raise SystemExit(f"STOP: Produktiver Videodienst ist nicht erreichbar: {exc}") from exc
    if not status.get("ok") or status.get("status") != "ready" or status.get("active_job_id"):
        raise SystemExit("STOP: Produktiver Videodienst beschäftigt. Kein Parallelbenchmark.")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-image", type=Path)
    parser.add_argument("--end-image", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=49)
    args = parser.parse_args()

    if bool(args.start_image) != bool(args.end_image):
        parser.error("--start-image und --end-image müssen zusammen angegeben werden")
    if args.frames < 17 or (args.frames - 1) % 8 != 0 or args.frames > 121:
        parser.error("--frames muss 8k+1 im Bereich 17..121 sein")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"STOP: Zieldatei existiert bereits: {output}")
    images = []
    if args.start_image:
        for value in (args.start_image, args.end_image):
            path = value.expanduser().resolve()
            if not path.is_file() or path.is_symlink():
                raise SystemExit(f"STOP: Referenzbild fehlt oder ist ein Symlink: {path}")
        images = [
            {"path": str(args.start_image.expanduser().resolve()), "frame_index": 0, "strength": 1.0},
            {"path": str(args.end_image.expanduser().resolve()), "frame_index": args.frames - 1, "strength": 1.0},
        ]
    python = STAGED_ROOT / ".venv/bin/python"
    worker = Path(__file__).resolve().parents[1] / "video_mlx_worker.py"
    for path in (python, worker, MODEL_ROOT / "embedded_config.json"):
        if not path.is_file():
            raise SystemExit(f"STOP: Datei fehlt: {path}")
    ensure_idle()
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix(".worker.log")
    if log.exists():
        raise SystemExit(f"STOP: Logdatei existiert bereits: {log}")
    port = free_port()
    token = secrets.token_hex(24)
    url = f"http://127.0.0.1:{port}"
    environment = dict(os.environ)
    environment.update({
        "LTX_MLX_WORKER_HOST": "127.0.0.1",
        "LTX_MLX_WORKER_PORT": str(port),
        "LTX_MLX_AUTH_TOKEN": token,
        "LTX_MLX_MODEL_DIR": str(MODEL_ROOT),
        "LTX_MLX_LOW_RAM": "1",
        "LTX_MLX_PARENT_PID": str(os.getpid()),
    })
    print(f"Staging worker port: {port}", flush=True)
    print(f"Video: {output}", flush=True)
    print(f"Log: {log}", flush=True)

    with log.open("xb") as log_file:
        process = subprocess.Popen([str(python), str(worker)], env=environment,
                                   cwd=str(STAGED_ROOT), stdout=log_file, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Staging-Worker beendet (Exit {process.returncode}). Siehe {log}")
                try:
                    health = request(url + "/health", token, timeout=2)
                    if health.get("ok"):
                        break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Staging-Worker hat den Health-Check nicht bestanden")

            data = {
                "prompt": "Smooth cinematic movement over a desert fortress; consistent buildings and natural lighting",
                "output": str(output),
                "width": 704, "height": 480,
                "frames": args.frames, "fps": 24,
                "seed": 12345, "stage1_steps": 8, "stage2_steps": 3,
                "image": None, "images": images, "profile": "standard",
            }
            print(f"Worker bereit, generiere {args.frames} Frames mit {len(images)} Referenzen", flush=True)
            started = time.monotonic()
            result = request(url + "/generate", token, data, timeout=900)
            seconds = time.monotonic() - started
            if not result.get("ok") or not output.is_file() or output.stat().st_size < 32:
                raise RuntimeError(f"Worker-Generierung fehlgeschlagen: {result}")
            if b"ftyp" not in output.read_bytes()[:32]:
                raise RuntimeError("Worker lieferte kein MP4")
            print(json.dumps({
                "ok": True,
                "runtime": "ltx-2-mlx 0.18.0", "mode": "isolated Nobby persistent worker",
                "seconds": round(seconds, 2), "bytes": output.stat().st_size,
                "images": len(images), "output": str(output),
            }, ensure_ascii=False, indent=2), flush=True)
        except Exception:
            print(f"Fehlerdetails: {log}", file=sys.stderr)
            raise
        finally:
            # Only terminate the child we created. Never touch the live 8060 service.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
