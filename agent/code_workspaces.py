"""Deterministic local code workspace, patch, snapshot and revert operations."""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from agent import knowledge

ROOT = Path.home() / ".config/mlx-web/code"
WORKSPACES = ROOT / "workspaces.json"
PATCHES = ROOT / "patches"
SNAPSHOTS = ROOT / "snapshots"
TESTS = ROOT / "tests"
AUDIT = ROOT / "audit/changes.jsonl"
IGNORE = {
    ".git",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "agent-venv",
    "image-venv-python313-backup-20260904",
    "backups",
    "__pycache__",
    "dist",
    "build",
    ".cache",
    "coverage",
    "tmp",
    "temp",
}
SECRET = (".env", ".pem", ".key", "id_rsa", "id_ed25519", "credentials", "secrets", "private_key", ".p12", ".pfx")
BINARY_SUFFIXES = {
    ".7z", ".a", ".avi", ".bin", ".bmp", ".class", ".dmg", ".doc",
    ".docx", ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg",
    ".jpg", ".mov", ".mp3", ".mp4", ".o", ".otf", ".pdf", ".png",
    ".pyc", ".so", ".tar", ".ttf", ".wav", ".webp", ".woff", ".woff2",
    ".xls", ".xlsx", ".zip",
}
PATCH_LOCK = threading.RLock()

def _now(): return time.time()
def _hash(data): return hashlib.sha256(data.encode("utf-8")).hexdigest()
def _load():
    try:
        data = json.loads(WORKSPACES.read_text()) if WORKSPACES.exists() else []
        return data if isinstance(data, list) else []
    except Exception: return []
def _save(items):
    ROOT.mkdir(parents=True,exist_ok=True); tmp=WORKSPACES.with_suffix('.tmp'); tmp.write_text(json.dumps(items,indent=2)); tmp.replace(WORKSPACES)
def _workspace(workspace_id):
    item=next((x for x in _load() if x["workspace_id"]==workspace_id),None)
    if not item: raise ValueError("WORKSPACE_NOT_FOUND")
    return item
def _root(item):
    try:
        root = Path(item["root_path"]).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("WORKSPACE_ROOT_UNAVAILABLE") from exc
    if not root.is_dir():
        raise ValueError("WORKSPACE_ROOT_UNAVAILABLE")
    return root
def _safe(item, path, write=False):
    root=_root(item); candidate=Path(path)
    try:
        target=(root/candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("WORKSPACE_INVALID_PATH") from exc
    try: target.relative_to(root)
    except ValueError: raise ValueError("PATH_OUTSIDE_WORKSPACE")
    if any(part in IGNORE for part in target.relative_to(root).parts): raise ValueError("PATH_IGNORED")
    if target.name.lower().startswith(SECRET) or target.suffix.lower() in {'.pem','.key','.p12','.pfx'}: raise ValueError("SECRET_BLOCKED")
    return target
def _rel(item,path): return str(path.relative_to(_root(item)))
def _atomic(path, content):
    tmp=path.with_name('.'+path.name+'.mlx-nobby.tmp');
    with open(tmp,'w',encoding='utf-8') as f: f.write(content); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def _read_text(path):
    if path.suffix.lower() in BINARY_SUFFIXES:
        raise ValueError("BINARY_FILE_BLOCKED")
    try:
        content=path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("BINARY_FILE_BLOCKED") from exc
    if "\x00" in content:
        raise ValueError("BINARY_FILE_BLOCKED")
    return content
def _patch_path(pid): return PATCHES / f"{pid}.json"
def _patch(pid):
    try: return json.loads(_patch_path(pid).read_text())
    except FileNotFoundError: raise ValueError("PATCH_NOT_FOUND")
def _operation(entry):
    # Patches aus älteren Versionen hatten keinen expliziten Typ und waren
    # ausschließlich MODIFY-Patches.
    operation=str(entry.get("operation") or "MODIFY").strip().upper()
    if operation not in {"CREATE", "MODIFY", "DELETE"}:
        raise ValueError("PATCH_INVALID_OPERATION")
    return operation
def _summary(item, **extra):
    return {
        "workspace_id": item["workspace_id"],
        "name": item["name"],
        "root_path": item["root_path"],
        "active": bool(item.get("active")),
        **extra,
    }
def _active_from(items):
    return next((item for item in items if item.get("active")), items[0] if items else None)
def list_workspaces():
    items = _load()
    active = _active_from(items)
    active_id = active.get("workspace_id") if active else None
    return [{**item, "active": item.get("workspace_id") == active_id} for item in items]
def active_workspace(validate=True):
    item = _active_from(_load())
    if not item:
        return None
    try:
        root = Path(item["root_path"]).resolve()
        available = root.is_dir()
    except (OSError, RuntimeError):
        available = False
    if validate and not available:
        raise ValueError("WORKSPACE_ROOT_UNAVAILABLE")
    return _summary({**item, "active": True}, available=available)
def active_workspace_id():
    item = active_workspace()
    if not item:
        raise ValueError("WORKSPACE_SELECTION_REQUIRED")
    return item["workspace_id"]
def set_active_workspace(workspace_id):
    items = _load()
    item = next((entry for entry in items if entry.get("workspace_id") == workspace_id), None)
    if not item:
        raise ValueError("WORKSPACE_NOT_FOUND")
    root = _root(item)
    if not root.is_dir():
        raise ValueError("WORKSPACE_ROOT_UNAVAILABLE")
    for entry in items:
        entry["active"] = entry.get("workspace_id") == workspace_id
    _save(items)
    return _summary({**item, "active": True})
def add_workspace(path,name=None,test_commands=None,activate=True):
    try:
        root=Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("WORKSPACE_INVALID_PATH") from exc
    if not root.exists() or not root.is_dir():
        raise ValueError("WORKSPACE_NOT_FOUND")
    if not os.access(root, os.R_OK | os.X_OK):
        raise ValueError("WORKSPACE_PERMISSION_DENIED")
    items=_load(); existing=next((x for x in items if x['root_path']==str(root)),None)
    if existing:
        if activate:
            for entry in items:
                entry["active"] = entry.get("workspace_id") == existing["workspace_id"]
            _save(items)
            existing = {**existing, "active": True}
        return _summary(existing, existing=True)
    now=_now(); item={"workspace_id":uuid.uuid4().hex[:16],"name":name or root.name,"root_path":str(root),"allowed_paths":["."],"ignored_paths":sorted(IGNORE),"test_commands":test_commands or [],"created_at":now,"updated_at":now,"knowledge_source_id":None,"snapshot_root":str(SNAPSHOTS),"active":bool(activate)}
    if activate:
        for entry in items:
            entry["active"] = False
    items.append(item)
    _save(items)
    return _summary(item, existing=False)
def remove_workspace(workspace_id):
    items=_load(); item=_workspace(workspace_id); remaining=[x for x in items if x['workspace_id']!=workspace_id]
    if item.get("active") and remaining:
        remaining[0]["active"] = True
    _save(remaining)
    active = _active_from(remaining)
    return {"removed":item['name'], "active_workspace":_summary({**active, "active": True}) if active else None}
def status(workspace_id):
    item=_workspace(workspace_id); root=_root(item); files=0
    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in IGNORE]
        files+=sum(1 for n in names if not n.startswith('.') and not n.lower().endswith(('.pem','.key')))
    return {**item,"files":files,"empty":files == 0,"knowledge":knowledge.status()}
def refresh(workspace_id):
    item=_workspace(workspace_id); result=knowledge.index_source(item['root_path'],item['name']); item['updated_at']=_now(); items=_load(); items[items.index(next(x for x in items if x['workspace_id']==workspace_id))]=item; _save(items); return result
def read(workspace_id,path,start_line=None,end_line=None):
    item=_workspace(workspace_id); target=_safe(item,path)
    if not target.is_file(): raise ValueError("FILE_NOT_FOUND")
    lines=target.read_text(encoding='utf-8',errors='replace').splitlines(); a=max(1,int(start_line or 1)); b=min(len(lines),int(end_line or a+240));
    return {"path":_rel(item,target),"start_line":a,"end_line":b,"content":"\n".join(lines[a-1:b])}
def list_files(workspace_id,query=None,limit=200):
    item=_workspace(workspace_id)
    root=_root(item)
    query=str(query or "").strip().lower()
    terms=[x for x in re.split(r"\s+",query) if x]
    results=[]

    text_suffixes={
        ".py",".js",".ts",".jsx",".tsx",".php",".html",".css",
        ".json",".md",".txt",".yaml",".yml",".sh",".sql"
    }

    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in IGNORE]

        for name in names:
            path=Path(base)/name

            try:
                safe=_safe(item,path)
            except ValueError:
                continue

            rel=_rel(item,safe)
            rel_lower=rel.lower()

            match_type=None
            line_number=None
            snippet=None

            if not terms:
                match_type="file"

            elif any(term in rel_lower for term in terms):
                match_type="path"

            elif safe.suffix.lower() in text_suffixes:
                try:
                    if safe.stat().st_size > 1024*1024:
                        continue

                    text=safe.read_text(
                        encoding="utf-8",
                        errors="replace"
                    )

                    lower=text.lower()

                    if any(term in lower for term in terms):
                        match_type="content"

                        for idx,line in enumerate(
                            text.splitlines(),
                            start=1
                        ):
                            line_lower=line.lower()

                            if any(
                                term in line_lower
                                for term in terms
                            ):
                                line_number=idx
                                snippet=line.strip()[:300]
                                break

                except (OSError,UnicodeError):
                    continue

            if match_type:
                results.append({
                    "path":rel,
                    "match":match_type,
                    "line":line_number,
                    "snippet":snippet,
                })

                if len(results)>=int(limit):
                    return {
                        "workspace_id":workspace_id,
                        "query":query,
                        "workspace_empty":False,
                        "truncated":True,
                        "files":results,
                    }

    return {
        "workspace_id":workspace_id,
        "query":query,
        "workspace_empty":not query and not results,
        "truncated":False,
        "files":results,
    }

def search(workspace_id, query, limit=100):
    item = _workspace(workspace_id)
    root = _root(item)

    query = str(query or "").strip()
    if not query:
        raise ValueError("SEARCH_QUERY_REQUIRED")

    query_lower = query.lower()
    terms = [
        term
        for term in re.split(r"\s+", query_lower)
        if term
    ]

    symbol_terms = [
        term
        for term in terms
        if re.fullmatch(r"[a-z_][a-z0-9_]*", term)
    ]

    multi_symbol_query = (
        len(terms) > 1
        and len(symbol_terms) == len(terms)
    )

    text_suffixes = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".php",
        ".html", ".css", ".json", ".md", ".txt",
        ".yaml", ".yml", ".sh", ".sql",
    }

    results = []

    for base, dirs, names in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORE
        ]

        for name in names:
            path = Path(base) / name

            try:
                safe = _safe(item, path)
            except ValueError:
                continue

            if safe.suffix.lower() not in text_suffixes:
                continue

            try:
                if safe.stat().st_size > 2 * 1024 * 1024:
                    continue

                text = safe.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, UnicodeError):
                continue

            rel = _rel(item, safe)
            rel_lower = rel.lower()

            for line_number, line in enumerate(
                text.splitlines(),
                start=1,
            ):
                line_lower = line.lower()

                exact_match = query_lower in line_lower

                if multi_symbol_query:
                    matched_symbols = [
                        term
                        for term in symbol_terms
                        if term in line_lower
                    ]
                    term_match = bool(matched_symbols)
                else:
                    matched_symbols = []
                    term_match = (
                        terms
                        and all(term in line_lower for term in terms)
                    )

                path_match = query_lower in rel_lower

                if not (
                    exact_match
                    or term_match
                    or path_match
                ):
                    continue

                results.append({
                    "path": rel,
                    "line": line_number,
                    "snippet": line.strip()[:500],
                    "match": (
                        "exact"
                        if exact_match
                        else "symbol"
                        if multi_symbol_query and term_match
                        else "terms"
                        if term_match
                        else "path"
                    ),
                    "matched_terms": (
                        matched_symbols
                        if multi_symbol_query and term_match
                        else None
                    ),
                })

                if len(results) >= int(limit):
                    return {
                        "workspace_id": workspace_id,
                        "query": query,
                        "results": results,
                        "count": len(results),
                        "truncated": True,
                    }

                if path_match and not (
                    exact_match or term_match
                ):
                    break

    results.sort(
        key=lambda item: (
            0 if item["match"] == "exact" else
            1 if item["match"] == "symbol" else
            2 if item["match"] == "terms" else
            3,
            item["path"],
            item["line"],
        )
    )

    return {
        "workspace_id": workspace_id,
        "query": query,
        "results": results,
        "count": len(results),
        "truncated": False,
    }
def _write_patch(patch):
    PATCHES.mkdir(parents=True, exist_ok=True)
    _patch_path(patch["patch_id"]).write_text(
        json.dumps(patch, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _validate_proposed_content(operation, proposed):
    if operation == "DELETE":
        if proposed not in {None, ""}:
            raise ValueError("PATCH_INVALID")
        return None
    if not isinstance(proposed, str):
        raise ValueError("PATCH_INVALID")
    if "\x00" in proposed:
        raise ValueError("BINARY_FILE_BLOCKED")
    return proposed


def _prepare_change(item, change, seen):
    if not isinstance(change, dict):
        raise ValueError("PATCH_INVALID")
    path=str(change.get("path") or "").strip()
    if not path:
        raise ValueError("PATCH_INVALID")
    target=_safe(item, path, write=True)
    if target.suffix.lower() in BINARY_SUFFIXES:
        raise ValueError("BINARY_FILE_BLOCKED")
    rel=_rel(item, target)
    if rel in seen:
        raise ValueError("PATCH_DUPLICATE_PATH")
    seen.add(rel)

    requested=change.get("operation")
    operation=(
        "MODIFY" if target.exists() else "CREATE"
    ) if requested is None else str(requested).strip().upper()
    if operation not in {"CREATE", "MODIFY", "DELETE"}:
        raise ValueError("PATCH_INVALID_OPERATION")
    proposed=_validate_proposed_content(
        operation,
        change.get("proposed_content"),
    )

    if operation == "CREATE":
        if target.exists():
            raise ValueError("CREATE_CONFLICT")
        original=""
        base_hash=None
    else:
        if not target.is_file():
            raise ValueError("FILE_NOT_FOUND")
        original=_read_text(target)
        base_hash=_hash(original)
        supplied_hash=change.get("base_hash")
        if supplied_hash is not None and supplied_hash != base_hash:
            raise ValueError("PATCH_CONFLICT")

    return {
        "path": rel,
        "operation": operation,
        "base_hash": base_hash,
        "original_content": original,
        "proposed_content": proposed,
    }


def create_patch(workspace_id, instruction, files):
    item=_workspace(workspace_id)
    if active_workspace_id() != workspace_id:
        raise ValueError("WORKSPACE_CHANGED")
    if not isinstance(files, list) or not files:
        raise ValueError("PATCH_INVALID")

    entries=[]
    seen=set()
    for change in files:
        entries.append(_prepare_change(item, change, seen))

    patch_id=uuid.uuid4().hex[:16]
    patch={
        "patch_id": patch_id,
        "change_set_id": patch_id,
        "workspace_id": workspace_id,
        "goal": str(instruction or "").strip(),
        "instruction": str(instruction or "").strip(),
        "created_at": _now(),
        "status": "proposed",
        "files": entries,
    }
    _write_patch(patch)
    return diff(patch_id)


def _diff_file(entry):
    operation=_operation(entry)
    fromfile="/dev/null" if operation == "CREATE" else "original/" + entry["path"]
    tofile="/dev/null" if operation == "DELETE" else "proposed/" + entry["path"]
    proposed="" if operation == "DELETE" else entry["proposed_content"]
    text="".join(difflib.unified_diff(
        entry["original_content"].splitlines(True),
        proposed.splitlines(True),
        fromfile=fromfile,
        tofile=tofile,
    ))
    lines=text.splitlines()
    return {
        "path": entry["path"],
        "operation": operation,
        "diff": text,
        "added": sum(1 for line in lines if line.startswith("+") and not line.startswith("+++")),
        "removed": sum(1 for line in lines if line.startswith("-") and not line.startswith("---")),
    }


def _change_summary(files):
    if files and "added" not in files[0]:
        files=[_diff_file(entry) for entry in files]
    operations={"CREATE": 0, "MODIFY": 0, "DELETE": 0}
    for entry in files:
        operations[_operation(entry)] += 1
    return {
        "files": len(files),
        "create": operations["CREATE"],
        "modify": operations["MODIFY"],
        "delete": operations["DELETE"],
        "added_lines": sum(int(entry.get("added") or 0) for entry in files),
        "removed_lines": sum(int(entry.get("removed") or 0) for entry in files),
    }


def diff(patch_id):
    patch=_patch(patch_id)
    files=[_diff_file(entry) for entry in patch["files"]]
    return {
        "patch_id": patch_id,
        "change_set_id": patch.get("change_set_id", patch_id),
        "workspace_id": patch["workspace_id"],
        "goal": patch.get("goal", patch.get("instruction", "")),
        "status": patch["status"],
        "summary": _change_summary(files),
        "files": files,
    }

def _test_copy_ignore(directory, names):
    ignored=[]
    for name in names:
        path=Path(directory)/name
        lower=name.lower()
        if (
            name in IGNORE
            or path.is_symlink()
            or lower.startswith(SECRET)
            or path.suffix.lower() in {'.pem','.key','.p12','.pfx'}
        ):
            ignored.append(name)
    return ignored

def _test_command_result(command, cwd, timeout):
    try:
        run=subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        return {
            "status": "passed" if run.returncode == 0 else "failed",
            "returncode": run.returncode,
            "output": ((run.stdout or "") + (run.stderr or ""))[:4000],
        }
    except FileNotFoundError as exc:
        return {"status": "unavailable", "output": str(exc)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "output": str(exc)}


def _simulate_change_set(work, files):
    for entry in files:
        target=work / entry["path"]
        operation=_operation(entry)
        if operation == "DELETE":
            if target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry["proposed_content"], encoding="utf-8")


def test(patch_id):
    patch=_patch(patch_id)
    item=_workspace(patch["workspace_id"])
    work=TESTS / patch_id
    test_commands=item.get("test_commands") or []
    results=[]

    shutil.rmtree(work, ignore_errors=True)
    work.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            _root(item),
            work,
            ignore=_test_copy_ignore,
        )
        _simulate_change_set(work, patch["files"])

        syntax_commands={
            ".php": lambda target: ["php", "-l", str(target)],
            ".py": lambda target: ["python3", "-m", "py_compile", str(target)],
            ".js": lambda target: ["node", "--check", str(target)],
            ".mjs": lambda target: ["node", "--check", str(target)],
            ".cjs": lambda target: ["node", "--check", str(target)],
            ".ts": lambda target: ["node", "--check", str(target)],
        }
        for entry in patch["files"]:
            operation=_operation(entry)
            if operation == "DELETE":
                results.append({
                    "path": entry["path"],
                    "operation": operation,
                    "status": "skipped",
                    "simulated": "absent",
                })
                continue
            target=work / entry["path"]
            factory=syntax_commands.get(target.suffix.lower())
            if factory is None:
                results.append({
                    "path": entry["path"],
                    "operation": operation,
                    "status": "skipped",
                })
                continue
            result=_test_command_result(factory(target), work, 30)
            results.append({
                "path": entry["path"],
                "operation": operation,
                "check": "syntax",
                **result,
            })

        for index, command in enumerate(test_commands):
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(part, str) and part for part in command)
            ):
                results.append({
                    "test_command": index,
                    "status": "failed",
                    "output": "INVALID_TEST_COMMAND",
                })
                continue
            result=_test_command_result(command, work, 120)
            results.append({
                "test_command": index,
                "command": command,
                **result,
            })
    except Exception as exc:
        results.append({
            "check": "test_workspace",
            "status": "failed",
            "output": str(exc),
        })
    finally:
        shutil.rmtree(work, ignore_errors=True)

    patch["tests"]={
        "patch_id": patch_id,
        "change_set_id": patch.get("change_set_id", patch_id),
        "summary": _change_summary(patch["files"]),
        "results": results,
        "passed": all(
            entry.get("status") in {"passed", "skipped"}
            for entry in results
        ),
        "test_workspace_removed": not work.exists(),
    }
    _write_patch(patch)
    return patch["tests"]


def _check_apply_conflicts(item, patch):
    targets=[]
    conflicts=[]
    create_conflicts=[]
    for entry in patch["files"]:
        target=_safe(item, entry["path"], write=True)
        operation=_operation(entry)
        current=None
        if operation == "CREATE":
            if target.exists():
                conflicts.append(entry["path"])
                create_conflicts.append(entry["path"])
        elif not target.is_file():
            conflicts.append(entry["path"])
        else:
            current=_read_text(target)
            if _hash(current) != entry["base_hash"]:
                conflicts.append(entry["path"])
        targets.append((entry, target, current))
    if conflicts:
        detail="PATCH_CONFLICT: " + ", ".join(conflicts)
        if create_conflicts:
            detail += " (CREATE_CONFLICT: " + ", ".join(create_conflicts) + ")"
        raise ValueError(detail)
    return targets


def _created_directories(item, targets):
    root=_root(item)
    missing=set()
    for entry, target, _ in targets:
        if _operation(entry) == "DELETE":
            continue
        parent=target.parent
        while parent != root and not parent.exists():
            missing.add(parent)
            parent=parent.parent
    return sorted(missing, key=lambda value: len(value.parts), reverse=True)


def _create_snapshot(item, patch, targets):
    snapshot=SNAPSHOTS / patch["patch_id"]
    files_dir=snapshot / "files"
    if snapshot.exists():
        shutil.rmtree(snapshot)
    files_dir.mkdir(parents=True, exist_ok=True)
    created_directories=_created_directories(item, targets)
    metadata=[]
    for entry, _target, current in targets:
        operation=_operation(entry)
        if operation != "CREATE":
            backup=files_dir / entry["path"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(current, encoding="utf-8")
        metadata.append({
            "path": entry["path"],
            "operation": operation,
            "before_hash": None if operation == "CREATE" else _hash(current),
            "after_hash": None if operation == "DELETE" else _hash(entry["proposed_content"]),
        })
    snapshot_data={
        "patch_id": patch["patch_id"],
        "change_set_id": patch.get("change_set_id", patch["patch_id"]),
        "workspace_id": item["workspace_id"],
        "created_at": _now(),
        "created_directories": [
            _rel(item, directory) for directory in created_directories
        ],
        "files": metadata,
    }
    (snapshot / "metadata.json").write_text(
        json.dumps(snapshot_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot, snapshot_data


def _apply_entries(item, targets):
    for entry, target, _current in targets:
        operation=_operation(entry)
        if operation == "DELETE":
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if _safe(item, target, write=True) != target:
            raise ValueError("PATH_OUTSIDE_WORKSPACE")
        _atomic(target, entry["proposed_content"])


def _rollback_to_snapshot(item, snapshot, metadata):
    errors=[]
    for entry in metadata["files"]:
        try:
            target=_safe(item, entry["path"], write=True)
            if _operation(entry) == "CREATE":
                if target.is_file() or target.is_symlink():
                    target.unlink()
                elif target.exists():
                    raise ValueError("ROLLBACK_TARGET_NOT_FILE")
                continue
            backup=snapshot / "files" / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup, target)
        except Exception as exc:
            errors.append({"path": entry["path"], "error": str(exc)})
    for rel in metadata.get("created_directories", []):
        try:
            directory=_safe(item, rel, write=True)
            if directory.is_dir():
                directory.rmdir()
        except OSError:
            pass
        except Exception as exc:
            errors.append({"path": rel, "error": str(exc)})
    return {"completed": not errors, "errors": errors}


def _audit(patch, status, **extra):
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    record={
        "timestamp": _now(),
        "workspace_id": patch["workspace_id"],
        "patch_id": patch["patch_id"],
        "change_set_id": patch.get("change_set_id", patch["patch_id"]),
        "instruction": patch.get("instruction", ""),
        "files": [entry["path"] for entry in patch["files"]],
        "status": status,
        **extra,
    }
    with AUDIT.open("a", encoding="utf-8") as audit:
        audit.write(json.dumps(record, ensure_ascii=False) + "\n")


def apply(patch_id, approved=False):
    if not approved:
        raise ValueError("APPROVAL_REQUIRED")
    with PATCH_LOCK:
        patch=_patch(patch_id)
        item=_workspace(patch["workspace_id"])
        if patch.get("status") != "proposed":
            raise ValueError("PATCH_STATE_INVALID")
        if active_workspace_id() != patch["workspace_id"]:
            raise ValueError("WORKSPACE_CHANGED")

        # Alle Konflikte werden vor der ersten Workspace-Änderung geprüft.
        targets=_check_apply_conflicts(item, patch)
        snapshot, metadata=_create_snapshot(item, patch, targets)
        try:
            _apply_entries(item, targets)
            patch["status"]="applied"
            patch["snapshot"]=str(snapshot)
            patch["applied_at"]=_now()
            _write_patch(patch)
            summary=_change_summary(patch["files"])
            _audit(patch, "applied", snapshot=str(snapshot), summary=summary)
        except Exception as exc:
            rollback=_rollback_to_snapshot(item, snapshot, metadata)
            patch["status"]="failed"
            patch["snapshot"]=str(snapshot)
            patch["apply_error"]=str(exc)
            patch["rollback"]=rollback
            try:
                _write_patch(patch)
            except Exception:
                pass
            try:
                _audit(
                    patch,
                    "apply_failed",
                    error=str(exc),
                    rollback=rollback,
                    snapshot=str(snapshot),
                )
            except Exception:
                pass
            raise ValueError("PATCH_APPLY_FAILED: " + str(exc)) from exc

        return {
            "patch_id": patch_id,
            "change_set_id": patch.get("change_set_id", patch_id),
            "status": "applied",
            "snapshot": str(snapshot),
            "summary": summary,
            "files": [
                {"path": entry["path"], "operation": _operation(entry)}
                for entry in patch["files"]
            ],
        }


def _check_revert_conflicts(item, metadata):
    conflicts=[]
    for entry in metadata["files"]:
        target=_safe(item, entry["path"], write=True)
        operation=_operation(entry)
        if operation == "DELETE":
            if target.exists():
                conflicts.append(entry["path"])
            continue
        if not target.is_file():
            conflicts.append(entry["path"])
            continue
        if _hash(_read_text(target)) != entry["after_hash"]:
            conflicts.append(entry["path"])
    if conflicts:
        raise ValueError("REVERT_CONFLICT: " + ", ".join(conflicts))


def _restore_applied_state(item, patch):
    errors=[]
    for entry in patch["files"]:
        target=_safe(item, entry["path"], write=True)
        try:
            if _operation(entry) == "DELETE":
                if target.is_file():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic(target, entry["proposed_content"])
        except Exception as exc:
            errors.append({"path": entry["path"], "error": str(exc)})
    return {"completed": not errors, "errors": errors}


def revert(patch_id):
    with PATCH_LOCK:
        patch=_patch(patch_id)
        item=_workspace(patch["workspace_id"])
        if patch.get("status") != "applied":
            raise ValueError("PATCH_STATE_INVALID")
        if active_workspace_id() != patch["workspace_id"]:
            raise ValueError("WORKSPACE_CHANGED")
        snapshot=SNAPSHOTS / patch_id
        metadata=json.loads(
            (snapshot / "metadata.json").read_text(encoding="utf-8")
        )
        _check_revert_conflicts(item, metadata)
        try:
            rollback=_rollback_to_snapshot(item, snapshot, metadata)
            if not rollback["completed"]:
                raise ValueError("REVERT_FAILED")
            patch["status"]="reverted"
            patch["reverted_at"]=_now()
            _write_patch(patch)
            summary=_change_summary(patch["files"])
            _audit(patch, "reverted", summary=summary)
        except Exception as exc:
            recovery=_restore_applied_state(item, patch)
            patch["status"]="applied"
            patch["revert_error"]=str(exc)
            patch["revert_recovery"]=recovery
            try:
                _write_patch(patch)
            except Exception:
                pass
            try:
                _audit(
                    patch,
                    "revert_failed",
                    error=str(exc),
                    recovery=recovery,
                )
            except Exception:
                pass
            raise ValueError("REVERT_FAILED: " + str(exc)) from exc

        return {
            "patch_id": patch_id,
            "change_set_id": patch.get("change_set_id", patch_id),
            "status": "reverted",
            "summary": summary,
        }


def verify(patch_id):
    patch=_patch(patch_id)
    item=_workspace(patch["workspace_id"])
    checks=[]
    for entry in patch["files"]:
        operation=_operation(entry)
        actual_hash=None
        error=None
        try:
            target=_safe(item, entry["path"])
            if operation == "DELETE":
                ok=not target.exists()
            else:
                ok=target.is_file()
                if ok:
                    actual_hash=_hash(_read_text(target))
                    ok=actual_hash == _hash(entry["proposed_content"])
        except (OSError, ValueError) as exc:
            ok=False
            error=str(exc)
        checks.append({
            "path": entry["path"],
            "operation": operation,
            "ok": ok,
            "actual_hash": actual_hash,
            "expected_hash": (
                None if operation == "DELETE"
                else _hash(entry["proposed_content"])
            ),
            "error": error,
        })
    verified=patch.get("status") == "applied" and all(
        entry["ok"] for entry in checks
    )
    return {
        "patch_id": patch_id,
        "change_set_id": patch.get("change_set_id", patch_id),
        "status": patch.get("status"),
        "verified": verified,
        "summary": _change_summary(patch["files"]),
        "files": checks,
        "errors": [entry for entry in checks if not entry["ok"]],
    }
