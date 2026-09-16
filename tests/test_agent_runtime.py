from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agent import code_workspaces, run_state
from agent.model_provider import ModelRequest, ModelResponse, ProviderError
from agent.permissions import PermissionEngine
from agent.runtime import AgentRuntime, RuntimeHooks, RuntimePolicy, current_runtime
from agent.tool_registry import Tool, ToolRegistry


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, request, *, run_context=None):
        self.calls.append((request, run_context))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return ModelResponse(json.dumps(reply) if isinstance(reply, dict) else reply,
                             "fake-local", request.role, {})


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.context = run_state.RunContext("runtime-test-run", "chat-one", None, None, ())
        self.registry = ToolRegistry(permission_engine=PermissionEngine())
        self.handler = mock.Mock(return_value={"value": "evidence"})
        self.add_tool("inspect", self.handler)
        self.approval = mock.Mock(return_value={"approval_id": "existing-approval"})
        self.events = []
        self.planner_limits = []

        def model_text(goal, observations):
            request = ModelRequest([{"role": "user", "content": json.dumps({"goal": goal, "observations": observations})}])
            return current_runtime().complete_model(request).text

        def plan(goal, observations, **kwargs):
            self.planner_limits.append(kwargs["max_steps"])
            return json.loads(model_text(goal, observations))

        self.hooks = RuntimeHooks(
            coding_read_only_fast_final_requested=lambda goal: False,
            ambiguous_delete_reference=lambda goal, context: False,
            agent_choose_next_step_v2=plan,
            agent_coding_read_only_final_answer=model_text,
            agent_v2_final_answer=model_text,
            orchestrator_missing_evidence=lambda goal, observations: [],
            orchestrator_unresolved_subagent_quality=lambda observations: [],
            orchestrator_delegate_attempts=lambda observations, name: sum(item.get("agent") == name for item in observations),
            orchestrator_duplicate_delegation=lambda *args: False,
            create_agent_approval=self.approval,
            build_subagent_report=lambda name, goal, result: {"answer": result["answer"]},
            assess_subagent_report=lambda *args: {"evidence_sufficient": True},
            compact_agent_observations=lambda observations: observations,
            sanitize_orchestrator_web_query=lambda goal, query: query,
            boost_orchestrator_research_query=lambda goal, query: query,
            degraded_empty_web_search_count=lambda observations: 0,
            canonical_github_repo_from_goal=lambda goal: None,
        )

    def add_tool(self, name, handler, risks=()):
        self.registry.register(Tool(name, "Test tool", {"type": "object"}, handler, "READ", risks))

    def runtime(self, replies, **kwargs):
        self.provider = FakeProvider(replies)
        return AgentRuntime(self.context, self.provider, self.registry, self.hooks, **kwargs)

    def progress(self, status, observations, current_step, pending_action):
        self.events.append((status, list(observations), current_step, pending_action))

    def test_final_response_without_tools(self):
        runtime = self.runtime([{"action": "final", "answer": "Done"}])
        result = runtime.run("Inspect", progress_callback=self.progress)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "Done")
        self.assertEqual(result["steps"], [])
        self.handler.assert_not_called()
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.events[-1][0], "completed")
        self.assertIsNone(current_runtime())
        self.assertIsNone(run_state.current_run_context())

    def test_tool_uses_registry_permission_gate_and_returns_evidence_to_provider(self):
        runtime = self.runtime([{"action": "inspect", "query": "target"}, {"action": "final", "answer": "Done"}])
        with (
            mock.patch.object(self.registry, "execute", wraps=self.registry.execute) as execute,
            mock.patch.object(self.registry.permission_engine, "evaluate", wraps=self.registry.permission_engine.evaluate) as evaluate,
        ):
            result = runtime.run("Inspect")
        execute.assert_called_once()
        evaluate.assert_called_once()
        self.handler.assert_called_once()
        self.assertEqual(result["steps"][0]["result"], {"value": "evidence"})
        self.assertIn("evidence", self.provider.calls[1][0].messages[0]["content"])

    def test_multiple_tools_in_sequence(self):
        second = mock.Mock(return_value={"second": True})
        self.add_tool("check", second)
        result = self.runtime([{"action": "inspect"}, {"action": "check"}, {"action": "final", "answer": "Done"}]).run("Inspect")
        self.assertEqual([step["action"] for step in result["steps"]], ["inspect", "check"])
        self.assertEqual(len(self.provider.calls), 3)
        second.assert_called_once()

    def test_tool_error_is_returned_to_model_and_run_can_recover(self):
        self.handler.side_effect = [ValueError("file missing"), {"found": True}]
        result = self.runtime([{"action": "inspect"}, {"action": "inspect", "query": "alternative"}, {"action": "final", "answer": "Recovered"}]).run("Inspect")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([step["status"] for step in result["steps"]], ["failed", "completed"])
        self.assertIn("file missing", self.provider.calls[1][0].messages[0]["content"])

    def test_permission_deny_prevents_execution_and_is_structured(self):
        blocked = mock.Mock()
        self.add_tool("blocked", blocked, ("PRIVILEGED",))
        result = self.runtime([{"action": "blocked"}, {"action": "final", "answer": "Blocked"}]).run("Inspect")
        blocked.assert_not_called()
        self.assertEqual(result["steps"][0]["permission_decision"]["decision"], "DENY")
        self.assertIn("PRIVILEGED_ACTION_BLOCKED", self.provider.calls[1][0].messages[0]["content"])

    def test_confirm_calls_existing_approval_boundary_without_execution(self):
        guarded = mock.Mock()
        self.add_tool("guarded", guarded, ("DELETE",))
        result = self.runtime([{"action": "guarded", "query": "target"}]).run("Inspect", progress_callback=self.progress)
        guarded.assert_not_called()
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["pending_action"], self.approval.return_value)
        self.approval.assert_called_once()
        self.assertEqual(self.approval.call_args.kwargs["operation"], "guarded")
        self.assertEqual(self.events[-1][0], "approval_required")

    def test_unsupported_confirmation_is_not_executed(self):
        guarded = mock.Mock()
        self.add_tool("guarded", guarded, ("DELETE",))
        self.approval.side_effect = ValueError("unsupported approval operation")
        result = self.runtime([{"action": "guarded"}, {"action": "final", "answer": "Cannot execute"}]).run("Inspect")
        guarded.assert_not_called()
        self.assertEqual(result["steps"][0]["approval_error"], "unsupported approval operation")

    def test_confirmation_is_blocked_for_delegated_read_only_work(self):
        self.add_tool("guarded", mock.Mock(), ("DELETE",))
        result = self.runtime([{"action": "guarded"}, {"action": "final", "answer": "Read only"}]).run("Inspect", allow_approval=False)
        self.approval.assert_not_called()
        self.assertEqual(result["status"], "completed")

    def test_existing_explicit_approval_action_is_preserved(self):
        result = self.runtime([{"action": "request_approval", "operation": "docker_restart", "target": "service"}]).run("Inspect")
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(self.approval.call_args.kwargs["operation"], "docker_restart")

    def test_provider_failure_is_structured_and_keeps_previous_steps(self):
        result = self.runtime([{"action": "inspect"}, ProviderError("timeout", "timed out")]).run("Inspect", progress_callback=self.progress)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], {"code": "timeout", "detail": "timed out"})
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(self.events[-1][0], "failed")
        self.assertIsNone(current_runtime())

    def test_step_limit_still_synthesizes_existing_observations(self):
        runtime = self.runtime([{"action": "inspect"}, {"action": "inspect"}, "Summary"], policy=RuntimePolicy(diagnostic_steps=2))
        result = runtime.run("Inspect")
        self.assertEqual(result["status"], "max_steps")
        self.assertEqual(result["answer"], "Summary")
        self.assertEqual(self.handler.call_count, 2)
        self.assertEqual(self.planner_limits, [2, 2])

    def test_coding_repeat_guard_preserves_default_step_budget(self):
        runtime = self.runtime([{"action": "inspect", "query": "same"}, {"action": "inspect", "query": "same"}, {"action": "final"}, "Summary"])
        result = runtime.run("Inspect", mode="coding")
        self.handler.assert_called_once()
        self.assertEqual(result["steps"][1]["action"], "repeat_guard")
        self.assertEqual(self.planner_limits, [24, 24, 24])

    def test_research_search_limit_is_preserved(self):
        search = mock.Mock(return_value={"results": [{"url": "https://example.org/docs"}]})
        self.add_tool("search_web", search)
        replies = [{"action": "search_web", "query": str(i)} for i in range(4)] + [{"action": "final"}, "Summary"]
        result = self.runtime(replies).run("Inspect", mode="research")
        self.assertEqual(search.call_count, 3)
        self.assertEqual(result["steps"][-1]["action"], "research_search_loop_guard")
        self.assertEqual(set(self.planner_limits), {6})

    def test_research_continuation_budget_only_continues_loaded_sources(self):
        fetch = mock.Mock(return_value={"ok": True, "truncated": True, "next_offset": 100})
        self.add_tool("fetch_url", fetch)
        source = "https://example.org/docs"
        observations = [{"action": "search_web", "status": "completed", "result": {"results": [{"url": source}]}}]
        runtime = self.runtime([{"action": "fetch_url", "query": source}, {"action": "fetch_url", "query": source}, "Summary"], policy=RuntimePolicy(research_steps=1, research_continuation_steps=1))
        result = runtime.run("Inspect", observations=observations, mode="research")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["status"], "max_steps")
        self.assertEqual(len(observations), 1)

    def test_cancel_before_run_does_not_call_provider_or_tools(self):
        self.context.cancel()
        result = self.runtime([]).run("Inspect", progress_callback=self.progress)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.provider.calls, [])
        self.handler.assert_not_called()
        self.assertEqual(self.events[-1][0], "cancelled")

    def test_cancel_before_model_operation(self):
        def progress(status, observations, step, pending):
            if step and step["action"] == "agent_plan":
                self.context.cancel()
        result = self.runtime([]).run("Inspect", progress_callback=progress)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.provider.calls, [])

    def test_cancel_before_tool_operation(self):
        def progress(status, observations, step, pending):
            if step and step["action"] == "inspect":
                self.context.cancel()
        result = self.runtime([{"action": "inspect"}]).run("Inspect", progress_callback=progress)
        self.assertEqual(result["status"], "cancelled")
        self.handler.assert_not_called()

    def test_cancel_after_tool_keeps_result_without_another_step(self):
        def execute(**arguments):
            self.context.cancel()
            return {"finished": True}
        self.handler.side_effect = execute
        result = self.runtime([{"action": "inspect"}]).run("Inspect")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["steps"][0]["result"], {"finished": True})
        self.assertEqual(len(self.provider.calls), 1)

    def test_provider_cancellation_is_a_cancelled_run(self):
        result = self.runtime([ProviderError("cancelled", "Cancelled")]).run("Inspect")
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(self.context.cancelled)

    def test_delegation_keeps_context_provider_and_registry(self):
        runtime = self.runtime([
            {"action": "delegate_agent", "agent": "diagnostic", "goal": "Inspect child"},
            {"action": "inspect"}, {"action": "final", "answer": "Child answer"},
            {"action": "final"}, "Parent answer",
        ])
        result = runtime.run("Inspect", mode="orchestrator")
        self.assertEqual(result["answer"], "Parent answer")
        self.handler.assert_called_once()
        self.assertEqual(result["steps"][0]["result"]["answer"], "Child answer")
        self.assertTrue(all(context is self.context for request, context in self.provider.calls))
        self.assertIsNone(current_runtime())

    def test_delegation_still_disallows_explicit_approval(self):
        result = self.runtime([
            {"action": "delegate_agent", "agent": "diagnostic", "goal": "Inspect child"},
            {"action": "request_approval", "operation": "docker_restart", "target": "service"},
            {"action": "final", "answer": "Child answer"}, {"action": "final"}, "Parent answer",
        ]).run("Inspect", mode="orchestrator")
        self.approval.assert_not_called()
        self.assertEqual(result["steps"][0]["result"]["steps"][0]["action"], "approval_guard")

    def test_workspace_does_not_follow_global_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            first, second = base / "first", base / "second"
            first.mkdir()
            second.mkdir()
            (first / "file.txt").write_text("original")
            (second / "file.txt").write_text("other")
            with mock.patch.multiple(code_workspaces, ROOT=base, WORKSPACES=base / "workspaces.json"):
                code_workspaces.add_workspace(str(first))
                self.context = run_state.RunContext.start(chat_id="bound-chat")
                code_workspaces.add_workspace(str(second))
                self.add_tool("read_bound", lambda **kwargs: run_state.current_run_context().resolve_path(kwargs["query"]).read_text(), ("workspace",))
                result = self.runtime([{"action": "read_bound", "query": "file.txt"}, {"action": "final", "answer": "Done"}]).run("Inspect")
                self.assertEqual(result["steps"][0]["result"], "original")
                self.assertTrue(all(context is self.context for request, context in self.provider.calls))

    def test_runtime_rejects_registry_without_permission_engine(self):
        with self.assertRaises(ValueError):
            AgentRuntime(self.context, FakeProvider([]), ToolRegistry(), self.hooks)

    def test_policy_defaults_and_validation(self):
        policy = RuntimePolicy()
        self.assertEqual([policy.max_steps(mode) for mode in ("diagnostic", "research", "coding", "orchestrator", "other")], [6, 6, 24, 12, 6])
        for field, value in (("coding_steps", 0), ("research_steps", True), ("research_continuation_steps", -1)):
            with self.assertRaises(ValueError):
                replace(policy, **{field: value})


class RuntimeAPICompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        with mock.patch.object(Path, "home", return_value=Path(directory.name)):
            from agent import app
        cls.agent = app

    def setUp(self):
        from fastapi.testclient import TestClient
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        for patch in (
            mock.patch.multiple(code_workspaces, ROOT=self.base, WORKSPACES=self.base / "workspaces.json"),
            mock.patch.object(self.agent, "ACTIVE_AGENT_RUNS", {}),
            mock.patch.object(self.agent, "PENDING_AGENT_ACTIONS", {}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        code_workspaces.add_workspace(str(self.workspace))
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        self.addCleanup(self.client.close)
        self.run_id = "1234567890abcdef1234567890abcdef"

    def test_api_real_planner_uses_runtime_provider_and_existing_progress_contract(self):
        provider = FakeProvider([{"action": "final", "answer": "Done"}])
        with (
            mock.patch.object(self.agent, "agent_model_provider", return_value=provider),
            mock.patch.object(self.agent.urllib.request, "urlopen", side_effect=AssertionError("No real inference")),
        ):
            response = self.client.post("/api/agent/run", json={"goal": "Inspect", "run_id": self.run_id, "chat_id": "chat-one"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "Done")
        context = provider.calls[0][1]
        self.assertEqual(context.run_id, self.run_id)
        self.assertEqual(context.chat_id, "chat-one")
        self.assertEqual(context.workspace_root, self.workspace)
        progress = self.client.get("/api/agent/runs/" + self.run_id)
        self.assertEqual(progress.json()["status"], "completed")
        self.assertIsNone(current_runtime())

    def test_existing_approval_resume_keeps_original_run_after_workspace_switch(self):
        provider = FakeProvider([
            {"action": "request_approval", "operation": "docker_restart", "target": "service", "reason": "Restart"},
            {"action": "final", "answer": "Rejected by user"},
        ])
        with mock.patch.object(self.agent, "agent_model_provider", return_value=provider):
            response = self.client.post("/api/agent/run", json={"goal": "Inspect", "run_id": self.run_id})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["status"], "approval_required")
            other = self.base / "other"
            other.mkdir()
            code_workspaces.add_workspace(str(other))
            resumed = self.client.post("/api/agent/approve/" + result["pending_action"]["approval_id"], json={"approved": False})
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["status"], "completed")
        self.assertEqual(resumed.json()["steps"][0]["status"], "rejected_by_user")
        self.assertIs(provider.calls[0][1], provider.calls[1][1])
        self.assertEqual(provider.calls[1][1].workspace_root, self.workspace)

    def test_api_provider_error_returns_structured_failure(self):
        provider = FakeProvider([ProviderError("unavailable", "Local model offline")])
        with mock.patch.object(self.agent, "agent_model_provider", return_value=provider):
            response = self.client.post("/api/agent/run", json={"goal": "Inspect", "run_id": self.run_id})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(response.json()["error"]["code"], "unavailable")
        self.assertEqual(self.client.get("/api/agent/runs/" + self.run_id).json()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
