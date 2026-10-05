"""Web-backend proxy routes for the local Talking Photo feature."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from fastapi import HTTPException, Request, Response


_ID = re.compile(r"^[a-f0-9]{24}$")


def _validated_id(value: str) -> str:
    value = str(value or "")
    if not _ID.fullmatch(value):
        raise HTTPException(422, "Ungültige Talking-Photo-ID")
    return value


def _detail(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        return str(json.loads(body).get("detail") or body)
    except Exception:
        return body


async def _proxy(
    request: Request,
    agent_url: str,
    path: str,
    *,
    timeout: int = 30,
) -> Response:
    body = await request.body()
    headers = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    query = str(request.url.query or "")
    upstream_path = path + (("?" + query) if query and "?" not in path else "")
    upstream_request = urllib.request.Request(
        f"{agent_url.rstrip('/')}{upstream_path}",
        data=body if body else None,
        headers=headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(upstream_request, timeout=timeout) as upstream:
            payload = upstream.read()
            response_headers = {"Cache-Control": "no-store"}
            disposition = upstream.headers.get("Content-Disposition")
            if disposition:
                response_headers["Content-Disposition"] = disposition
            return Response(
                content=payload,
                status_code=getattr(upstream, "status", 200),
                media_type=upstream.headers.get("Content-Type", "application/json"),
                headers=response_headers,
            )
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, _detail(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Agent nicht erreichbar") from exc


def install_routes(app, agent_url: str):
    methods_by_path = {
        (getattr(route, "path", None), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }

    if ("/api/talking-photo/status", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/status")
        async def talking_photo_status(request: Request):
            return await _proxy(
                request, agent_url, "/api/talking-photo/status", timeout=5,
            )

    if ("/api/talking-photo/jobs", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs", status_code=202)
        async def talking_photo_create(request: Request):
            return await _proxy(
                request, agent_url, "/api/talking-photo/jobs", timeout=15,
            )

    if ("/api/talking-photo/jobs/{job_id}", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/jobs/{job_id}")
        async def talking_photo_job(job_id: str, request: Request):
            job_id = _validated_id(job_id)
            return await _proxy(
                request, agent_url, f"/api/talking-photo/jobs/{job_id}", timeout=15,
            )

    if ("/api/talking-photo/jobs/{job_id}/cancel", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/cancel")
        async def talking_photo_cancel(job_id: str, request: Request):
            job_id = _validated_id(job_id)
            return await _proxy(
                request,
                agent_url,
                f"/api/talking-photo/jobs/{job_id}/cancel",
                timeout=15,
            )

    if ("/api/talking-photo/jobs/{job_id}/keep", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/keep")
        async def talking_photo_keep(job_id: str, request: Request):
            job_id = _validated_id(job_id)
            return await _proxy(
                request,
                agent_url,
                f"/api/talking-photo/jobs/{job_id}/keep",
                timeout=15,
            )

    if ("/api/talking-photo/jobs/{job_id}/discard", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/discard")
        async def talking_photo_discard(job_id: str, request: Request):
            job_id = _validated_id(job_id)
            return await _proxy(
                request,
                agent_url,
                f"/api/talking-photo/jobs/{job_id}/discard",
                timeout=15,
            )

    if ("/api/talking-photo/videos/{video_id}", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/videos/{video_id}")
        async def talking_photo_video(video_id: str, request: Request):
            video_id = _validated_id(video_id)
            return await _proxy(
                request,
                agent_url,
                f"/api/talking-photo/videos/{video_id}",
                timeout=60,
            )
