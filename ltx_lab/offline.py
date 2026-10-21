"""CPU-only local asset verification; never imports HF/MLX or downloads anything."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def tensor_header(path):
    with path.open("rb") as f:
        raw = f.read(8)
        if len(raw) != 8:
            raise ValueError("Truncated safetensors header")
        size = struct.unpack("<Q", raw)[0]
        if not 2 <= size <= 16 * 1024**2:
            raise ValueError("Invalid/oversized safetensors header")
        header = json.loads(f.read(size))
    payload = path.stat().st_size - 8 - size
    sizes = {"BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3": 1, "F8_E5M2": 1,
             "I16": 2, "U16": 2, "F16": 2, "BF16": 2, "I32": 4, "U32": 4,
             "F32": 4, "I64": 8, "U64": 8, "F64": 8}
    intervals = []
    for name, value in header.items():
        if name == "__metadata__":
            continue
        a, b = value["data_offsets"]
        shape, dtype = value["shape"], value["dtype"]
        if (not all(type(n) is int and n >= 0 for n in [a, b, *shape])
                or b < a or b > payload or dtype not in sizes
                or math.prod(shape) * sizes[dtype] != b - a):
            raise ValueError(f"Invalid safetensors payload range/shape: {name}")
        intervals.append((a, b))
    cursor = 0
    for a, b in sorted(intervals):
        if a != cursor:
            raise ValueError("Overlapping or missing safetensors payload ranges")
        cursor = b
    if not intervals or cursor != payload:
        raise ValueError("Incomplete safetensors payload")
    return set(header) - {"__metadata__"}


def inspect_model(path):
    root = Path(path).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Original absolute local directory required")
    root = root.resolve()
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json"):
        if not (root / name).is_file():
            raise ValueError(f"Missing local asset: {name}")
        json.loads((root / name).read_text())
    config = json.loads((root / "config.json").read_text())
    if config.get("auto_map") or json.loads((root / "tokenizer_config.json").read_text()).get("auto_map"):
        raise ValueError("Custom/remote code needs a separate offline contract")
    weights = sorted(root.glob("*.safetensors"))
    if not weights:
        raise ValueError("No local safetensors shards")
    names = {}
    for weight in weights:
        for name in tensor_header(weight):
            if name in names:
                raise ValueError("Duplicate tensor across shards")
            names[name] = weight.name
    index = root / "model.safetensors.index.json"
    if index.exists():
        mapping = json.loads(index.read_text())["weight_map"]
        if not mapping or mapping != names:
            raise ValueError("Shard index and actual tensor headers differ")
    elif len(weights) != 1:
        raise ValueError("Multiple shards require a complete index")
    files = []
    # Check every snapshot symlink (including auxiliary config/processor files).
    for p in sorted(root.iterdir()):
        if p.is_symlink() and not p.exists():
            raise ValueError(f"Broken snapshot link: {p.name}")
        if p.is_file():
            st = p.stat()
            row = {"name": p.name, "resolved": str(p.resolve()), "size": st.st_size,
                   "mtime_ns": st.st_mtime_ns, "inode": st.st_ino,
                   "symlink": str(p.readlink()) if p.is_symlink() else None}
            if p.suffix in {".json", ".jinja", ".txt", ".model"}:
                row["sha256"] = digest(p)
            files.append(row)
    return {"path": str(root), "files": files, "shards": len(weights), "tensors": len(names),
            "weight_bytes": sum(p.stat().st_size for p in weights),
            "offline_assets_complete": True, "gpu_reload_tested": False,
            "weight_content_hashes_checked": False}


def inspect_cache(repo, hub):
    if not repo or len(repo.split("/")) != 2 or any(p in {".", "..", ""} for p in repo.split("/")):
        raise ValueError("Expected owner/repository ID")
    directory = Path(hub) / ("models--" + repo.replace("/", "--"))
    refs = {str(p.relative_to(directory / "refs")): p.read_text().strip()
            for p in (directory / "refs").rglob("*") if p.is_file()}
    snapshots = {}
    for path in sorted((directory / "snapshots").glob("*")):
        if path.is_dir():
            try:
                snapshots[path.name] = inspect_model(path)
            except (ValueError, OSError, KeyError) as exc:
                snapshots[path.name] = {"offline_assets_complete": False, "error": str(exc)}
    return {"repo": repo, "cache": str(directory), "refs": refs, "snapshots": snapshots,
            "live_model_revision_proven": False}
