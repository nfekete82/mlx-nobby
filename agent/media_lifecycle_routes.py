"""Agent routes and download hook for generated-media lifecycle management."""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent import media_lifecycle


class MediaRef(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: str = Field(min_length=1, max_length=32)
    id: str = Field(min_length=1, max_length=64)


class MediaRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assets: list[MediaRef] = Field(default_factory=list, max_length=500)


class MediaLifecycleDownloadMiddleware:
    """Promote generated chat media when the user explicitly downloads it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET":
            query = parse_qs(bytes(scope.get("query_string") or b"").decode("ascii", errors="ignore"))
            wants_download = str((query.get("download") or [""])[0]).lower() in {
                "1", "true", "yes", "on",
            }
            if wants_download:
                path = str(scope.get("path") or "")
                candidates = (
                    ("/api/images/", "image"),
                    ("/api/videos/", "video"),
                    ("/api/talking-photo/videos/", "talking_photo"),
                )
                for prefix, kind in candidates:
                    if not path.startswith(prefix):
                        continue
                    asset_id = path[len(prefix):]
                    if "/" in asset_id or not asset_id:
                        break
                    try:
                        media_lifecycle.persist(kind, asset_id)
                    except (ValueError, OSError):
                        pass
                    break
        await self.app(scope, receive, send)


def install_routes(app: FastAPI) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/media-lifecycle/status" not in paths:
        @app.get("/api/media-lifecycle/status")
        def media_lifecycle_status():
            return media_lifecycle.status()

    if "/api/media-lifecycle/persist" not in paths:
        @app.post("/api/media-lifecycle/persist")
        def media_lifecycle_persist(request: MediaRefs):
            results = []
            for ref in request.assets:
                try:
                    record = media_lifecycle.persist(ref.kind, ref.id)
                    results.append({
                        "kind": ref.kind,
                        "id": ref.id,
                        "persistent": bool(record.get("persistent")),
                    })
                except FileNotFoundError as exc:
                    raise HTTPException(404, "Generiertes Medium nicht gefunden") from exc
                except ValueError as exc:
                    raise HTTPException(422, "Ungültige Media-Referenz") from exc
            return {"processed": len(results), "assets": results}

    if "/api/media-lifecycle/discard" not in paths:
        @app.post("/api/media-lifecycle/discard")
        def media_lifecycle_discard(request: MediaRefs):
            return media_lifecycle.discard_many(
                [ref.model_dump() for ref in request.assets]
            )

    if "/api/media-lifecycle/cleanup" not in paths:
        @app.post("/api/media-lifecycle/cleanup")
        def media_lifecycle_cleanup():
            return media_lifecycle.cleanup_expired()
