"""Small AgentRuntime adapters for existing workspace and service capabilities."""

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from agent import code_workspaces, knowledge, run_state
from agent.model_provider import ModelRequest
from agent.runtime import current_runtime


OUTPUT_LIMIT = 12000
SHELL_TIMEOUT = 30
GIT_TIMEOUT = 20


def _context():
    context = run_state.current_run_context()
    if context is None:
        raise ValueError("RUN_CONTEXT_REQUIRED")
    if context.cancelled:
        raise ValueError("RUN_CANCELLED")
    return context


def _options(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("INVALID_TOOL_OPTIONS")
    return value


def _limited_structure(value):
    if len(json.dumps(value, ensure_ascii=False, default=str)) <= OUTPUT_LIMIT:
        return value
    budget = [max(1000, OUTPUT_LIMIT - 2000)]
    def visit(item):
        if isinstance(item, str):
            part = item[:budget[0]]
            budget[0] -= len(part)
            return part
        if isinstance(item, list):
            return [visit(child) for child in item[:30] if budget[0] > 0]
        if isinstance(item, dict):
            return {key: visit(child) for key, child in list(item.items())[:60] if budget[0] > 0}
        return item
    if isinstance(value, dict):
        return {**visit(value), "truncated": True}
    return {"preview": visit(value), "truncated": True}


def _run(args, root, timeout):
    context = _context()
    context.workspace()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.run(
                args, cwd=root, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, timeout=timeout, check=False,
            )
            timed_out = False
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
        if context.cancelled:
            raise ValueError("RUN_CANCELLED")
        def bounded(handle):
            size = handle.tell()
            handle.seek(0)
            return handle.read(OUTPUT_LIMIT).decode("utf-8", errors="replace"), size > OUTPUT_LIMIT
        out, out_cut = bounded(stdout)
        err, err_cut = bounded(stderr)
    return {
        "returncode": returncode, "stdout": out, "stderr": err,
        "timed_out": timed_out, "truncated": out_cut or err_cut,
    }


def _relative_path(value, *, write=False):
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError("INVALID_WORKSPACE_PATH")
    context = _context()
    target = context.resolve_path(value, write=write)
    return str(target.relative_to(context.workspace_root))


def workspace_shell_arguments(query):
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError("INVALID_SHELL_COMMAND")
    args = shlex.split(query)
    if not args:
        raise ValueError("INVALID_SHELL_COMMAND")
    executable = args[0]
    if executable == "pwd" and len(args) == 1:
        command = ["pwd"]
    elif executable == "ls" and len(args) in (1, 2, 3):
        tail = args[1:]
        if tail and tail[0] == "-la":
            tail = tail[1:]
            command = ["ls", "-la"]
        else:
            command = ["ls"]
        if len(tail) > 1:
            raise ValueError("SHELL_COMMAND_NOT_ALLOWED")
        command.append(_relative_path(tail[0]) if tail else ".")
    elif executable == "rg" and len(args) in (2, 3):
        if args[1].startswith("-"):
            raise ValueError("SHELL_COMMAND_NOT_ALLOWED")
        command = ["rg", "--", args[1], _relative_path(args[2]) if len(args) == 3 else "."]
    elif executable in {"python", "python3"} and len(args) in (4, 5) and args[1:3] == ["-m", "pytest"]:
        command = [executable, "-m", "pytest", *(_relative_path(path) for path in args[3:])]
    elif executable == "node" and len(args) == 3 and args[1] == "--check":
        command = ["node", "--check", _relative_path(args[2])]
    else:
        raise ValueError("SHELL_COMMAND_NOT_ALLOWED")
    return command


def _workspace_shell(query):
    command = workspace_shell_arguments(query)
    root = _context().workspace_root
    return {"command": command, **_run(command, root, SHELL_TIMEOUT)}


def _git(args):
    context = _context()
    root = context.workspace_root
    context.workspace()
    probe = _run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], root, GIT_TIMEOUT)
    if probe["returncode"] != 0 or Path(probe["stdout"].strip()).resolve() != root:
        raise ValueError("GIT_REPOSITORY_MUST_MATCH_WORKSPACE")
    return _run([
        "git", "--no-pager", "-c", "core.fsmonitor=false",
        "-c", "core.hooksPath=/dev/null", "-C", str(root), *args,
    ], root, GIT_TIMEOUT)


def _git_paths(options):
    paths = options.get("paths")
    if not isinstance(paths, list) or not paths or len(paths) > 30:
        raise ValueError("GIT_PATHS_REQUIRED")
    if any(not isinstance(path, str) or path.startswith(":") or any(char in path for char in "*?[]") for path in paths):
        raise ValueError("GIT_LITERAL_FILE_PATHS_REQUIRED")
    values = [_relative_path(path, write=True) for path in paths]
    if any((_context().workspace_root / path).is_dir() for path in values):
        raise ValueError("GIT_LITERAL_FILE_PATHS_REQUIRED")
    if len(set(values)) != len(values):
        raise ValueError("DUPLICATE_GIT_PATH")
    return values


def _git_tool(action, query, options):
    if action == "git_status":
        return _git(["status", "--short", "--untracked-files=normal"])
    if action == "git_diff":
        no_path = not query or (
            isinstance(query, str) and query.strip().lower() in {"none", "null"}
        )
        path = None if no_path else _relative_path(query)
        return _git(["diff", "--no-ext-diff", "--no-textconv", *(["--cached"] if options.get("cached") is True else []),
                     "--", *([path] if path else [])])
    if action == "git_log":
        return _git(["log", "-5", "--format=%h %s"])
    if action == "git_stage":
        return _git(["add", "--", *_git_paths(options)])
    if action == "git_commit":
        paths = _git_paths(options)
        message = options.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 200 or "\n" in message:
            raise ValueError("INVALID_COMMIT_MESSAGE")
        git_staged_fingerprint(paths)
        return _git(["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                     "commit", "-m", message.strip()])
    raise ValueError("UNKNOWN_GIT_TOOL")


def git_staged_fingerprint(paths):
    """Bind a commit approval to the exact staged paths and blob IDs."""
    staged = _git(["diff", "--cached", "--name-only", "-z"])
    if staged["returncode"] != 0 or staged["truncated"]:
        raise ValueError("GIT_STAGED_FILES_UNAVAILABLE")
    staged_paths = {path for path in staged["stdout"].split("\x00") if path}
    if staged_paths != set(paths):
        raise ValueError("GIT_STAGED_PATHS_CHANGED")
    raw = _git(["diff", "--no-ext-diff", "--no-textconv", "--cached", "--raw", "-z"])
    if raw["returncode"] != 0 or raw["truncated"]:
        raise ValueError("GIT_STAGED_FILES_UNAVAILABLE")
    return hashlib.sha256(raw["stdout"].encode("utf-8")).hexdigest()


def git_worktree_fingerprint(paths):
    """Bind a stage approval to the selected files' current content."""
    digest = hashlib.sha256()
    root = _context().workspace_root
    for path in paths:
        relative = _relative_path(path, write=True)
        target = root / relative
        if target.is_dir():
            raise ValueError("GIT_LITERAL_FILE_PATHS_REQUIRED")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if not target.exists():
            digest.update(b"deleted\0")
        else:
            with target.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
    return digest.hexdigest()


def _vision(query, goal, options):
    from agent import app
    context = _context()
    artifact_id = options.get("artifact_id")
    upload_path = options.get("upload_path")
    if upload_path:
        source = Path(str(upload_path)).resolve()
        if source not in context.upload_paths:
            raise ValueError("UPLOAD_OUTSIDE_RUN")
    elif artifact_id:
        _chat_artifact(artifact_id)
        source = app._resolve_image_artifact_source(artifact_id)
    else:
        source = context.resolve_path(query)
    mime = mimetypes.guess_type(source.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp"} or not source.is_file() or source.stat().st_size > 10_000_000:
        raise ValueError("UNSUPPORTED_VISION_IMAGE")
    image = base64.b64encode(source.read_bytes()).decode("ascii")
    request = ModelRequest(
        messages=[{"role": "user", "content": [
            {"type": "text", "text": str(options.get("prompt") or goal)[:4000]},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}},
        ]}], max_tokens=1000, role="vision",
    )
    runtime = current_runtime()
    if runtime is None:
        raise ValueError("AGENT_RUNTIME_REQUIRED")
    response = runtime.provider.complete(request, run_context=context)
    return {"answer": response.text, "model": response.model, "source": source.name}


def _chat_artifact(artifact_id):
    from agent import app
    context = _context()
    match = app.IMAGE_ARTIFACT_ID_PATTERN.fullmatch(str(artifact_id or ""))
    if not context.chat_id or match is None:
        raise ValueError("IMAGE_ARTIFACT_OUTSIDE_CHAT")
    with app.CHATS_LOCK:
        chat = app.read_chat(context.chat_id)
    if chat is None or match.group("image_id") not in app.collect_chat_image_ids(chat):
        raise ValueError("IMAGE_ARTIFACT_OUTSIDE_CHAT")


def _image_tool(action, query, goal, options):
    from agent import app
    context = _context()
    if action == "image_job_status":
        job_id = str(query or "")
        job = app.image_api.request("GET", "/jobs/" + app.image_api.job_id(job_id), timeout=15)
        if not context.chat_id or job.get("chat_id") != context.chat_id:
            raise ValueError("IMAGE_JOB_OUTSIDE_CHAT")
        return app._image_job_tool_result(job)
    if not context.chat_id:
        raise ValueError("CHAT_ID_REQUIRED")
    with app.CHATS_LOCK:
        chat = app.read_chat(context.chat_id)
    if chat is None:
        raise ValueError("CHAT_NOT_FOUND")
    if action == "image_edit":
        if options.get("upload_path"):
            if Path(str(options["upload_path"])).resolve() not in context.upload_paths:
                raise ValueError("UPLOAD_OUTSIDE_RUN")
        else:
            _chat_artifact(options.get("artifact_id"))
    request = app.ChatActionRequest(
        prompt=str(query or goal), action=action, chat_id=context.chat_id,
        run_id=context.run_id,
        chat_revision=context.chat_revision if context.chat_revision is not None else chat.get("revision", 0),
        active_artifact_id=options.get("artifact_id"),
        file_context={"stored_path": str(Path(str(options["upload_path"])).resolve())}
        if options.get("upload_path") else None,
        image_options=options.get("image_options"),
    )
    return app._start_chat_image_job(action, request)


def _document_tool(action, query, instruction, options):
    from agent import app
    if action in {"file_inspect", "file_pii_audit"}:
        source = _context().resolve_path(query)
        if not source.is_file() or source.suffix.lower() in code_workspaces.BINARY_SUFFIXES or source.stat().st_size > 10_000_000:
            raise ValueError("UNSUPPORTED_TEXT_FILE")
        if action == "file_inspect":
            return _limited_structure(app.analyze_file_structure(str(source)))
        return app.deterministic_pii_audit(source.read_text(encoding="utf-8", errors="replace"))
    if action == "document_search":
        if _context().resources_bound and options.get("document_id") not in _context().document_ids:
            raise ValueError("DOCUMENT_OUTSIDE_RUN")
        result = knowledge.search_uploaded_document(options.get("document_id"), query, limit=6)
        result = dict(result)
        original_results = result.get("results", [])[:6]
        result["results"] = [
            {**item, "content": str(item.get("content") or "")[:1500]}
            for item in original_results
        ]
        result["truncated"] = any(
            len(str(item.get("content") or "")) > 1500
            for item in original_results
        )
        return result
    if action == "document_page":
        if _context().resources_bound and options.get("document_id") not in _context().document_ids:
            raise ValueError("DOCUMENT_OUTSIDE_RUN")
        page = options.get("page")
        if type(page) is not int or page < 1:
            raise ValueError("INVALID_DOCUMENT_PAGE")
        result = knowledge.get_uploaded_document_page(options.get("document_id"), page)
        result = dict(result)
        original = str(result.get("text") or "")
        result["text"] = original[:OUTPUT_LIMIT]
        result["truncated"] = len(original) > OUTPUT_LIMIT
        return result
    if action == "file_analyze":
        source = _context().resolve_path(query)
        if not source.is_file() or source.suffix.lower() == ".pdf":
            raise ValueError("USE_INDEXED_DOCUMENT_FOR_PDF")
        operation = options.get("operation", "analyze")
        if operation not in {"inspect", "analyze", "summarize"}:
            raise ValueError("INVALID_FILE_OPERATION")
        job = app.create_file_analysis_job(
            str(source), str(instruction or "Analyze this file"), source.suffix.lstrip("."),
            3000, operation, chat_id=_context().chat_id, run_id=_context().run_id,
        )
        app.start_file_analysis_job(job["id"])
        return {"job_id": job["id"], "status": job["status"], "operation": operation}
    if action == "file_analysis_status":
        if not re.fullmatch(r"[a-f0-9]{12}", str(query or "")):
            raise ValueError("INVALID_FILE_JOB_ID")
        with app.BATCH_LOCK:
            job = app.load_batch_jobs().get(query)
        if not job or job.get("kind") != "file_analysis":
            raise ValueError("FILE_JOB_NOT_FOUND")
        context = _context()
        if job.get("chat_id") and job["chat_id"] != context.chat_id:
            raise ValueError("FILE_JOB_OUTSIDE_CHAT")
        source = Path(job["input_path"]).resolve()
        if source not in context.upload_paths:
            source = context.resolve_path(job["input_path"])
            if str(source) != job["input_path"]:
                raise ValueError("FILE_JOB_OUTSIDE_WORKSPACE")
        return {key: value for key, value in job.items() if key not in {"input_path", "result"}} | {
            "result": str(job.get("result") or "")[:OUTPUT_LIMIT]
        }
    raise ValueError("UNKNOWN_DOCUMENT_TOOL")


def execute(action, goal, query=None, instruction=None, files=None, options=None):
    options = _options(options)
    if action == "workspace_status":
        context = _context()
        return code_workspaces.status(context.workspace()["workspace_id"])
    if action == "shell_workspace":
        return _workspace_shell(query)
    if action.startswith("git_"):
        return _git_tool(action, query, options)
    if action == "vision_analyze":
        return _vision(query, goal, options)
    if action in {"image_generate", "image_edit", "image_job_status"}:
        return _image_tool(action, query, goal, options)
    if action in {"document_search", "document_page", "file_inspect", "file_pii_audit", "file_analyze", "file_analysis_status"}:
        return _document_tool(action, query, instruction, options)
    raise ValueError("UNKNOWN_RUNTIME_TOOL")
