"""Web → agent proxies for authoritative Shorts drafts and media."""
import os
import urllib.error
import urllib.parse
import urllib.request
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool


def install_routes(app, agent_json_request):
    if any(getattr(r, "path", None) == "/api/mlx/shorts/drafts" for r in app.routes):
        return
    first_new_route = len(app.router.routes)

    @app.post("/api/mlx/shorts/plan", status_code=201)
    def plan(request: dict):
        return agent_json_request("POST", "/api/shorts/plan", request, timeout=900)

    @app.get("/api/mlx/shorts/capabilities")
    def capabilities():
        return agent_json_request("GET", "/api/shorts/capabilities", None, timeout=15)

    @app.get("/api/mlx/shorts/drafts")
    def drafts():
        return agent_json_request("GET", "/api/shorts/drafts", None, timeout=15)

    @app.post("/api/mlx/shorts/drafts", status_code=201)
    def create(request: dict):
        return agent_json_request("POST", "/api/shorts/drafts", request, timeout=15)

    @app.get('/api/mlx/shorts/drafts/{draft_id}/preflight')
    def preflight(draft_id: str):
        return agent_json_request('GET', f'/api/shorts/drafts/{urllib.parse.quote(draft_id, safe="")}/preflight', None, timeout=60)

    @app.api_route("/api/mlx/shorts/drafts/{draft_id}", methods=["GET", "PUT", "DELETE"])
    async def draft(draft_id: str, request: Request):
        payload = await request.json() if request.method == "PUT" else None
        return await run_in_threadpool(agent_json_request, request.method, "/api/shorts/drafts/" + urllib.parse.quote(draft_id, safe=""), payload, timeout=15)

    @app.post("/api/mlx/shorts/drafts/{draft_id}/{action}")
    async def action(draft_id: str, action: str, request: Request):
        if action not in {"plan", "render", "duplicate"}:
            raise HTTPException(404, "unknown draft action")
        body = await request.body()
        import json
        try:
            payload = json.loads(body) if body else {}
        except ValueError as exc:
            raise HTTPException(400, "invalid JSON") from exc
        return await run_in_threadpool(agent_json_request, "POST", f"/api/shorts/drafts/{urllib.parse.quote(draft_id, safe='')}/{action}",
                                  payload, timeout=900 if action == "plan" else 30)

    @app.post("/api/mlx/shorts/drafts/{draft_id}/scenes/{scene_id}/improve")
    def improve(draft_id: str, scene_id: str):
        return agent_json_request("POST", f"/api/shorts/drafts/{urllib.parse.quote(draft_id, safe='')}/scenes/{urllib.parse.quote(scene_id, safe='')}/improve", {}, timeout=900)

    def stream(path, request):
        url = os.environ.get("AGENT_URL", "http://127.0.0.1:8010").rstrip("/") + path
        headers = {"Range": request.headers["range"]} if request.headers.get("range") else {}
        try:
            upstream = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
        except urllib.error.HTTPError as exc:
            raise HTTPException(exc.code, "Shorts media unavailable") from exc
        except urllib.error.URLError as exc:
            raise HTTPException(503, "Agent unavailable") from exc
        def chunks():
            try:
                while chunk := upstream.read(1024 * 1024):
                    yield chunk
            finally:
                upstream.close()
        return StreamingResponse(chunks(), status_code=upstream.status,
                                 media_type=upstream.headers.get("Content-Type"),
                                 headers={k: upstream.headers[k] for k in ("Content-Length", "Content-Range", "Accept-Ranges") if k in upstream.headers})

    @app.get("/api/mlx/shorts/library/{kind}/{track:path}")
    def audio(kind: str, track: str, request: Request):
        return stream(f"/api/shorts/library/{urllib.parse.quote(kind, safe='')}/{urllib.parse.quote(track, safe='/')}", request)

    @app.get("/api/mlx/shorts/jobs/{job_id}/scenes/{scene_id}/{kind}")
    def scene(job_id: str, scene_id: str, kind: str, request: Request):
        parts = [urllib.parse.quote(v, safe="") for v in (job_id, scene_id, kind)]
        return stream(f"/api/shorts/jobs/{parts[0]}/scenes/{parts[1]}/{parts[2]}", request)

    # The legacy single-segment download route must not swallow the static
    # drafts/capabilities GET paths. Entrypoints install these routes after app.py.
    added = app.router.routes[first_new_route:]
    del app.router.routes[first_new_route:]
    legacy_index = next((i for i, route in enumerate(app.router.routes)
                         if getattr(route, "path", None) == "/api/mlx/shorts/{job_id}"),
                        len(app.router.routes))
    app.router.routes[legacy_index:legacy_index] = added
