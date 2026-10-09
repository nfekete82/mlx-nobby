"""Read-only local media discovery and explicitly requested save/delete actions.

Only known Nobby output roots and canonical generated asset IDs can be accessed.
No file bytes or absolute paths are returned by the index.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from agent import media_lifecycle

KINDS = ("image", "video", "talking_photo")
SUFFIX = {"image": ".png", "video": ".mp4", "talking_photo": ".mp4"}


def list_assets(kind="all", limit=400):
    kinds = KINDS if kind == "all" else (kind,)
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
            except (ValueError, OSError):
                continue
            results.append({
                "kind": media_kind, "id": asset_id,
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

    @app.post("/api/library/assets/{kind}/{asset_id}/save")
    def library_save(kind: str, asset_id: str):
        try:
            record = media_lifecycle.persist(kind, asset_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Medium nicht gefunden") from exc
        return {"kind": record["kind"], "id": record["id"], "persistent": True}

    @app.delete("/api/library/assets/{kind}/{asset_id}")
    def library_delete(kind: str, asset_id: str):
        try:
            result = media_lifecycle.discard(kind, asset_id, force=True)
        except ValueError as exc:
            raise HTTPException(422, "Ungültiges Medium") from exc
        return {"deleted": result["deleted"], "kind": kind, "id": asset_id}
