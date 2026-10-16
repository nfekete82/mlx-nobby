"""Read-only local media discovery and explicitly requested save/delete actions.

Only known Nobby output roots and canonical generated asset IDs can be accessed.
No file bytes or absolute paths are returned by the index.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from agent import media_lifecycle, media_library_previews, media_library_organize, media_library_workflows

KINDS = ("image", "video", "talking_photo")
SUFFIX = {"image": ".png", "video": ".mp4", "talking_photo": ".mp4"}


def list_assets(kind="all", limit=400):
    kinds = KINDS if kind == "all" else (("video", "talking_photo") if kind == "video" else (kind,))
    if kind != "all" and kind not in KINDS:
        raise ValueError("Unsupported media kind")
    results = []
    with media_lifecycle._lock:
        records = media_lifecycle._load_locked().get("assets", {})
    for media_kind in kinds:
        root = media_lifecycle._root_for(media_kind)
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if not path.is_file() or path.is_symlink() or path.suffix.lower() != SUFFIX[media_kind]:
                continue
            try:
                asset_id = media_lifecycle._validate_id(media_kind, path.stem)
                canonical = media_lifecycle._expected_path(media_kind, asset_id)
                if path.resolve() != canonical:
                    continue
                stat = path.stat()
                if stat.st_size == 0:
                    continue
                record = records.get(media_kind + ":" + asset_id) or {}
                # Acceptance fixtures are not user media. Existing files stay
                # untouched and are still managed by their normal TTL.
                if isinstance(record, dict) and record.get("owner") == "acceptance":
                    continue
            except (ValueError, OSError):
                continue
            results.append({
                "kind": media_kind, "id": asset_id,
                "engine": (media_library_previews._engine(media_kind, asset_id)
                           if media_kind == "talking_photo" else None),
                "created_at": round(stat.st_mtime, 3),
                "size_bytes": stat.st_size,
                "persistent": bool((records.get(media_kind + ":" + asset_id) or {}).get("persistent")),
                "expires_at": (records.get(media_kind + ":" + asset_id) or {}).get("expires_at"),
                "url": ("/api/mlx/images/" if media_kind == "image" else
                        "/api/mlx/videos/" if media_kind == "video" else
                        "/api/talking-photo/videos/") + asset_id,
            })
    results.sort(key=lambda asset: (asset["created_at"], asset["id"]), reverse=True)
    return {"assets": results[:limit], "total": len(results), "limit": limit}


def install_routes(app: FastAPI):
    @app.get("/api/library/assets")
    def library_assets(kind: str = "all", limit: int = Query(default=400, ge=1, le=1000)):
        try:
            return list_assets(kind, limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/library/organize")
    def library_organization():
        return media_library_organize.snapshot()

    @app.post("/api/library/organize/collections")
    def library_create_collection(payload: dict):
        try:
            return media_library_organize.create_collection(payload.get("name"))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/library/organize/collections/{collection_id}")
    def library_remove_collection(collection_id: str):
        try:
            return media_library_organize.delete_collection(collection_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/library/organize/batch")
    def library_organize_batch(payload: dict):
        try:
            return media_library_organize.update_many(
                payload.get("items"), payload.get("operation"),
                payload.get("collection_id"),
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/library/workflows")
    def library_workflows():
        return media_library_workflows.snapshot()

    @app.post("/api/library/workflows/links")
    def library_link_workflow(payload: dict):
        try:
            return media_library_workflows.link(
                payload.get("source_kind"), payload.get("source_id"),
                payload.get("output_kind"), payload.get("output_id"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/library/assets/{kind}/{asset_id}/metadata")
    def library_metadata(kind: str, asset_id: str):
        try:
            return media_library_previews.metadata(kind, asset_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Videodaten nicht gefunden") from exc

    @app.get("/api/library/assets/{kind}/{asset_id}/thumbnail")
    def library_thumbnail(kind: str, asset_id: str):
        try:
            path = media_library_previews.thumbnail(kind, asset_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Videovorschau nicht gefunden") from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(503, "Videovorschau nicht verfügbar") from exc
        return FileResponse(path, media_type="image/jpeg", headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        })

    @app.post("/api/library/assets/{kind}/{asset_id}/save")
    def library_save(kind: str, asset_id: str):
        try:
            record = media_lifecycle.persist(kind, asset_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Medium nicht gefunden") from exc
        return {"kind": record["kind"], "id": record["id"], "persistent": True}

    @app.post("/api/library/assets/delete-all")
    def library_delete_all(payload: dict):
        kind = str(payload.get("kind") or "all")
        if kind != "all" and kind not in KINDS:
            raise HTTPException(422, "Ungültiger Medientyp")
        if payload.get("confirm") != "DELETE_ALL_MEDIA_PERMANENTLY":
            raise HTTPException(400, "Explizite Löschbestätigung fehlt")
        candidates = list_assets(kind, 1000000)["assets"]
        deleted = 0
        errors = 0
        for asset in candidates:
            try:
                result = media_lifecycle.discard(asset["kind"], asset["id"], force=True)
                deleted += int(result["deleted"])
                if result["deleted"]:
                    media_library_previews.purge_cached(asset["kind"], asset["id"])
                    media_library_organize.forget(asset["kind"], asset["id"])
                    media_library_workflows.forget(asset["kind"], asset["id"])
            except (ValueError, OSError):
                errors += 1
        return {"deleted": deleted, "errors": errors, "selected": len(candidates)}

    @app.delete("/api/library/assets/{kind}/{asset_id}")
    def library_delete(kind: str, asset_id: str):
        try:
            result = media_lifecycle.discard(kind, asset_id, force=True)
        except ValueError as exc:
            raise HTTPException(422, "Ungültiges Medium") from exc
        if result["deleted"]:
            media_library_previews.purge_cached(kind, asset_id)
            media_library_organize.forget(kind, asset_id)
            media_library_workflows.forget(kind, asset_id)
        return {"deleted": result["deleted"], "kind": kind, "id": asset_id}
