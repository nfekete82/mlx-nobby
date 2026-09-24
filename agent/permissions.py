"""Additional policy gate; tool handlers retain all existing safety checks."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from agent import code_workspaces


class Decision(str, Enum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"


class Risk(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    CREATE = "CREATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    EXTERNAL = "EXTERNAL"
    PRIVILEGED = "PRIVILEGED"


@dataclass(frozen=True)
class PermissionDecision:
    decision: Decision
    reason: str

    def as_dict(self):
        return {"decision": self.decision.value, "reason": self.reason}


class ToolPermissionError(ValueError):
    def __init__(self, tool_name, decision):
        self.tool_name = tool_name
        self.decision = decision
        super().__init__(f"{decision.decision.value}: {decision.reason}")


@dataclass(frozen=True)
class PermissionPolicy:
    allow_workspace_writes: bool = False


_RISK_ALIASES = {
    "workspace": Risk.READ,
    "filesystem": Risk.READ,
    "network": Risk.EXTERNAL,
    "host_process": Risk.EXECUTE,
    "executes_project_code": Risk.EXECUTE,
    "writes_test_copy": Risk.EXECUTE,
    "writes_patch_metadata": Risk.CREATE,
    "destructive": Risk.DELETE,
}
_LEGACY_READ_EXECUTION = {"shell_read", "process_usage", "code_test", "git_status", "git_diff", "git_log"}


class PermissionEngine:
    def __init__(self, policy=None):
        self.policy = policy or PermissionPolicy()

    def evaluate(self, tool, context, arguments):
        return self.decide(tool.permission, tool.risks, context, arguments, tool_name=tool.name)

    def decide(self, permission, risks, context, arguments, *, tool_name=""):
        if permission == "PREPARE" and tool_name != "code_patch":
            return PermissionDecision(Decision.DENY, "UNKNOWN_PREPARE_ACTION")
        try:
            if not isinstance(risks, tuple) or not all(isinstance(risk, str) for risk in risks):
                raise ValueError("INVALID_PERMISSION_METADATA")
            categories = {Risk.READ if permission == "PREPARE" else Risk(permission)}
            for risk in risks:
                categories.add(_RISK_ALIASES[risk] if risk in _RISK_ALIASES else Risk(risk))
        except (ValueError, TypeError):
            return PermissionDecision(Decision.DENY, "INVALID_PERMISSION_METADATA")

        if context is None:
            return PermissionDecision(Decision.DENY, "RUN_CONTEXT_REQUIRED")
        if context.cancelled:
            return PermissionDecision(Decision.DENY, "RUN_CANCELLED")
        if Risk.PRIVILEGED in categories:
            return PermissionDecision(Decision.DENY, "PRIVILEGED_ACTION_BLOCKED")

        workspace_required = bool({"workspace", "filesystem"}.intersection(risks))
        paths = []
        try:
            for key in ("path", "source_path", "destination_path"):
                if arguments.get(key) is not None:
                    paths.append(arguments[key])
            if tool_name == "code_read" and arguments.get("query"):
                paths.append(re.sub(r":\d+(?:-\d+)?$", "", str(arguments["query"])))
            if tool_name == "code_patch" and isinstance(arguments.get("files"), list):
                paths.extend(entry["path"] for entry in arguments["files"] if isinstance(entry, dict) and "path" in entry)
            options = arguments.get("options")
            if tool_name == "shell_workspace":
                from agent.runtime_tools import workspace_shell_arguments
                from agent.run_state import bind_run_context
                with bind_run_context(context):
                    workspace_shell_arguments(arguments.get("query"))
            if tool_name in {"git_stage", "git_commit"}:
                if not isinstance(options, dict) or not isinstance(options.get("paths"), list) or not 0 < len(options["paths"]) <= 30:
                    raise ValueError("GIT_PATHS_REQUIRED")
                if any(not isinstance(path, str) or path.startswith(":") or any(char in path for char in "*?[]") for path in options["paths"]):
                    raise ValueError("GIT_LITERAL_FILE_PATHS_REQUIRED")
                if tool_name == "git_commit":
                    message = options.get("message")
                    if not isinstance(message, str) or not message.strip() or len(message) > 200 or "\n" in message:
                        raise ValueError("INVALID_COMMIT_MESSAGE")
                paths.extend(options["paths"])
            if tool_name in {"vision_analyze", "image_edit", "video_animate"} and isinstance(options, dict) and options.get("upload_path"):
                if Path(str(options["upload_path"])).resolve() not in context.upload_paths:
                    raise ValueError("UPLOAD_OUTSIDE_RUN")
            if tool_name == "vision_analyze":
                if not (isinstance(options, dict) and (options.get("artifact_id") or options.get("upload_path"))):
                    paths.append(arguments.get("query"))
            if isinstance(options, dict) and options.get("artifact_id") and context.resources_bound:
                if options["artifact_id"] not in context.artifact_ids:
                    raise ValueError("IMAGE_ARTIFACT_OUTSIDE_RUN")
            if tool_name in {"document_search", "document_page"} and context.resources_bound:
                if not isinstance(options, dict) or options.get("document_id") not in context.document_ids:
                    raise ValueError("DOCUMENT_OUTSIDE_RUN")
            if tool_name in {"file_inspect", "file_pii_audit", "file_analyze"}:
                paths.append(arguments.get("query"))
            if tool_name == "git_diff" and arguments.get("query"):
                paths.append(arguments["query"])

            patch_id = arguments.get("patch_id")
            if tool_name in {"code_diff", "code_test"}:
                patch_id = arguments.get("query")
            if patch_id is not None:
                if not isinstance(patch_id, str) or not re.fullmatch(r"[a-fA-F0-9]{16}", patch_id):
                    raise ValueError("INVALID_PATCH_ID")
                patch = code_workspaces._patch(patch_id)
                if patch["workspace_id"] != context.workspace()["workspace_id"]:
                    raise ValueError("PATCH_OUTSIDE_WORKSPACE")
                paths.extend(entry["path"] for entry in patch["files"])
                if tool_name == "code_apply" and any(
                    entry.get("operation") == "DELETE" for entry in patch["files"]
                ):
                    categories.add(Risk.DELETE)
                workspace_required = True

            if workspace_required or paths:
                context.workspace()
            if tool_name in {"code_files", "code_search", "code_test"}:
                context.resolve_path(".")
            for path in paths:
                target = context.resolve_path(path, write=bool(categories & {Risk.WRITE, Risk.CREATE, Risk.DELETE}))
                if tool_name in {"git_stage", "git_commit"} and target.is_dir():
                    raise ValueError("GIT_LITERAL_FILE_PATHS_REQUIRED")
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return PermissionDecision(Decision.DENY, str(exc))

        if Risk.DELETE in categories:
            return PermissionDecision(Decision.CONFIRM, "DELETE_REQUIRES_APPROVAL")
        if Risk.EXECUTE in categories:
            if not (permission == "READ" and tool_name in _LEGACY_READ_EXECUTION):
                return PermissionDecision(Decision.CONFIRM, "EXECUTION_REQUIRES_APPROVAL")
        if categories & {Risk.WRITE, Risk.CREATE}:
            if permission == "PREPARE" and set(risks) == {"writes_patch_metadata", "workspace"}:
                return PermissionDecision(Decision.ALLOW, "PATCH_PREPARATION_ONLY")
            if self.policy.allow_workspace_writes and paths:
                return PermissionDecision(Decision.ALLOW, "WORKSPACE_WRITE_POLICY")
            return PermissionDecision(Decision.CONFIRM, "WRITE_REQUIRES_APPROVAL")
        return PermissionDecision(Decision.ALLOW, "EXISTING_READ_POLICY")
