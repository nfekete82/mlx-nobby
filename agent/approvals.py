"""The existing one-shot approval store, safety checks and action handlers."""

from copy import deepcopy
import json
import re
import subprocess
import time as _agent_time
import uuid as _agent_uuid
import urllib.request
import urllib.error

from agent import code_workspaces, run_state
from agent.evidence import normalize_agent_conversation_context
from agent.permissions import Decision, ToolPermissionError


class ApprovalError(ValueError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_agent_docker_target(target):
    target = str(target or "").strip()

    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
        target,
    ):
        raise ValueError(
            "Ungültiger Docker-Containername"
        )

    return target



def validate_agent_patch_id(target):
    target = str(target or "").strip()

    if not re.fullmatch(r"[a-fA-F0-9]{16}", target):
        raise ValueError(
            "Ungültige Patch-ID"
        )

    return target



class AgentApprovals:
    def __init__(self, registry, pending, lock, ttl=300):
        self.registry = registry
        self.pending = pending
        self.lock = lock
        self.ttl = ttl

    def take(self, approval_id):
        with self.lock:
            pending = self.pending.pop(approval_id, None)
        if pending is None:
            raise ApprovalError(404, "Freigabe nicht gefunden oder bereits verwendet")
        if _agent_time.time() > pending["expires_at"]:
            raise ApprovalError(410, "Freigabe ist abgelaufen")
        return pending

    def permission(self, operation, target, context):
        if operation == "code_apply":
            permission, risks, arguments = "WRITE", ("workspace",), {"patch_id": target}
        elif operation == "docker_restart":
            permission, risks, arguments = "EXECUTE", (), {}
        else:
            raise ValueError(f"Nicht freigegebene Agent-Aktion: {operation}")
        decision = self.registry.permission_engine.decide(
            permission, risks, context, arguments, tool_name=operation,
        )
        if decision.decision == Decision.DENY:
            raise ToolPermissionError(operation, decision)
        return decision


    def create(self,
        goal,
        observations,
        step,
        mode,
        operation,
        target,
        reason,
        conversation_context=None,
        *, runtime=None, progress_callback=None, tool_request=None,
    ):
        mode = str(mode or "diagnostic").strip().lower()

        context = runtime.context if runtime is not None else (
            run_state.current_run_context() or run_state.RunContext.start()
        )
        if tool_request is not None:
            return self._create_tool_approval(
                goal, observations, step, mode, operation, target, reason,
                conversation_context, runtime, progress_callback, context, tool_request,
            )

        if operation not in {
            "docker_restart",
            "code_apply",
        }:
            raise ValueError(
                f"Nicht freigegebene Agent-Aktion: {operation}"
            )

        if operation == "code_apply" and mode != "coding":
            raise ValueError(
                "code_apply ist ausschließlich im Coding-Modus verfügbar"
            )
        if operation == "docker_restart" and mode != "diagnostic":
            raise ValueError(
                "docker_restart ist ausschließlich im Diagnose-Modus verfügbar"
            )

        if operation == "docker_restart":
            target = validate_agent_docker_target(target)

        elif operation == "code_apply":
            target = validate_agent_patch_id(target)

        permission_decision = self.permission(operation, target, context)

        if operation == "code_apply":
        # Approve only a patch that actually exists.
            patch_state = code_workspaces.diff(target)
            if patch_state.get("status") != "proposed":
                raise ValueError("code_apply benötigt einen vorgeschlagenen Patch")

        # Diff and test must exist as successful, ordered observations
        # for this exact patch.
            diff_step = None
            test_step = None
            test_result = None

            for index, observation in enumerate(observations):
                if observation.get("status") != "completed":
                    continue

                if str(observation.get("query") or "").strip() != target:
                    continue

                if observation.get("action") == "code_diff":
                    result = observation.get("result") or {}
                    if result.get("patch_id") == target:
                        diff_step = index

                if observation.get("action") == "code_test":
                    result = observation.get("result") or {}
                    checks_run = result.get("checks_run")
                    if (
                        result.get("patch_id") == target
                        and result.get("passed") is True
                        and result.get("test_status") == "passed"
                        and type(checks_run) is int
                        and checks_run > 0
                    ):
                        test_step = index
                        test_result = result

            if (
                diff_step is None
                or test_step is None
                or diff_step >= test_step
            ):
                raise ValueError(
                    "code_apply benötigt vorher code_diff und danach einen "
                    "erfolgreichen code_test"
                )

        approval_id = _agent_uuid.uuid4().hex
        now = _agent_time.time()

        pending = {
            "id": approval_id,
            "run_context": context,
            "runtime": runtime,
            "progress_callback": progress_callback,
            "operation": operation,
            "target": target,
            "reason": str(reason or "").strip(),
            "goal": goal,
            "mode": mode,
            "conversation_context": normalize_agent_conversation_context(
                conversation_context
            ),
            "observations": deepcopy(observations),
            "step": step,
            "created_at": now,
            "expires_at": now + self.ttl,
        }

        with self.lock:
            self.pending[approval_id] = pending

        return {
            "approval_id": approval_id,
            "permission_decision": permission_decision.as_dict(),
            "operation": operation,
            "target": target,
            "reason": pending["reason"],
            "expires_in": self.ttl,
            **({
                "change_set_id": patch_state.get("change_set_id", target),
                "summary": patch_state.get("summary", {}),
                "files": [
                    {
                        "path": entry.get("path"),
                        "operation": entry.get("operation"),
                    }
                    for entry in patch_state.get("files", [])
                ],
                "tests": {
                    "passed": bool((test_result or {}).get("passed")),
                    "test_status": (test_result or {}).get("test_status"),
                    "checks_run": (test_result or {}).get("checks_run", 0),
                    "results": len((test_result or {}).get("results", [])),
                },
            } if operation == "code_apply" else {}),
        }


    def _create_tool_approval(self, goal, observations, step, mode, operation, target,
                              reason, conversation_context, runtime, progress_callback,
                              context, tool_request):
        # Legacy mutations retain their dedicated validation and verification path.
        if operation in {"code_apply", "docker_restart"}:
            raise ValueError("LEGACY_ACTION_REQUIRES_EXPLICIT_APPROVAL")
        if runtime is None or runtime.registry is not self.registry:
            raise ValueError("APPROVAL_RUNTIME_REQUIRED")
        allowed = self.registry.names(permission="READ")
        if mode == "coding":
            allowed |= self.registry.names(permission="PREPARE")
        if operation not in allowed:
            raise ValueError("TOOL_NOT_ALLOWED_IN_MODE")
        tool = self.registry.get(operation)
        arguments = deepcopy(tool_request)
        decision = self.registry.permission_engine.evaluate(tool, context, arguments)
        if decision.decision == Decision.DENY:
            raise ToolPermissionError(operation, decision)
        approval_id = _agent_uuid.uuid4().hex
        now = _agent_time.time()
        pending = {
            "id": approval_id, "run_context": context, "runtime": runtime,
            "progress_callback": progress_callback,
            "operation": operation, "target": target,
            "reason": str(reason or "").strip(), "goal": goal, "mode": mode,
            "conversation_context": normalize_agent_conversation_context(conversation_context),
            "observations": deepcopy(observations), "step": step,
            "created_at": now, "expires_at": now + self.ttl,
            "tool_arguments": arguments, "approved_tool": tool,
        }
        with self.lock:
            self.pending[approval_id] = pending
        return {
            "approval_id": approval_id, "permission_decision": decision.as_dict(),
            "operation": operation, "target": target, "reason": pending["reason"],
            "expires_in": self.ttl,
        }

    def execute(self, pending):
        context = pending.get("run_context") or run_state.current_run_context() or run_state.RunContext.start()
        with run_state.bind_run_context(context):
            return self._execute(pending, context)

    def _execute(self, pending, context):
        operation = pending["operation"]
        target = pending["target"]
        if "tool_arguments" in pending:
            result = self.registry.execute_approved(
                operation, run_context=context, expected_tool=pending["approved_tool"],
                **pending["tool_arguments"],
            )
            return {"operation": operation, "target": target, "returncode": 0,
                    "stdout": "", "stderr": "", "tool_result": result}
        self.permission(operation, target, context)

        if operation == "code_apply":
            patch_id = validate_agent_patch_id(target)

            result = code_workspaces.apply(
                patch_id,
                approved=True,
            )

            return {
                "operation": operation,
                "target": patch_id,
                "returncode": 0,
                "stdout": "Patch erfolgreich angewendet",
                "stderr": "",
                "apply_result": result,
            }

        if operation != "docker_restart":
            raise ValueError(
                "Nicht freigegebene Agent-Aktion"
            )

        target = validate_agent_docker_target(target)

        result = subprocess.run(
            [
                "docker",
                "restart",
                target,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )

        return {
            "operation": operation,
            "target": target,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-10000:],
            "stderr": (result.stderr or "")[-10000:],
        }


    def verify(self, pending):
        """
        Perform mandatory technical verification after an approved
        state-changing action.
        """
        operation = pending["operation"]
        target = pending["target"]

        if operation == "code_apply":
            patch_id = validate_agent_patch_id(target)

            try:
                patch_diff = code_workspaces.diff(patch_id)
                tests = code_workspaces.test(patch_id)
                files = code_workspaces.verify(patch_id)

                patch_status = patch_diff.get("status")
                tests_ok = tests.get("passed") is True
                files_ok = files.get("verified") is True

                verified = (
                    patch_status == "applied"
                    and tests_ok
                    and files_ok
                )

                return {
                    "verified": verified,
                    "checks": [
                        {
                            "check": "patch_status",
                            "ok": patch_status == "applied",
                            "status": patch_status,
                        },
                        {
                            "check": "code_test",
                            "ok": tests_ok,
                            "result": tests,
                        },
                        {
                            "check": "workspace_files",
                            "ok": files_ok,
                            "result": files,
                        },
                    ],
                    "patch_id": patch_id,
                }

            except Exception as exc:
                return {
                    "verified": False,
                    "checks": [],
                    "patch_id": patch_id,
                    "error": str(exc),
                }

        if operation != "docker_restart":
            return {
                "verified": False,
                "checks": [],
                "error": (
                    "Für diese Aktion existiert noch keine "
                    "Verifikationsroutine"
                ),
            }

        checks = []

        # Allow a short startup delay after a restart.
        _agent_time.sleep(2)

        # -----------------------------------------------------
        # Docker-State / Health
        # -----------------------------------------------------

        try:
            inspect_result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .State}}",
                    target,
                ],
                capture_output=True,
                text=True,
                timeout=15,
                stdin=subprocess.DEVNULL,
            )

            state_raw = (
                inspect_result.stdout or ""
            ).strip()

            state = {}

            if (
                inspect_result.returncode == 0
                and state_raw
            ):
                try:
                    state = json.loads(state_raw)
                except Exception:
                    state = {}

            running = bool(
                state.get("Running", False)
            )

            health = (
                state.get("Health", {}) or {}
            ).get("Status")

            docker_ok = (
                inspect_result.returncode == 0
                and running
                and health not in {
                    "unhealthy",
                }
            )

            checks.append({
                "check": "docker_state",
                "ok": docker_ok,
                "running": running,
                "health": health,
                "exit_code": state.get("ExitCode"),
                "error": (
                    inspect_result.stderr or ""
                ).strip(),
            })

        except Exception as exc:
            docker_ok = False

            checks.append({
                "check": "docker_state",
                "ok": False,
                "error": str(exc),
            })

        # -----------------------------------------------------
        # Determine published ports
        # -----------------------------------------------------

        published_ports = []

        try:
            port_result = subprocess.run(
                [
                    "docker",
                    "port",
                    target,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )

            if port_result.returncode == 0:
                for line in (
                    port_result.stdout or ""
                ).splitlines():

                    if "->" not in line:
                        continue

                    _, host_part = line.split(
                        "->",
                        1,
                    )

                    host_part = host_part.strip()

                    # Beispiele:
                    # 0.0.0.0:3000
                    # [::]:3000
                    match = re.search(
                        r":(\d+)$",
                        host_part,
                    )

                    if match:
                        port = int(
                            match.group(1)
                        )

                        if port not in published_ports:
                            published_ports.append(
                                port
                            )

        except Exception as exc:
            checks.append({
                "check": "docker_ports",
                "ok": False,
                "error": str(exc),
            })

        # -----------------------------------------------------
        # HTTP-Verifikation
        # -----------------------------------------------------

        http_ok = None

        if published_ports:
            http_ok = False

            # Check only the first published port.
            port = published_ports[0]
            url = f"http://127.0.0.1:{port}/"

            last_error = None
            status_code = None

            # Some applications need a few seconds after a Docker restart
            # before HTTP becomes available.
            for attempt in range(1, 6):
                try:
                    request = urllib.request.Request(
                        url,
                        method="GET",
                        headers={
                            "User-Agent": (
                                "MLX-Nobby-Agent/1.0"
                            ),
                        },
                    )

                    with urllib.request.urlopen(
                        request,
                        timeout=8,
                    ) as response:
                        status_code = (
                            response.status
                        )

                    if 200 <= status_code < 500:
                        http_ok = True
                        break

                except urllib.error.HTTPError as exc:
                    status_code = exc.code

                    if 200 <= exc.code < 500:
                        http_ok = True
                        break

                    last_error = str(exc)

                except Exception as exc:
                    last_error = str(exc)

                if attempt < 5:
                    _agent_time.sleep(2)

            checks.append({
                "check": "http",
                "ok": http_ok,
                "url": url,
                "status_code": status_code,
                "error": last_error,
            })

        else:
            checks.append({
                "check": "http",
                "ok": None,
                "reason": (
                    "Container veröffentlicht keinen "
                    "ermittelbaren TCP-Port"
                ),
            })

        # Docker must be running.
        #
        # HTTP must succeed when a port is available.
        verified = bool(
            docker_ok
            and (
                http_ok is True
                or http_ok is None
            )
        )

        return {
            "verified": verified,
            "operation": operation,
            "target": target,
            "checks": checks,
        }
