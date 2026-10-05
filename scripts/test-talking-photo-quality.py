#!/usr/bin/env python3
"""Run a real local Talking Photo Quality smoke test through the Agent API."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


DEFAULT_AGENT_URL = "http://127.0.0.1:8010"
DEFAULT_TEXT = "Hallo, das ist ein kurzer LTX Qualitätstest."


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--image", required=True, help="PNG or JPEG portrait")
    value.add_argument("--text", default=DEFAULT_TEXT)
    value.add_argument("--voice")
    value.add_argument("--language", default="de")
    value.add_argument("--output", default=str(Path.home() / "Downloads/talking-photo-ltx-quality.mp4"))
    value.add_argument("--agent-url", default=DEFAULT_AGENT_URL)
    value.add_argument("--timeout", type=float, default=3600.0)
    return value


def json_request(base: str, method: str, path: str, payload=None, timeout=30):
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[-3000:]}") from exc


def image_data_url(path: Path) -> str:
    payload = path.read_bytes()
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif payload.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise RuntimeError("Only PNG and JPEG portraits are supported")
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def download(base: str, path: str, output: Path) -> None:
    request = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "video/mp4"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if len(data) < 32 or b"ftyp" not in data[:32]:
        raise RuntimeError("Agent returned no valid MP4")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)


def main() -> int:
    args = parser().parse_args()
    image = Path(args.image).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not image.is_file():
        raise SystemExit(f"Image not found: {image}")

    status = json_request(args.agent_url, "GET", "/api/talking-photo/status", timeout=10)
    quality = ((status.get("providers") or {}).get("quality") or {})
    if not quality.get("ready"):
        raise SystemExit(quality.get("detail") or "LTX Talking Photo Quality is not ready")

    body = {
        "image_data_url": image_data_url(image),
        "text": args.text,
        "voice": args.voice,
        "language": args.language,
        "speed": 1.0,
        "motion": "none",
        "engine": "quality",
    }
    job = json_request(args.agent_url, "POST", "/api/talking-photo/jobs", body, timeout=30)
    job_id = str(job.get("id") or "")
    if not job_id:
        raise SystemExit("Agent returned no Talking Photo job id")
    print(f"job={job_id}", flush=True)

    deadline = time.monotonic() + args.timeout
    previous = None
    try:
        while time.monotonic() < deadline:
            job = json_request(args.agent_url, "GET", f"/api/talking-photo/jobs/{job_id}", timeout=15)
            marker = (
                job.get("status"),
                job.get("phase"),
                round(float(job.get("progress") or 0), 3),
            )
            if marker != previous:
                print(f"status={marker[0]} phase={marker[1]} progress={marker[2]:.3f}", flush=True)
                previous = marker
            if job.get("status") == "completed":
                video_url = str((job.get("result") or {}).get("video_url") or "")
                if not video_url:
                    raise RuntimeError("Completed job has no video URL")
                download(args.agent_url, video_url, output)
                print(f"saved={output}")
                print(json.dumps(job.get("result") or {}, ensure_ascii=False, indent=2))
                return 0
            if job.get("status") in {"failed", "cancelled"}:
                raise RuntimeError(str(job.get("error") or job.get("status")))
            time.sleep(1.0)
    except KeyboardInterrupt:
        try:
            json_request(
                args.agent_url,
                "POST",
                f"/api/talking-photo/jobs/{job_id}/cancel",
                {},
                timeout=10,
            )
        except Exception:
            pass
        print("Cancelled.", file=sys.stderr)
        return 130

    raise RuntimeError("Talking Photo Quality smoke test timed out")


if __name__ == "__main__":
    raise SystemExit(main())
