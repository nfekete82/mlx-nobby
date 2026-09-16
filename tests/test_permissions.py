from dataclasses import FrozenInstanceError, replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import code_workspaces
from agent.permissions import Decision, PermissionEngine, PermissionPolicy, Risk, ToolPermissionError
from agent.run_state import RunContext, bind_run_context, current_run_context
from agent.tool_registry import Tool, ToolRegistry


class PermissionAndRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.import_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.import_directory.cleanup)
        with mock.patch.object(Path, "home", return_value=Path(cls.import_directory.name)):
            from agent import app
        cls.agent = app

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root_a = self.base / "a"
        self.root_b = self.base / "b"
        self.root_a.mkdir()
        self.root_b.mkdir()
        (self.root_a / "a.txt").write_text("first workspace")
        (self.root_b / "b.txt").write_text("second workspace")
        config = self.base / "config"
        patch = mock.patch.multiple(
            code_workspaces, ROOT=config, WORKSPACES=config / "workspaces.json",
            PATCHES=config / "patches", SNAPSHOTS=config / "snapshots",
            TESTS=config / "tests", AUDIT=config / "audit.jsonl",
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.b = code_workspaces.add_workspace(str(self.root_b))
        self.a = code_workspaces.add_workspace(str(self.root_a))
        self.context = RunContext.start(chat_id="chat-one")
        self.engine = PermissionEngine()
        self.handler = mock.Mock(return_value={"ok": True})
        self.tool = Tool(
            name="read_file", description="Read a workspace file.",
            parameters={"type": "object"}, execute=self.handler,
            permission="READ", risks=("workspace",),
        )
        pending_patch = mock.patch.object(self.agent, "PENDING_AGENT_ACTIONS", {})
        pending_patch.start()
        self.addCleanup(pending_patch.stop)

    def decide(self, tool=None, **arguments):
        return self.engine.evaluate(tool or self.tool, self.context, arguments)

    def registry(self, tool=None):
        registry = ToolRegistry(permission_engine=self.engine)
        registry.register(tool or self.tool)
        return registry

    def test_read_inside_workspace_is_allowed(self):
        self.assertEqual(self.decide(path="a.txt").decision, Decision.ALLOW)
        self.assertEqual(self.decide(path=str(self.root_a / "a.txt")).decision, Decision.ALLOW)

    def test_traversal_and_absolute_escape_are_denied(self):
        for path in ("../b/b.txt", str(self.root_b / "b.txt"), "/etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.decide(path=path).decision, Decision.DENY)

    def test_symlink_escape_is_denied(self):
        (self.root_a / "link").symlink_to(self.root_b, target_is_directory=True)
        self.assertEqual(self.decide(path="link/b.txt").decision, Decision.DENY)

    def test_existing_secret_and_ignored_path_checks_remain(self):
        for path in (".env", ".git/config", "private.key"):
            with self.subTest(path=path):
                self.assertEqual(self.decide(path=path).decision, Decision.DENY)

    def test_delete_requires_confirmation_inside_but_not_outside(self):
        tool = replace(self.tool, permission="DELETE")
        self.assertEqual(self.decide(tool, path="a.txt").decision, Decision.CONFIRM)
        self.assertEqual(self.decide(tool, path="../b/b.txt").decision, Decision.DENY)

    def test_privileged_action_is_denied_and_execute_requires_confirmation(self):
        for tool in (
            replace(self.tool, permission="PRIVILEGED"),
            replace(self.tool, risks=("PRIVILEGED",)),
        ):
            self.assertEqual(self.decide(tool, path="a.txt").decision, Decision.DENY)
        self.assertEqual(self.decide(replace(self.tool, permission="EXECUTE")).decision, Decision.CONFIRM)
        self.assertEqual(self.decide(replace(self.tool, risks=("destructive",))).decision, Decision.CONFIRM)

    def test_unknown_permission_and_risk_metadata_fail_closed(self):
        for permission, risks in (("UNKNOWN", ()), (None, ()), ("READ", ("unknown",)), ("READ", ["workspace"]), ("PREPARE", ())):
            with self.subTest(permission=permission, risks=risks):
                result = self.engine.decide(permission, risks, self.context, {})
                self.assertEqual(result.decision, Decision.DENY)

    def test_risk_categories_are_extensible_strings(self):
        self.assertEqual({risk.value for risk in Risk}, {"READ", "WRITE", "CREATE", "DELETE", "EXECUTE", "EXTERNAL", "PRIVILEGED"})

    def test_write_and_create_preserve_confirmation_default(self):
        for permission in ("WRITE", "CREATE"):
            tool = replace(self.tool, permission=permission)
            self.assertEqual(self.decide(tool, path="new.txt").decision, Decision.CONFIRM)
            engine = PermissionEngine(PermissionPolicy(allow_workspace_writes=True))
            self.assertEqual(engine.evaluate(tool, self.context, {"path": "new.txt"}).decision, Decision.ALLOW)
            self.assertEqual(engine.evaluate(tool, self.context, {"path": "../new.txt"}).decision, Decision.DENY)
            self.assertEqual(engine.evaluate(tool, self.context, {}).decision, Decision.CONFIRM)

    def test_existing_web_and_read_execution_policy_is_preserved(self):
        for name in ("web_search", "search_web", "fetch_url", "shell_read", "process_usage"):
            tool = self.agent.AGENT_TOOL_REGISTRY.get(name)
            self.assertEqual(self.decide(tool).decision, Decision.ALLOW)
        self.assertEqual(self.decide(replace(self.tool, risks=("EXECUTE",))).decision, Decision.CONFIRM)

    def test_bound_workspace_is_immutable_after_global_switch(self):
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        self.assertEqual(self.context.workspace_id, self.a["workspace_id"])
        self.assertEqual(self.context.workspace_root, self.root_a)
        self.assertEqual(self.context.allowed_roots, (self.root_a,))
        self.assertEqual(self.context.resolve_path("a.txt"), self.root_a / "a.txt")
        with self.assertRaises(FrozenInstanceError):
            self.context.workspace_id = self.b["workspace_id"]

    def test_independent_runs_have_independent_binding_and_cancellation(self):
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        second = RunContext.start(chat_id="chat-two")
        self.assertNotEqual(self.context.run_id, second.run_id)
        self.assertEqual(second.workspace_id, self.b["workspace_id"])
        self.context.cancel()
        self.assertFalse(second.cancelled)
        self.assertEqual(second.chat_id, "chat-two")
        self.assertGreater(second.started_at, 0)

    def test_context_without_workspace_does_not_acquire_later_selection(self):
        code_workspaces.deactivate_workspace()
        context = RunContext.start()
        code_workspaces.set_active_workspace(self.a["workspace_id"])
        self.assertEqual(self.engine.evaluate(self.tool, context, {"path": "a.txt"}).decision, Decision.DENY)

    def test_retargeted_or_removed_workspace_is_denied(self):
        items = code_workspaces._load()
        next(item for item in items if item["workspace_id"] == self.a["workspace_id"])["root_path"] = str(self.root_b)
        code_workspaces._save(items)
        self.assertEqual(self.decide(path="b.txt").decision, Decision.DENY)
        code_workspaces.remove_workspace(self.a["workspace_id"])
        self.assertEqual(self.decide(path="b.txt").decision, Decision.DENY)

    def test_allowed_subtree_cannot_expand_workspace_boundary(self):
        subdir = self.root_a / "subdir"
        subdir.mkdir()
        context = replace(self.context, allowed_roots=(subdir,))
        self.assertEqual(context.resolve_path("subdir/new.txt"), subdir / "new.txt")
        with self.assertRaises(ValueError):
            context.resolve_path("a.txt")
        with self.assertRaises(ValueError):
            replace(self.context, allowed_roots=(self.root_b,))

    def test_context_binding_restores_outer_context_even_on_error(self):
        self.assertIsNone(current_run_context())
        with bind_run_context(self.context):
            with self.assertRaises(RuntimeError):
                with bind_run_context(RunContext.start()):
                    raise RuntimeError("handler failed")
            self.assertIs(current_run_context(), self.context)
        self.assertIsNone(current_run_context())

    def test_concurrent_runs_do_not_share_workspace_context(self):
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        second = RunContext.start()
        barrier = Barrier(2)

        def read(context, path):
            with bind_run_context(context):
                barrier.wait(timeout=5)
                return self.agent.AGENT_TOOL_REGISTRY.execute("code_read", goal="Read", query=path)["content"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(read, self.context, "a.txt")
            second_result = executor.submit(read, second, "b.txt")
            self.assertEqual(first_result.result(timeout=5), "first workspace")
            self.assertEqual(second_result.result(timeout=5), "second workspace")

    def test_whole_workspace_tools_cannot_expand_subtree_grant(self):
        subdir = self.root_a / "subdir"
        subdir.mkdir()
        context = replace(self.context, allowed_roots=(subdir,))
        for name in ("code_files", "code_search"):
            with self.subTest(name=name):
                with self.assertRaises(ToolPermissionError):
                    self.agent.AGENT_TOOL_REGISTRY.execute(name, run_context=context, goal="Inspect", query="first")

    def test_registry_allow_calls_handler_with_bound_context(self):
        self.handler.side_effect = lambda **kwargs: current_run_context()
        result = self.registry().execute("read_file", run_context=self.context, path="a.txt")
        self.assertIs(result, self.context)
        self.handler.assert_called_once_with(path="a.txt")
        self.assertIsNone(current_run_context())

    def test_registry_deny_prevents_execution(self):
        with self.assertRaises(ToolPermissionError) as caught:
            self.registry().execute("read_file", run_context=self.context, path="../b/b.txt")
        self.assertEqual(caught.exception.decision.decision, Decision.DENY)
        self.handler.assert_not_called()

    def test_registry_confirm_is_structured_and_does_not_execute(self):
        tool = replace(self.tool, permission="DELETE")
        with self.assertRaises(ToolPermissionError) as caught:
            self.registry(tool).execute("read_file", run_context=self.context, path="a.txt")
        self.assertEqual(caught.exception.decision.as_dict(), {"decision": "CONFIRM", "reason": "DELETE_REQUIRES_APPROVAL"})
        self.assertEqual(caught.exception.tool_name, "read_file")
        self.handler.assert_not_called()

    def test_cancelled_context_prevents_execution(self):
        self.context.cancel()
        with self.assertRaisesRegex(ToolPermissionError, "RUN_CANCELLED"):
            self.registry().execute("read_file", run_context=self.context, path="a.txt")
        self.handler.assert_not_called()

    def test_migrated_reads_searches_and_patch_preparation_use_bound_workspace(self):
        registry = self.agent.AGENT_TOOL_REGISTRY
        patch = registry.execute("code_patch", run_context=self.context, goal="Prepare", files=[{"path": "new.txt", "proposed_content": "new"}])
        self.assertEqual(code_workspaces.diff(patch["patch_id"])["workspace_id"], self.a["workspace_id"])
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        read = registry.execute("code_read", run_context=self.context, goal="Read", query="a.txt")
        self.assertEqual(read["content"], "first workspace")
        listing = registry.execute("code_files", run_context=self.context, goal="List")
        self.assertEqual([item["path"] for item in listing["files"]], ["a.txt"])
        with mock.patch.object(code_workspaces, "search", return_value={}) as search:
            registry.execute("code_search", run_context=self.context, goal="Search", query="first")
        search.assert_called_once_with(self.a["workspace_id"], "first")
        with self.assertRaisesRegex(ValueError, "WORKSPACE_CHANGED"):
            registry.execute("code_patch", run_context=self.context, goal="Prepare", files=[{"path": "other.txt", "proposed_content": "new"}])
        self.assertFalse((self.root_a / "new.txt").exists())
        self.assertFalse((self.root_b / "new.txt").exists())

    def test_cross_workspace_patch_and_invalid_patch_id_are_blocked(self):
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        patch = code_workspaces.create_patch(self.b["workspace_id"], "Prepare", [{"path": "new.txt", "proposed_content": "new"}])
        registry = self.agent.AGENT_TOOL_REGISTRY
        for tool in ("code_diff", "code_test"):
            for query in (patch["patch_id"], "../other"):
                with self.subTest(tool=tool, query=query):
                    with self.assertRaises(ToolPermissionError):
                        registry.execute(tool, run_context=self.context, goal="Inspect", query=query)

    def test_agent_run_binds_before_planner_changes_active_workspace(self):
        def choose(*args, **kwargs):
            code_workspaces.set_active_workspace(self.b["workspace_id"])
            if not args[1]:
                return {"action": "code_files"}
            return {"action": "final", "answer": "Done"}

        with (
            mock.patch.object(self.agent, "agent_choose_next_step_v2", side_effect=choose),
            mock.patch.object(self.agent, "agent_v2_final_answer", return_value="Done"),
        ):
            result = self.agent.run_agent_v2("List project files", mode="coding")
        listing = next(step["result"] for step in result["steps"] if step["action"] == "code_files")
        self.assertEqual([item["path"] for item in listing["files"]], ["a.txt"])
        self.assertIsNone(current_run_context())

    def approval(self):
        patch = code_workspaces.create_patch(self.a["workspace_id"], "Prepare", [{"path": "new.txt", "proposed_content": "new"}])
        patch_id = patch["patch_id"]
        observations = [
            {"action": "code_diff", "status": "completed", "query": patch_id, "result": code_workspaces.diff(patch_id)},
            {"action": "code_test", "status": "completed", "query": patch_id, "result": {"patch_id": patch_id, "passed": True, "test_status": "passed", "checks_run": 1}},
        ]
        with bind_run_context(self.context):
            return self.agent.create_agent_approval("Prepare", observations, 3, "coding", "code_apply", patch_id, "Apply tested patch")

    def test_existing_approval_boundary_carries_decision_and_run_context(self):
        approval = self.approval()
        self.assertEqual(approval["permission_decision"]["decision"], "CONFIRM")
        pending = self.agent.PENDING_AGENT_ACTIONS[approval["approval_id"]]
        self.assertIs(pending["run_context"], self.context)
        self.assertNotIn("run_context", approval)

    def test_approval_resume_uses_original_binding(self):
        approval = self.approval()
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        contexts = []
        def final(*args, **kwargs):
            contexts.append(current_run_context())
            return {"action": "final", "answer": "Rejected"}
        with (
            mock.patch.object(self.agent, "agent_choose_next_step_v2", side_effect=final) as resume,
            mock.patch.object(self.agent, "agent_v2_final_answer", return_value="Rejected"),
        ):
            result = self.agent.api_agent_approve(approval["approval_id"], self.agent.AgentApprovalRequest(approved=False))
        resume.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(contexts, [self.context])
        self.assertIs(contexts[0], self.context)
        self.assertIsNone(current_run_context())

    def test_approval_rechecks_cancellation_before_mutation(self):
        approval = self.approval()
        pending = self.agent.PENDING_AGENT_ACTIONS[approval["approval_id"]]
        self.context.cancel()
        with mock.patch.object(code_workspaces, "apply") as apply:
            with self.assertRaisesRegex(ToolPermissionError, "RUN_CANCELLED"):
                self.agent.execute_agent_approved_action(pending)
        apply.assert_not_called()

    def test_delete_patch_still_requires_confirmation_with_automatic_write_policy(self):
        patch = code_workspaces.create_patch(self.a["workspace_id"], "Delete", [{"path": "a.txt", "operation": "DELETE"}])
        engine = PermissionEngine(PermissionPolicy(allow_workspace_writes=True))
        decision = engine.decide("WRITE", ("workspace",), self.context, {"patch_id": patch["patch_id"]}, tool_name="code_apply")
        self.assertEqual(decision.decision, Decision.CONFIRM)
        self.assertEqual(decision.reason, "DELETE_REQUIRES_APPROVAL")

    def test_approval_does_not_bypass_existing_active_workspace_guard(self):
        approval = self.approval()
        pending = self.agent.PENDING_AGENT_ACTIONS[approval["approval_id"]]
        code_workspaces.set_active_workspace(self.b["workspace_id"])
        with self.assertRaisesRegex(ValueError, "WORKSPACE_CHANGED"):
            self.agent.execute_agent_approved_action(pending)
        self.assertFalse((self.root_a / "new.txt").exists())
        self.assertFalse((self.root_b / "new.txt").exists())


if __name__ == "__main__":
    unittest.main()
