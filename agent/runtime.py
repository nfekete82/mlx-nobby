"""The existing agent loop, with explicit run, provider and tool dependencies."""

from contextvars import ContextVar
from dataclasses import dataclass
import logging
import re
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from agent import code_workspaces, run_state
from agent.model_provider import ModelProvider, ModelRequest, ProviderError
from agent.permissions import Decision, ToolPermissionError
from agent.tool_registry import ToolRegistry


@dataclass(frozen=True)
class RuntimePolicy:
    diagnostic_steps: int = 6
    research_steps: int = 6
    coding_steps: int = 24
    orchestrator_steps: int = 12
    research_continuation_steps: int = 3

    def __post_init__(self):
        for name, value in vars(self).items():
            minimum = 0 if name == "research_continuation_steps" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"Invalid runtime limit: {name}")

    def max_steps(self, mode):
        return {
            "research": self.research_steps,
            "coding": self.coding_steps,
            "orchestrator": self.orchestrator_steps,
        }.get(mode, self.diagnostic_steps)


@dataclass(frozen=True)
class RuntimeHooks:
    """Bindings for extracted prompts/evidence and the existing approval service."""

    coding_read_only_fast_final_requested: Callable
    ambiguous_delete_reference: Callable
    agent_choose_next_step_v2: Callable
    agent_coding_read_only_final_answer: Callable
    agent_v2_final_answer: Callable
    orchestrator_missing_evidence: Callable
    orchestrator_unresolved_subagent_quality: Callable
    orchestrator_delegate_attempts: Callable
    orchestrator_duplicate_delegation: Callable
    create_agent_approval: Callable
    build_subagent_report: Callable
    assess_subagent_report: Callable
    compact_agent_observations: Callable
    sanitize_orchestrator_web_query: Callable
    boost_orchestrator_research_query: Callable
    degraded_empty_web_search_count: Callable
    canonical_github_repo_from_goal: Callable
    execute_agent_approved_action: Callable | None = None
    verify_agent_action: Callable | None = None


_CURRENT_RUNTIME = ContextVar("mlx_agent_runtime", default=None)


def current_runtime():
    return _CURRENT_RUNTIME.get()


class _RunCancelled(Exception):
    pass


class AgentRuntime:
    def __init__(self, context: run_state.RunContext, provider: ModelProvider,
                 registry: ToolRegistry, hooks: RuntimeHooks, policy=None, logger=None):
        if registry.permission_engine is None:
            raise ValueError("AgentRuntime requires a registry with a permission engine")
        self.context = context
        self.provider = provider
        self.registry = registry
        self.hooks = hooks
        self.policy = policy or RuntimePolicy()
        self.logger = logger or logging.getLogger(__name__)
        self.model_role = "agent"

    def _check_cancelled(self):
        if self.context.cancelled:
            raise _RunCancelled()

    def complete_model(self, request: ModelRequest):
        self._check_cancelled()
        try:
            response = self.provider.complete(request, run_context=self.context)
        except ProviderError as exc:
            self._check_cancelled()
            if exc.code == "cancelled":
                self.context.cancel()
                raise _RunCancelled() from exc
            raise
        self._check_cancelled()
        return response

    def _model_hook(self, function, *args, **kwargs):
        self._check_cancelled()
        result = function(*args, **kwargs)
        self._check_cancelled()
        return result

    def _execute_tool(self, action, goal, query=None, instruction=None, files=None, options=None):
        self._check_cancelled()
        result = self.registry.execute(
            action, run_context=self.context, goal=goal, query=query,
            instruction=instruction, files=files, options=options,
        )
        return result

    def _allowed_tools(self, mode):
        allowed = set(self.registry.names(permission="READ"))
        allowed.update(self.registry.names(permission="EXECUTE"))
        allowed.update(self.registry.names(permission="CREATE"))
        if "image_edit" in self.registry.names(permission="WRITE"):
            allowed.add("image_edit")
        if mode == "coding":
            allowed.update(self.registry.names(permission="PREPARE"))
            allowed.update(self.registry.names(permission="WRITE"))
        return allowed

    def _publish(self, callback, status, observations, current_step=None, pending_action=None):
        if callback:
            try:
                callback(status, observations, current_step, pending_action)
            except Exception:
                self.logger.exception(
                    "Agent progress callback failed (status=%s, current_step=%r)",
                    status, current_step,
                )

    def resume_approval(self, pending, approved):
        """Continue the consumed approval with the original dependencies and run state."""
        if pending.get("run_context") is not None and pending["run_context"] is not self.context:
            raise ValueError("APPROVAL_RUN_CONTEXT_CHANGED")
        if pending.get("runtime") is not None and pending["runtime"] is not self:
            raise ValueError("APPROVAL_RUNTIME_CHANGED")
        observations = list(pending["observations"])
        step = int(pending["step"])
        callback = pending.get("progress_callback")
        operation = pending["operation"]
        target = pending["target"]
        token = _CURRENT_RUNTIME.set(self)
        try:
            with run_state.bind_run_context(self.context):
                try:
                    self._check_cancelled()
                    self._publish(callback, "running", observations)
                    verification = None
                    if not approved:
                        observations.append({
                            "step": step, "action": operation, "target": target,
                            "status": "rejected_by_user",
                        })
                    else:
                        try:
                            self._check_cancelled()
                            result = self.hooks.execute_agent_approved_action(pending)
                            observation = {
                                "step": step, "action": operation, "target": target,
                                "status": "completed" if result["returncode"] == 0 else "failed",
                                "result": result.get("tool_result") if "tool_arguments" in pending else result,
                            }
                            if "tool_arguments" in pending:
                                arguments = pending["tool_arguments"]
                                observation.update(
                                    query=arguments.get("query"),
                                    options=arguments.get("options") or None,
                                    instruction=arguments.get("instruction") or None,
                                    reason=pending["reason"],
                                )
                            observations.append(observation)
                            self._check_cancelled()
                            if result["returncode"] == 0 and "tool_arguments" not in pending:
                                verification = self.hooks.verify_agent_action(pending)
                                observations.append({
                                    "step": step, "action": "verify_change", "target": target,
                                    "status": "completed" if verification.get("verified") else "failed",
                                    "result": verification,
                                })
                                self._check_cancelled()
                        except _RunCancelled:
                            raise
                        except Exception as exc:
                            observation = {
                                "step": step, "action": operation, "target": target,
                                "status": "failed", "error": str(exc),
                            }
                            if isinstance(exc, ToolPermissionError):
                                observation["permission_decision"] = exc.decision.as_dict()
                            observations.append(observation)
                            self._check_cancelled()
                    self._publish(callback, "running", observations)
                    if operation == "code_apply" and verification and verification.get("verified") is True:
                        untested = any(item.get("action") == "code_test"
                            and item.get("query") == target
                            and (item.get("result") or {}).get("test_status") == "no_checks"
                            for item in observations)
                        result = {
                            "status": "completed", "goal": pending["goal"], "steps": observations,
                            "pending_action": None,
                            "answer": ("Änderung angewendet und Dateien verifiziert; "
                                       "nicht getestet (keine geeigneten Tests)." if untested else
                                       "Änderung erfolgreich angewendet und verifiziert."),
                        }
                        self._publish(callback, "completed", observations)
                        return result
                    return self.run(
                        pending["goal"], observations, step + 1,
                        mode=pending.get("mode", "diagnostic"),
                        conversation_context=pending.get("conversation_context"),
                        progress_callback=callback,
                    )
                except _RunCancelled:
                    result = {"status": "cancelled", "goal": pending["goal"],
                              "steps": observations, "pending_action": None, "answer": ""}
                    self._publish(callback, "cancelled", observations)
                    return result
        finally:
            _CURRENT_RUNTIME.reset(token)

    def run(self, goal, observations=None, start_step=1, mode="diagnostic",
            conversation_context=None, progress_callback=None, allow_approval=True):
        goal = str(goal or "").strip()
        if not goal:
            raise ValueError("Kein Agent-Ziel angegeben")
        observations = list(observations or [])
        token = _CURRENT_RUNTIME.set(self)
        try:
            with run_state.bind_run_context(self.context):
                try:
                    self._check_cancelled()
                    return self._run_loop(
                        goal, observations, start_step, mode, conversation_context,
                        progress_callback, allow_approval,
                    )
                except _RunCancelled:
                    result = {"status": "cancelled", "goal": goal, "steps": observations,
                              "pending_action": None, "answer": ""}
                except ProviderError as exc:
                    result = {"status": "failed", "goal": goal, "steps": observations,
                              "answer": str(exc), "error": {"code": exc.code, "detail": str(exc)}}
                self._publish(progress_callback, result["status"], observations)
                return result
        finally:
            _CURRENT_RUNTIME.reset(token)

    def _run_loop(self, goal, observations, start_step, mode, conversation_context,
                  progress_callback, allow_approval):
        previous_role = self.model_role
        self.model_role = "coding" if str(mode).strip().lower() == "coding" else "agent"
        try:
            return self._run_loop_body(
                goal, observations, start_step, mode, conversation_context,
                progress_callback, allow_approval,
            )
        finally:
            self.model_role = previous_role

    def _run_loop_body(self, goal, observations, start_step, mode, conversation_context,
                       progress_callback, allow_approval):
        goal = str(goal or "").strip()
        mode = str(mode or "diagnostic").strip().lower()

        # Explicit read-only analysis of a named workspace file is a coding
        # task even if the caller omitted mode="coding". This keeps simple
        # file analysis independent from model-based routing decisions.
        if (
            mode == "diagnostic"
            and self.hooks.coding_read_only_fast_final_requested(goal)
        ):
            explicit_file_match = re.search(
                r"(?<![A-Za-z0-9_.-])"
                r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"
                r"\.[A-Za-z0-9]{1,12})"
                r"(?![A-Za-z0-9_.-])",
                goal,
            )

            if explicit_file_match:
                try:
                    self._execute_tool("code_read", goal, query=explicit_file_match.group(1))
                except (OSError, ValueError):
                    pass
                else:
                    mode = "coding"
                    self.model_role = "coding"

        max_steps = self.policy.max_steps(mode)
        research_continuation_steps = self.policy.research_continuation_steps if mode == "research" else 0
        loop_max_steps = max_steps + research_continuation_steps

        def publish(status="running", current_step=None, pending_action=None):
            self._publish(progress_callback, status, observations, current_step, pending_action)

        if mode == "coding" and self.hooks.ambiguous_delete_reference(
            goal,
            conversation_context,
        ):
            result={
                "status": "completed",
                "goal": goal,
                "steps": observations,
                "answer": (
                    "Welche konkrete Datei, Seite oder welches Modul soll "
                    "gelöscht werden? Ohne eindeutige Referenz bereite ich "
                    "keinen DELETE-Patch vor."
                ),
            }
            publish("completed")
            return result

        for step in range(
            start_step,
            loop_max_steps + 1,
        ):
            self._check_cancelled()
            # Additional research steps are allowed only to continue an
            # already loaded, truncated web source.
            if mode == "research" and step > max_steps:
                continuation_available = any(
                    isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("action") == "fetch_url"
                    and isinstance(item.get("result"), dict)
                    and item.get("result", {}).get("ok") is True
                    and item.get("result", {}).get("truncated") is True
                    and item.get("result", {}).get("next_offset") is not None
                    for item in observations
                )

                if not continuation_available:
                    break
            # ---------------------------------------------------------
            # Read-only coding fast final
            # ---------------------------------------------------------
            # For an explicit analysis/review request without writes, a
            # successfully completed code_read already provides all evidence
            # needed for final synthesis. Skip another planner LLM round.
            if (
                mode == "coding"
                and self.hooks.coding_read_only_fast_final_requested(goal)
            ):
                completed_code_reads = [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("action") == "code_read"
                    and item.get("status") == "completed"
                    and isinstance(item.get("result"), dict)
                    and isinstance(
                        item.get("result", {}).get("content"),
                        str,
                    )
                    and bool(
                        item.get("result", {}).get("content")
                    )
                ]

                if completed_code_reads:
                    final_answer = self._model_hook(self.hooks.agent_coding_read_only_final_answer,
                        goal,
                        observations,
                    )

                    result = {
                        "status": "completed",
                        "goal": goal,
                        "steps": observations,
                        "answer": final_answer,
                    }

                    publish("completed")
                    return result

            # A prepared change set has a fixed, cheap next step. Keep the
            # patch in the existing approval workflow without another model
            # round for diff, test, or the final apply request.
            prepared = next((item for item in reversed(observations)
                if item.get("action") == "code_patch"
                and item.get("status") == "completed"
                and isinstance(item.get("result"), dict)
                and item["result"].get("patch_id")), None) if mode == "coding" else None
            workflow_decision = None
            if prepared:
                patch_id = prepared["result"]["patch_id"]
                patch_index = observations.index(prepared)
                subsequent = observations[patch_index + 1:]
                if any(item.get("action") == "code_apply"
                       and item.get("target") == patch_id
                       and item.get("status") in {"rejected_by_user", "completed"}
                       for item in subsequent):
                    prepared = None
            if prepared:
                diff_done = any(item.get("action") == "code_diff"
                    and item.get("status") == "completed"
                    and item.get("query") == patch_id for item in subsequent)
                tested = next((item for item in reversed(subsequent)
                    if item.get("action") == "code_test"
                    and item.get("status") == "completed"
                    and item.get("query") == patch_id), None)
                if not diff_done:
                    workflow_decision = {"action": "code_diff", "query": patch_id}
                elif tested is None:
                    workflow_decision = {"action": "code_test", "query": patch_id}
                elif tested.get("result", {}).get("test_status") in {"passed", "no_checks"} and allow_approval:
                    workflow_decision = {
                        "action": "request_approval", "operation": "code_apply",
                        "target": patch_id,
                        "reason": "Patch geprüft; Anwendung benötigt Zustimmung"
                    }
            if workflow_decision is None:
                publish("running", {
                    "step": step, "action": "agent_plan",
                    "reason": "Nächsten sicheren Schritt planen", "status": "running",
                })
            # ---------------------------------------------------------
            # Deterministic coding fast path for an explicitly named file
            # ---------------------------------------------------------
            # Do not spend a model planning round deciding whether an
            # explicitly named workspace file should be read. On the first
            # coding step we can safely route that request directly to
            # code_read. After the read, normal model reasoning resumes.
            decision = workflow_decision
            prefetched_read = None

            if mode == "coding" and not observations:
                explicit_file_match = re.search(
                    r"(?<![A-Za-z0-9_.-])"
                    r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"
                    r"\.[A-Za-z0-9]{1,12})"
                    r"(?![A-Za-z0-9_.-])",
                    str(goal or ""),
                )

                if explicit_file_match:
                    explicit_file = explicit_file_match.group(1)

                    try:
                        prefetched_read = self._execute_tool("code_read", goal, query=explicit_file)
                    except (OSError, ValueError):
                        # Unknown, ambiguous or unavailable file:
                        # fall back to normal model-driven discovery.
                        pass
                    else:
                        decision = {
                            "action": "code_read",
                            "query": explicit_file,
                            "reason": (
                                "Explizit genannte Datei direkt lesen"
                            ),
                            "plan": [
                                "Datei vollständig lesen",
                                "Aufgabe anhand des Dateiinhalts bearbeiten",
                            ],
                        }

            if decision is None:
                decision = self._model_hook(self.hooks.agent_choose_next_step_v2,
                    goal,
                    observations,
                    max_steps=max_steps,
                    mode=mode,
                    conversation_context=conversation_context,
                )

            action = str(
                decision.get("action", "")
            ).strip()
            plan = decision.get("plan")
            if isinstance(plan, list):
                plan = [
                    str(item).strip()[:500]
                    for item in plan[:12]
                    if str(item).strip()
                ]
            else:
                plan = None

            if action == "final":
                if (mode == "coding" and not prepared and
                    not any(item.get("action") == "code_apply" and
                            item.get("status") == "rejected_by_user"
                            for item in observations) and
                    re.search(r"\b(?:ändere|aendere|implementiere|repariere|"
                              r"behebe|fixe|ersetze|entferne|füge|fuege|"
                              r"erstelle|erzeuge|refaktoriere|überarbeite|"
                              r"ueberarbeite|lösche|loesche|verbessere|"
                              r"optimiere)\b", goal, re.IGNORECASE)):
                    observations.append({
                        "step": step, "action": "patch_required",
                        "status": "rejected",
                        "reason": "Änderungsauftrag benötigt einen vorbereiteten code_patch."
                    })
                    publish("running", observations[-1])
                    continue

                # For explicit cross-capability goals, the orchestrator may finish
                # only after the required data sources have been used successfully.
                if mode == "orchestrator":
                    missing = self.hooks.orchestrator_missing_evidence(
                        goal,
                        observations,
                    )

                    if missing:
                        observations.append({
                            "step": step,
                            "action": "evidence_gate",
                            "status": "rejected",
                            "reason": (
                                "Abschluss noch nicht erlaubt; "
                                "erforderliche Evidence fehlt: "
                                + ", ".join(missing)
                            ),
                        })

                        publish("running", observations[-1])
                        continue

                    unresolved_quality = (
                        self.hooks.orchestrator_unresolved_subagent_quality(
                            observations
                        )
                    )

                    if unresolved_quality:
                        still_open = []
                        exhausted = []

                        for item in unresolved_quality:
                            agent_name = str(
                                item.get("agent") or ""
                            ).strip().lower()

                            attempts = self.hooks.orchestrator_delegate_attempts(
                                observations,
                                agent_name,
                            )

                            enriched = dict(item)
                            enriched["attempts"] = attempts

                            verification_exhausted = attempts >= 3

                            if agent_name == "research":
                                research_circuit_broken = any(
                                    isinstance(observation, dict)
                                    and observation.get("action")
                                    == "web_search_circuit_breaker"
                                    and observation.get("status") == "rejected"
                                    for observation in observations
                                )

                                if research_circuit_broken:
                                    verification_exhausted = True
                                    enriched["verification_exhausted_by"] = (
                                        "web_search_circuit_breaker"
                                    )

                            if verification_exhausted:
                                exhausted.append(enriched)
                            else:
                                still_open.append(enriched)

                        if still_open:
                            details = "; ".join(
                                (
                                    str(item.get("agent") or "subagent")
                                    + ": "
                                    + str(
                                        item.get("reason")
                                        or "Verifikation erforderlich"
                                    )
                                )
                                for item in still_open
                            )

                            observations.append({
                                "step": step,
                                "action": "quality_gate",
                                "status": "rejected",
                                "reason": (
                                    "Abschluss noch nicht erlaubt; "
                                    "Subagent-Evidence benötigt Verifikation: "
                                    + details
                                ),
                                "unresolved": still_open,
                            })

                            publish("running", observations[-1])
                            continue

                        if exhausted:
                            details = "; ".join(
                                (
                                    str(item.get("agent") or "subagent")
                                    + ": "
                                    + str(item.get("attempts") or 0)
                                    + " Verifikationsversuche; "
                                    + str(
                                        item.get("reason")
                                        or "Evidence blieb unzureichend"
                                    )
                                )
                                for item in exhausted
                            )

                            observations.append({
                                "step": step,
                                "action": "verification_exhausted",
                                "status": "completed",
                                "reason": (
                                    "Weitere gleichartige Verifikationsversuche "
                                    "sind voraussichtlich nicht sinnvoll. "
                                    "Abschluss ist mit ausdrücklicher "
                                    "Kennzeichnung der Unsicherheit erlaubt: "
                                    + details
                                ),
                                "agents": exhausted,
                            })

                            publish("running", observations[-1])

                    # The orchestrator always synthesizes the final answer again
                    # using only the observations.
                    final_answer = self._model_hook(self.hooks.agent_v2_final_answer,
                        goal,
                        observations,
                    )

                elif mode in {"coding", "research"}:
                    final_answer = self._model_hook(self.hooks.agent_v2_final_answer,
                        goal,
                        observations,
                    )

                else:
                    final_answer = str(
                        decision.get("answer", "")
                    ).strip()

                    if not final_answer:
                        final_answer = self._model_hook(self.hooks.agent_v2_final_answer,
                            goal,
                            observations,
                        )

                result={
                    "status": "completed",
                    "goal": goal,
                    "steps": observations,
                    "answer": final_answer,
                }

                publish("completed")
                return result

            if action == "request_approval":
                if not allow_approval:
                    observations.append({
                        "step": step,
                        "action": "approval_guard",
                        "status": "rejected",
                        "reason": (
                            "Delegierte Spezialagenten dürfen keine "
                            "Approval-Aktionen anfordern. "
                            "Arbeite ausschließlich READ-ONLY weiter "
                            "oder schließe mit den vorhandenen "
                            "Beobachtungen ab."
                        ),
                    })
                    publish("running", observations[-1])
                    continue

                operation = str(
                    decision.get("operation", "")
                ).strip()

                target = str(
                    decision.get("target", "")
                ).strip()

                reason = str(
                    decision.get("reason", "")
                ).strip()

                try:
                    self._check_cancelled()
                    approval = self.hooks.create_agent_approval(
                        goal=goal,
                        observations=observations,
                        step=step,
                        mode=mode,
                        operation=operation,
                        target=target,
                        reason=reason,
                        conversation_context=conversation_context,
                        runtime=self, progress_callback=progress_callback,
                    )

                except _RunCancelled:
                    raise

                except Exception as exc:
                    observations.append({
                        "step": step,
                        "action": "request_approval",
                        "status": "failed",
                        "error": str(exc),
                    })
                    publish()
                    continue

                self._check_cancelled()
                result={
                    "status": "approval_required",
                    "goal": goal,
                    "steps": observations,
                    "pending_action": approval,
                }
                publish("approval_required", pending_action=approval)
                return result

            # -------------------------------------------------
            # Orchestrator v2: kontrollierte Subagent-Delegation
            # -------------------------------------------------
            if action == "delegate_agent":
                if mode != "orchestrator":
                    observations.append({
                        "step": step,
                        "action": "delegate_agent",
                        "status": "rejected",
                        "reason": (
                            "Nur der Orchestrator darf Teilaufgaben "
                            "an Spezialagenten delegieren."
                        ),
                    })
                    publish("running", observations[-1])
                    continue

                delegate_name = str(
                    decision.get("agent", "")
                ).strip().lower()

                delegate_goal = str(
                    decision.get("goal", "")
                ).strip()

                delegate_reason = str(
                    decision.get("reason", "")
                ).strip()

                delegate_modes = {
                    "research": "research",
                    "diagnostic": "diagnostic",

                    # Deliberately do not start coding_analysis in coding mode.
                    # This gives the subagent access only to read tools.
                    "coding_analysis": "orchestrator_readonly_code",
                }

                if delegate_name not in delegate_modes:
                    observations.append({
                        "step": step,
                        "action": "delegate_agent",
                        "status": "rejected",
                        "reason": (
                            "Unbekannter Spezialagent. Erlaubt sind: "
                            "research, diagnostic, coding_analysis."
                        ),
                        "agent": delegate_name or None,
                    })
                    publish("running", observations[-1])
                    continue

                if not delegate_goal:
                    observations.append({
                        "step": step,
                        "action": "delegate_agent",
                        "status": "rejected",
                        "reason": (
                            "delegate_agent benötigt ein konkretes Teilziel."
                        ),
                        "agent": delegate_name,
                    })
                    publish("running", observations[-1])
                    continue

                # -------------------------------------------------
                # Orchestrator v2: Repeat-/Budget-Guard
                # -------------------------------------------------

                delegate_attempts = self.hooks.orchestrator_delegate_attempts(
                    observations,
                    delegate_name,
                )

                if delegate_attempts >= 3:
                    observations.append({
                        "step": step,
                        "action": "delegate_guard",
                        "status": "rejected",
                        "agent": delegate_name,
                        "goal": delegate_goal,
                        "reason": (
                            "Maximale Anzahl sinnvoller Delegationen an "
                            f"{delegate_name} erreicht. "
                            "Wähle eine alternative Strategie oder schließe "
                            "mit den vorhandenen Einschränkungen ab."
                        ),
                    })

                    publish("running", observations[-1])
                    continue

                if self.hooks.orchestrator_duplicate_delegation(
                    observations,
                    delegate_name,
                    delegate_goal,
                ):
                    observations.append({
                        "step": step,
                        "action": "delegate_guard",
                        "status": "rejected",
                        "agent": delegate_name,
                        "goal": delegate_goal,
                        "reason": (
                            "Diese Delegation wurde bereits mit praktisch "
                            "demselben Teilziel ausgeführt. "
                            "Formuliere eine andere Verifikationsstrategie "
                            "oder verwende einen anderen Spezialagenten."
                        ),
                    })

                    publish("running", observations[-1])
                    continue

                # Guard against excessively large or abusive delegation goals.
                delegate_goal = delegate_goal[:4000]

                # coding_analysis receives a dedicated read-only assignment.
                # It uses research mode internally, whose tool permissions are
                # also read-only.
                if delegate_name == "coding_analysis":
                    delegate_mode = "research"
                    effective_goal = (
                        "Analysiere ausschließlich den aktiven lokalen "
                        "Code-Workspace. Verwende code_files, code_search und "
                        "code_read. Verwende keine Webrecherche, sofern sie für "
                        "dieses Teilziel nicht ausdrücklich erforderlich ist. "
                        "Verändere keine Dateien und bereite keine Änderungen "
                        "oder Patches vor.\n\nTeilziel:\n"
                        + delegate_goal
                    )
                else:
                    delegate_mode = delegate_modes[delegate_name]
                    if delegate_name == "research":
                        parent_constraints = str(goal or "").strip()[:4000]
                        effective_goal = (
                            delegate_goal
                            + "\n\nÜbergeordnete Anforderungen des Nutzers, "
                            "die bei diesem Teilziel erhalten bleiben müssen:\n"
                            + parent_constraints
                        )
                    else:
                        effective_goal = delegate_goal

                publish("running", {
                    "step": step,
                    "action": "delegate_agent",
                    "status": "running",
                    "agent": delegate_name,
                    "goal": delegate_goal,
                    "reason": delegate_reason,
                })

                try:
                    sub_result = self.run(
                        effective_goal,
                        observations=None,
                        start_step=1,
                        mode=delegate_mode,
                        conversation_context=conversation_context,

                        # No progress_callback:
                        # return subagent steps to the orchestrator as a compact
                        # result first.
                        allow_approval=False,
                        progress_callback=None,
                    )

                    self._check_cancelled()

                    sub_report = self.hooks.build_subagent_report(
                        delegate_name,
                        effective_goal,
                        sub_result,
                    )

                    sub_quality = self.hooks.assess_subagent_report(
                        delegate_name,
                        effective_goal,
                        sub_report,
                    )

                    observations.append({
                        "step": step,
                        "action": "delegate_agent",
                        "status": "completed",
                        "agent": delegate_name,
                        "goal": delegate_goal,
                        "reason": delegate_reason,
                        "result": {
                            "status": sub_result.get("status"),
                            "answer": sub_result.get("answer"),
                            "steps": self.hooks.compact_agent_observations(
                                sub_result.get("steps") or []
                            ),
                            "report": sub_report,
                            "quality": sub_quality,
                        },
                    })

                except _RunCancelled:
                    raise

                except Exception as exc:
                    observations.append({
                        "step": step,
                        "action": "delegate_agent",
                        "status": "failed",
                        "agent": delegate_name,
                        "goal": delegate_goal,
                        "reason": delegate_reason,
                        "error": str(exc),
                    })

                publish("running", observations[-1])
                continue

            if not action:
                observations.append({
                    "step": step,
                    "action": "planner_invalid_action",
                    "status": "rejected",
                    "reason": (
                        "Planner hat keine gültige action geliefert. "
                        "Wähle ein verfügbares Tool oder final."
                    ),
                })
                publish("running", observations[-1])
                continue

            if action not in self._allowed_tools(mode):
                observations.append({
                    "step": step,
                    "action": action,
                    "status": "rejected",
                    "reason": (
                        "Tool ist nicht freigegeben"
                    ),
                })
                publish()
                continue

            reason = str(
                decision.get("reason", "")
            ).strip()

            query = str(
                decision.get("query", "")
            ).strip()

            instruction = str(
                decision.get("instruction", "")
            ).strip()

            files = decision.get("files")

            tool_options = decision.get("options")
            if not isinstance(tool_options, dict):
                tool_options = {}
            else:
                tool_options = dict(tool_options)
            if self.context.resources_bound:
                if action in {"vision_analyze", "image_edit"} and not (
                    tool_options.get("artifact_id") or tool_options.get("upload_path")
                ):
                    if len(self.context.upload_paths) == 1:
                        tool_options["upload_path"] = str(self.context.upload_paths[0])
                    elif len(self.context.artifact_ids) == 1:
                        tool_options["artifact_id"] = self.context.artifact_ids[0]
                if action in {"document_search", "document_page"} and not tool_options.get("document_id"):
                    if len(self.context.document_ids) == 1:
                        tool_options["document_id"] = self.context.document_ids[0]

            # -------------------------------------------------
            # Research search-loop guard
            # -------------------------------------------------
            # Research should not consume its entire step budget on new search
            # variations when concrete results already exist. After three web
            # searches, block another search. The planner must then verify existing
            # results with fetch_url or finish with a transparent limitation.
            if (
                mode == "research"
                and action in {"web_search", "search_web"}
            ):
                completed_searches = [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("action") in {"web_search", "search_web"}
                ]

                successful_fetches = [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("action") == "fetch_url"
                    and isinstance(item.get("result"), dict)
                    and item.get("result", {}).get("ok") is True
                ]

                if len(completed_searches) >= 3 and not successful_fetches:
                    candidate_urls = []

                    for search_item in reversed(completed_searches):
                        search_result = search_item.get("result")
                        if not isinstance(search_result, dict):
                            continue

                        for result_item in search_result.get("results") or []:
                            if not isinstance(result_item, dict):
                                continue

                            url = str(result_item.get("url") or "").strip()
                            if (
                                url
                                and re.match(
                                    r"^https?://",
                                    url,
                                    flags=re.IGNORECASE,
                                )
                                and url not in candidate_urls
                            ):
                                candidate_urls.append(url)

                            if len(candidate_urls) >= 5:
                                break

                        if len(candidate_urls) >= 5:
                            break

                    observations.append({
                        "step": step,
                        "action": "research_search_loop_guard",
                        "status": "rejected",
                        "reason": (
                            "Bereits drei Websuchen ohne erfolgreich geladene "
                            "Quelle ausgeführt. Führe keine weitere Suchvariation "
                            "aus. Lade stattdessen einen vorhandenen Treffer mit "
                            "fetch_url oder schließe transparent ab, falls keine "
                            "brauchbare Quelle vorhanden ist."
                        ),
                        "candidate_urls": candidate_urls,
                    })

                    publish(
                        "running",
                        observations[-1],
                    )

                    continue

            # -------------------------------------------------
            # Orchestrator query hardening
            # -------------------------------------------------
            if (
                mode == "orchestrator"
                and action in {"web_search", "search_web"}
                and self.hooks.degraded_empty_web_search_count(observations) >= 3
            ):
                observations.append({
                    "step": step,
                    "action": "web_search_circuit_breaker",
                    "status": "rejected",
                    "reason": (
                        "Drei degradierte Websuchen ohne Treffer wurden bereits "
                        "ausgeführt. Weitere identische Websuchen sind aktuell "
                        "nicht sinnvoll. Nutze eine deterministisch ableitbare "
                        "Primärquelle, einen anderen READ-only Belegpfad oder "
                        "schließe mit transparenter Einschränkung ab."
                    ),
                })

                publish(
                    "running",
                    observations[-1],
                )
                continue

            if mode == "orchestrator":

                if action in {"web_search", "search_web"}:
                    original_query = query

                    query = self.hooks.sanitize_orchestrator_web_query(
                        goal,
                        query,
                    )

                    sanitized_query = query

                    query = self.hooks.boost_orchestrator_research_query(
                        goal,
                        query,
                    )

                    if original_query != sanitized_query:
                        observations.append({
                            "step": step,
                            "action": "query_sanitizer",
                            "status": "completed",
                            "reason": (
                                "Veraltete Jahreszahlen aus einer "
                                "Aktualitäts-Websuche entfernt"
                            ),
                            "original_query": original_query,
                            "query": sanitized_query,
                        })

                    if sanitized_query != query:
                        observations.append({
                            "step": step,
                            "action": "primary_source_booster",
                            "status": "completed",
                            "reason": (
                                "Technische Recherche auf offizielle "
                                "Dokumentation und Repository-Quellen fokussiert"
                            ),
                            "original_query": sanitized_query,
                            "query": query,
                        })

                if action == "fetch_url":

                    if not re.match(
                        r"^https?://",
                        query or "",
                        flags=re.IGNORECASE,
                    ):
                        observations.append({
                            "step": step,
                            "action": "fetch_url_guard",
                            "status": "rejected",
                            "reason": (
                                "fetch_url benötigt eine konkrete HTTP(S)-URL. "
                                "Eine Suchphrase ist keine URL. Nutze zuerst "
                                "web_search/search_web und danach eine URL "
                                "aus den Suchergebnissen."
                            ),
                            "blocked_query": query or None,
                        })

                        publish(
                            "running",
                            observations[-1],
                        )

                        continue

            # -------------------------------------------------
            # Research / Orchestrator Fetch-URL-Allowlist
            # -------------------------------------------------
            if mode in {"orchestrator", "research"} and action == "fetch_url":

                def normalize_fetch_url(value):
                    value = str(value or "").strip()

                    if not value:
                        return ""

                    try:
                        parts = urlsplit(value)
                    except Exception:
                        return value.rstrip("/")

                    # The fragment does not affect source identity.
                    return urlunsplit((
                        parts.scheme.lower(),
                        parts.netloc.lower(),
                        parts.path.rstrip("/") or "/",
                        parts.query,
                        "",
                    ))

                allowed_urls = set()

                for item in observations:
                    if not isinstance(item, dict):
                        continue

                    if item.get("status") != "completed":
                        continue

                    if item.get("action") not in {
                        "web_search",
                        "search_web",
                    }:
                        continue

                    search_result = item.get("result")

                    if not isinstance(search_result, dict):
                        continue

                    results = search_result.get("results")

                    if not isinstance(results, list):
                        continue

                    for search_item in results:
                        if not isinstance(search_item, dict):
                            continue

                        result_url = search_item.get("url")

                        if result_url:
                            allowed_urls.add(
                                normalize_fetch_url(result_url)
                            )

                canonical_repo = self.hooks.canonical_github_repo_from_goal(goal)

                if canonical_repo:
                    canonical_url = normalize_fetch_url(
                        canonical_repo.get("url")
                    )

                    if canonical_url:
                        allowed_urls.add(canonical_url)

                requested_url = normalize_fetch_url(query)

                def fetch_url_is_allowed(requested, allowed):
                    """
                    Allow exact discovered URLs and genuine subpaths.
                    The host and scheme must remain identical.
                    """
                    if requested == allowed:
                        return True

                    try:
                        requested_parts = urlsplit(requested)
                        allowed_parts = urlsplit(allowed)
                    except Exception:
                        return False

                    if (
                        requested_parts.scheme.lower()
                        != allowed_parts.scheme.lower()
                    ):
                        return False

                    if (
                        requested_parts.netloc.lower()
                        != allowed_parts.netloc.lower()
                    ):
                        return False

                    requested_path = (
                        requested_parts.path.rstrip("/") or "/"
                    )
                    allowed_path = (
                        allowed_parts.path.rstrip("/") or "/"
                    )

                    # A domain-root match does not automatically
                    # allow the entire domain.
                    if allowed_path == "/":
                        return False

                    return requested_path.startswith(
                        allowed_path + "/"
                    )

                matching_allowed_url = next(
                    (
                        allowed_url
                        for allowed_url in allowed_urls
                        if fetch_url_is_allowed(
                            requested_url,
                            allowed_url,
                        )
                    ),
                    None,
                )

                if matching_allowed_url is None:
                    observations.append({
                        "step": step,
                        "action": "fetch_url_allowlist_guard",
                        "status": "rejected",
                        "reason": (
                            "fetch_url darf in Research/Orchestrator nur eine zuvor "
                            "gefundene URL oder einen echten Unterpfad dieser "
                            "Quelle öffnen. Andere Hosts oder benachbarte "
                            "Repository-/Pfadbereiche bleiben gesperrt."
                        ),
                        "blocked_query": query or None,
                        "allowed_url_count": len(allowed_urls),
                    })
                    publish(
                        "running",
                        observations[-1],
                    )
                    continue

                successful_fetches = sum(
                    1
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("action") == "fetch_url"
                )

                if successful_fetches >= 3:
                    observations.append({
                        "step": step,
                        "action": "fetch_url_limit_guard",
                        "status": "rejected",
                        "reason": (
                            "Bereits drei Web-Quellen erfolgreich geladen. "
                            "Nutze die vorhandenen Quellen zur Synthese oder "
                            "führe nur bei fehlender Evidence eine neue Suche aus."
                        ),
                        "blocked_query": query or None,
                    })

                    publish(
                        "running",
                        observations[-1],
                    )

                    continue

            # -------------------------------------------------
            # Deterministic code_search -> code_read targeting
            # -------------------------------------------------
            # If the model requests only the bare file path after a successful
            # code_search, use an exact result from the latest matching search
            # as the line anchor.
            #
            # This turns:
            #   code_search -> agent/app.py:6325
            #   code_read   -> agent/app.py
            #
            # into a targeted read around the match instead of starting at line 1
            # and then paginating sequentially.
            if action == "code_read" and query:
                requested_query = str(query).strip()

                if not re.search(r":\d+(?:-\d+)?$", requested_query):
                    anchored_line = None

                    for item in reversed(observations):
                        if not isinstance(item, dict):
                            continue
                        if item.get("status") != "completed":
                            continue
                        if item.get("action") != "code_search":
                            continue

                        result = item.get("result")
                        if not isinstance(result, dict):
                            continue

                        results = result.get("results")
                        if not isinstance(results, list):
                            continue

                        matching_hits = [
                            hit
                            for hit in results
                            if isinstance(hit, dict)
                            and str(hit.get("path") or "").strip() == requested_query
                            and str(hit.get("match") or "").strip()
                            in {"exact", "symbol"}
                        ]

                        definition_hits = [
                            hit
                            for hit in matching_hits
                            if re.match(
                                r"^(?:async\s+)?(?:def|class)\s+",
                                str(hit.get("snippet") or "").strip(),
                            )
                        ]

                        candidate_hits = definition_hits or matching_hits

                        for hit in candidate_hits:
                            try:
                                line = int(hit.get("line"))
                            except (TypeError, ValueError):
                                continue

                            if line > 0:
                                anchored_line = line
                                break

                        if anchored_line is not None:
                            break

                    if anchored_line is not None:
                        anchor_start = max(1, anchored_line - 60)
                        anchor_end = anchored_line + 120
                        query = (
                            f"{requested_query}:"
                            f"{anchor_start}-{anchor_end}"
                        )

                        observations.append({
                            "step": step,
                            "action": "code_read_search_anchor",
                            "status": "completed",
                            "reason": (
                                "Nackter code_read wurde automatisch auf einen "
                                "exakten Treffer aus der vorherigen code_search "
                                "zentriert."
                            ),
                            "original_query": requested_query,
                            "anchor_line": anchored_line,
                            "query": query,
                        })

                        publish(
                            "running",
                            observations[-1],
                        )

            # -------------------------------------------------
            # Deterministic code_read pagination
            # -------------------------------------------------
            # Local models sometimes omit a new line range when continuing and
            # request the same bare file path again.
            #
            # If that exact path was already read successfully, continue after
            # the most recently read range automatically. This keeps progressive
            # reading reliable even when the model ignores the prompt rule.
            if action == "code_read" and query:
                requested_query = str(query).strip()

                if not re.search(r":\d+(?:-\d+)?$", requested_query):
                    previous_reads = [
                        item
                        for item in observations
                        if isinstance(item, dict)
                        and item.get("status") == "completed"
                        and item.get("action") == "code_read"
                        and isinstance(item.get("result"), dict)
                        and str(
                            item.get("result", {}).get("path") or ""
                        ).strip() == requested_query
                    ]

                    if previous_reads:
                        last_read = previous_reads[-1]
                        last_result = last_read.get("result") or {}

                        try:
                            last_end = int(last_result.get("end_line"))
                        except (TypeError, ValueError):
                            last_end = 0

                        last_content = str(
                            last_result.get("content") or ""
                        )
                        returned_lines = (
                            len(last_content.splitlines())
                            if last_content
                            else 0
                        )

                        # A default code_read may already contain the complete
                        # source file. Do not paginate a completed read.
                        read_complete = (
                            returned_lines > 0
                            and returned_lines
                            < code_workspaces.CODE_READ_DEFAULT_MAX_LINES
                        )

                        if last_end > 0 and not read_complete:
                            next_start = last_end + 1
                            next_end = (
                                next_start
                                + code_workspaces.CODE_READ_RANGE_MAX_LINES
                                - 1
                            )
                            query = (
                                f"{requested_query}:"
                                f"{next_start}-{next_end}"
                            )

                            observations.append({
                                "step": step,
                                "action": "code_read_pagination",
                                "status": "completed",
                                "reason": (
                                    "Identischer code_read ohne Zeilenbereich "
                                    "wurde automatisch auf den nächsten "
                                    "Dateibereich fortgesetzt."
                                ),
                                "original_query": requested_query,
                                "query": query,
                            })

                            publish(
                                "running",
                                observations[-1],
                            )

            # -------------------------------------------------
            # Repeat and loop guard for agent tool calls
            # -------------------------------------------------
            # Coding agents need the same protection as the general
            # orchestrator. Otherwise a model can repeatedly request
            # an already completed code_read and waste inference time.
            if mode in {"orchestrator", "coding"}:

                completed_tool_calls = [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                ]

            # 1. Do not repeat an identical action and query.
            # Deliberately exclude instruction from the signature because query
            # is the actual target reference for read tools.
                same_call_count = sum(
                    1
                    for item in completed_tool_calls
                    if str(item.get("action") or "").strip() == action
                    and str(item.get("query") or "").strip() == query
                    and (
                        action not in {
                            "disk_usage", "git_stage", "git_commit", "git_diff",
                            "document_search", "document_page", "vision_analyze",
                            "image_edit", "file_analyze",
                        }
                        or item.get("options") == (tool_options or None)
                    )
                    and (
                        action not in {"web_search", "search_web"}
                        or (
                            isinstance(item.get("result"), dict)
                            and bool(
                                item.get("result", {}).get("results")
                            )
                        )
                    )
                )

                if same_call_count >= 1 and action not in {
                    "image_job_status", "file_analysis_status",
                }:
                    observations.append({
                        "step": step,
                        "action": "repeat_guard",
                        "status": "rejected",
                        "reason": (
                            "Identischer Tool-Aufruf wurde bereits erfolgreich "
                            f"ausgeführt: {action} / {query or '<ohne query>'}. "
                            "Nutze einen anderen Suchbegriff, einen anderen "
                            "Zeilenbereich, fetch_url oder schließe die Analyse ab."
                        ),
                        "blocked_action": action,
                        "blocked_query": query or None,
                    })
                    publish("running", observations[-1])
                    continue

            # 2. Limit web searches.
            # After three successful searches, inspect results more deeply or
            # synthesize them instead of consuming more similar search runs.
                if action in {"web_search", "search_web"}:
                    web_search_count = sum(
                        1
                        for item in completed_tool_calls
                        if item.get("action") in {
                            "web_search",
                            "search_web",
                        }
                        and isinstance(item.get("result"), dict)
                        and bool(
                            item.get("result", {}).get("results")
                        )
                    )

                    if web_search_count >= 3:
                        observations.append({
                            "step": step,
                            "action": "web_search_guard",
                            "status": "rejected",
                            "reason": (
                                "Bereits drei Web-Suchen erfolgreich ausgeführt. "
                                "Nutze jetzt fetch_url für relevante Treffer "
                                "oder synthetisiere die vorhandenen Ergebnisse."
                            ),
                            "blocked_action": action,
                            "blocked_query": query or None,
                        })
                        publish("running", observations[-1])
                        continue

            publish("running", {
                "step": step,
                "action": action,
                "reason": reason,
                "plan": plan,
                "query": query or None,
                "options": tool_options or None,
                "status": "running",
            })

            try:
                result = (prefetched_read if prefetched_read is not None
                          and action == "code_read" and query == explicit_file
                          else self._execute_tool(
                              action, goal, query=query or None,
                              instruction=instruction or None,
                              files=files, options=tool_options,
                          ))

                observations.append({
                    "step": step,
                    "action": action,
                    "reason": reason,
                    "plan": plan,
                    "query": query or None,
                    "options": tool_options or None,
                    "instruction": instruction or None,
                    "status": "completed",
                    "result": result,
                })
                self._check_cancelled()
                publish()

            except _RunCancelled:
                raise

            except ToolPermissionError as exc:
                self._check_cancelled()
                observation = {
                    "step": step, "action": action, "reason": reason,
                    "query": query or None, "status": "failed",
                    "error": str(exc), "permission_decision": exc.decision.as_dict(),
                }
                observations.append(observation)
                if exc.decision.decision == Decision.CONFIRM and allow_approval:
                    try:
                        approval = self.hooks.create_agent_approval(
                            goal=goal, observations=observations, step=step, mode=mode,
                            operation=action, target=query,
                            reason=exc.decision.reason,
                            conversation_context=conversation_context,
                            runtime=self, progress_callback=progress_callback,
                            tool_request={"goal": goal, "query": query or None,
                                          "instruction": instruction or None, "files": files,
                                          "options": tool_options},
                        )
                    except _RunCancelled:
                        raise
                    except Exception as approval_error:
                        observation["approval_error"] = str(approval_error)
                    else:
                        self._check_cancelled()
                        publish("approval_required", pending_action=approval)
                        return {"status": "approval_required", "goal": goal,
                                "steps": observations, "pending_action": approval}
                publish()

            except Exception as exc:
                observations.append({
                    "step": step,
                    "action": action,
                    "reason": reason,
                    "plan": plan,
                    "query": query or None,
                    "options": tool_options or None,
                    "status": "failed",
                    "error": str(exc),
                })
                publish()

        final_status = "max_steps"

        if mode == "orchestrator":
            missing = self.hooks.orchestrator_missing_evidence(
                goal,
                observations,
            )

            if not missing:
                # All evidence types required for the goal are available.
                # At the step limit, the agent may therefore synthesize and
                # finish cleanly.
                final_status = "completed"

            else:
                observations.append({
                    "step": max_steps,
                    "action": "evidence_gate",
                    "status": "rejected",
                    "reason": (
                        "Schrittbudget erreicht; "
                        "erforderliche Evidence fehlt: "
                        + ", ".join(missing)
                    ),
                })

        result = {
            "status": final_status,
            "goal": goal,
            "steps": observations,
            "answer": self._model_hook(self.hooks.agent_v2_final_answer,
                goal,
                observations,
            ),
        }

        publish(final_status)

        return result
