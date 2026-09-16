import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from agent import code_workspaces, run_state, runtime_tools
from agent.model_provider import ModelResponse
from agent.permissions import Decision, ToolPermissionError


class RuntimeToolAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        with mock.patch.object(Path, "home", return_value=Path(directory.name)):
            from agent import app
        cls.app = app

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        storage = self.base / "state"
        patch = mock.patch.multiple(
            code_workspaces, ROOT=storage, WORKSPACES=storage / "workspaces.json",
            PATCHES=storage / "patches", SNAPSHOTS=storage / "snapshots",
            TESTS=storage / "tests", AUDIT=storage / "audit" / "changes.jsonl",
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.workspace_info = code_workspaces.add_workspace(str(self.workspace))
        self.context = run_state.RunContext.start(run_id="adapter-run", chat_id="adapter-chat")
        self.registry = self.app.AGENT_TOOL_REGISTRY

    def execute(self, name, *, query=None, options=None, goal="Inspect", instruction=None):
        return self.registry.execute(
            name, run_context=self.context, goal=goal, query=query,
            instruction=instruction, files=None, options=options,
        )

    def approved(self, name, *, query=None, options=None, goal="Inspect", instruction=None):
        arguments = dict(goal=goal, query=query, instruction=instruction, files=None, options=options)
        with self.assertRaises(ToolPermissionError) as error:
            self.registry.execute(name, run_context=self.context, **arguments)
        self.assertEqual(error.exception.decision.decision, Decision.CONFIRM)
        return self.registry.execute_approved(
            name, run_context=self.context, expected_tool=self.registry.get(name), **arguments,
        )

    def test_registry_and_workspace_binding(self):
        names = self.registry.names()
        self.assertTrue({"workspace_status", "shell_workspace", "git_status", "git_diff", "git_log",
                         "git_stage", "git_commit", "vision_analyze", "image_generate", "image_edit",
                         "image_job_status", "document_search", "document_page", "file_analyze",
                         "file_analysis_status", "file_inspect", "file_pii_audit"} <= names)
        other = self.base / "other"
        other.mkdir()
        code_workspaces.add_workspace(str(other))
        result = self.execute("workspace_status")
        self.assertEqual(result["workspace_id"], self.workspace_info["workspace_id"])
        self.assertEqual(self.context.workspace_root, self.workspace)

    def test_shell_confirm_is_bounded_and_rejects_destructive_commands(self):
        (self.workspace / "sample.txt").write_text("SHELL_MARKER\n" * 100)
        with mock.patch.object(runtime_tools, "OUTPUT_LIMIT", 40):
            result = self.approved("shell_workspace", query="rg SHELL_MARKER sample.txt")
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"]), 40)
        with self.assertRaises(ToolPermissionError) as error:
            self.execute("shell_workspace", query="rm sample.txt")
        self.assertEqual(error.exception.decision.decision, Decision.DENY)
        self.assertTrue((self.workspace / "sample.txt").exists())
        with self.assertRaises(ToolPermissionError):
            self.execute("shell_workspace", query="pwd")

    def test_shell_timeout_and_cancel(self):
        with mock.patch.object(runtime_tools.subprocess, "run", side_effect=subprocess.TimeoutExpired("pwd", 1)):
            result = self.approved("shell_workspace", query="pwd")
        self.assertTrue(result["timed_out"])
        self.context.cancel()
        with self.assertRaises(ToolPermissionError) as error:
            self.execute("shell_workspace", query="pwd")
        self.assertEqual(error.exception.decision.reason, "RUN_CANCELLED")

    def test_git_read_stage_commit_and_workspace_isolation(self):
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Adapter Test"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.email", "adapter@example.invalid"], check=True)
        (self.workspace / "selected.txt").write_text("selected\n")
        (self.workspace / "other.txt").write_text("other\n")
        other = self.base / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        code_workspaces.add_workspace(str(other))
        self.assertIn("selected.txt", self.execute("git_status")["stdout"])
        self.assertEqual(self.execute("git_diff")["returncode"], 0)
        subprocess.run(["git", "-C", str(self.workspace), "add", "-N", "--", "selected.txt"], check=True)
        self.assertIn("selected", self.execute("git_diff", query="None")["stdout"])
        self.assertEqual(self.execute("git_log")["returncode"], 128)
        with self.assertRaises(ToolPermissionError) as error:
            self.execute("git_stage", options={"paths": ["../other/other.txt"]})
        self.assertEqual(error.exception.decision.decision, Decision.DENY)
        for path in (".", "*.txt", ":(top)selected.txt"):
            with self.subTest(path=path), self.assertRaises(ToolPermissionError) as error:
                self.execute("git_stage", options={"paths": [path]})
            self.assertEqual(error.exception.decision.decision, Decision.DENY)
        self.assertEqual(self.approved("git_stage", options={"paths": ["selected.txt"]})["returncode"], 0)
        self.assertIn("selected", self.execute("git_diff", options={"cached": True})["stdout"])
        with self.assertRaisesRegex(ValueError, "GIT_STAGED_PATHS_CHANGED"):
            self.approved("git_commit", options={"paths": ["other.txt"], "message": "Wrong"})
        committed = self.approved("git_commit", options={"paths": ["selected.txt"], "message": "Add selected"})
        self.assertEqual(committed["returncode"], 0, committed)
        self.assertIn("Add selected", self.execute("git_log")["stdout"])
        self.assertIn("other.txt", self.execute("git_status")["stdout"])

    def test_image_job_adapter_preserves_chat_contract(self):
        with mock.patch.object(self.app, "read_chat", return_value={"revision": 2}), \
             mock.patch.object(self.app, "_start_chat_image_job", return_value={"id": "job-one", "status": "queued"}) as start:
            job = self.approved("image_generate", query="A red square")
        self.assertEqual(job["status"], "queued")
        request = start.call_args.args[1]
        self.assertEqual((request.chat_id, request.chat_revision, request.prompt),
                         ("adapter-chat", 2, "A red square"))
        image_id = "image-1234567890-abcdef123456"
        with mock.patch.object(self.app, "read_chat", return_value={"revision": 2, "image_id": "1234567890-abcdef123456"}), \
             mock.patch.object(self.app, "_start_chat_image_job", return_value={"id": "job-two", "status": "queued"}):
            self.assertEqual(self.approved("image_edit", query="Make it blue", options={"artifact_id": image_id})["id"], "job-two")
        with mock.patch.object(self.app.image_api, "request", return_value={"chat_id": "other-chat", "operation": "generate", "status": "queued"}):
            with self.assertRaisesRegex(ValueError, "IMAGE_JOB_OUTSIDE_CHAT"):
                self.execute("image_job_status", query="a" * 24)
        with mock.patch.object(self.app.image_api, "request", return_value={"chat_id": "adapter-chat", "operation": "generate", "status": "queued"}), \
             mock.patch.object(self.app, "_image_job_tool_result", return_value={"action": "image_generate", "status": "queued"}):
            self.assertEqual(self.execute("image_job_status", query="a" * 24)["status"], "queued")

    def test_vision_workspace_image_and_provider_contract(self):
        data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wlq0SQAAAAASUVORK5CYII=")
        (self.workspace / "tiny.png").write_bytes(data)
        provider = mock.Mock()
        provider.complete.return_value = ModelResponse("A dot", "vision-local", "vision", {})
        with mock.patch.object(runtime_tools, "current_runtime", return_value=mock.Mock(provider=provider)):
            result = self.execute("vision_analyze", query="tiny.png", options={"prompt": "Describe"})
        self.assertEqual(result["answer"], "A dot")
        request = provider.complete.call_args.args[0]
        self.assertEqual(request.role, "vision")
        self.assertTrue(request.messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        with self.assertRaises(ToolPermissionError):
            self.execute("vision_analyze", query="../outside.png")

    def test_vision_chat_artifact_does_not_require_code_workspace(self):
        source = self.base / "managed.png"
        source.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wlq0SQAAAAASUVORK5CYII="
        ))
        context = run_state.RunContext("image-run", "adapter-chat", None, None, ())
        provider = mock.Mock()
        provider.complete.return_value = ModelResponse("A dot", "vision-local", "vision", {})
        with mock.patch.object(self.app, "read_chat", return_value={"image_id": "1234567890-abcdef123456"}), \
             mock.patch.object(self.app, "_resolve_image_artifact_source", return_value=source), \
             mock.patch.object(runtime_tools, "current_runtime", return_value=mock.Mock(provider=provider)):
            result = self.registry.execute(
                "vision_analyze", run_context=context, goal="Describe",
                query=None, instruction=None, files=None,
                options={"artifact_id": "image-1234567890-abcdef123456"},
            )
        self.assertEqual(result["answer"], "A dot")

    def test_documents_use_existing_search_page_and_analysis_jobs(self):
        with mock.patch.object(runtime_tools.knowledge, "search_uploaded_document", return_value={"results": [{"content": "hit" * 1000}]}) as search:
            result = self.execute("document_search", query="needle", options={"document_id": "doc"})
        self.assertEqual(len(result["results"][0]["content"]), 1500)
        self.assertTrue(result["truncated"])
        search.assert_called_once_with("doc", "needle", limit=6)
        with mock.patch.object(runtime_tools.knowledge, "get_uploaded_document_page", return_value={"text": "x" * 100}) as page, \
             mock.patch.object(runtime_tools, "OUTPUT_LIMIT", 30):
            self.assertEqual(len(self.execute("document_page", options={"document_id": "doc", "page": 2})["text"]), 30)
        page.assert_called_once_with("doc", 2)
        (self.workspace / "note.txt").write_text("Safe content")
        with mock.patch.object(self.app, "analyze_file_structure", return_value={"filename": "note.txt"}) as inspect:
            self.assertEqual(self.execute("file_inspect", query="note.txt")["filename"], "note.txt")
        inspect.assert_called_once_with(str(self.workspace / "note.txt"))
        with mock.patch.object(self.app, "analyze_file_structure", return_value={"sample": "x" * 50000}):
            bounded = self.execute("file_inspect", query="note.txt")
        self.assertTrue(bounded["truncated"])
        self.assertLess(len(bounded["sample"]), 12000)
        with mock.patch.object(self.app, "deterministic_pii_audit", return_value={"pii": 0}) as pii:
            self.assertEqual(self.execute("file_pii_audit", query="note.txt")["pii"], 0)
        pii.assert_called_once_with("Safe content")
        with mock.patch.object(self.app, "create_file_analysis_job", return_value={"id": "a" * 12, "status": "queued"}) as create, \
             mock.patch.object(self.app, "start_file_analysis_job") as start:
            job = self.approved("file_analyze", query="note.txt", instruction="Summarize", options={"operation": "summarize"})
        self.assertEqual(job["job_id"], "a" * 12)
        self.assertEqual(create.call_args.args[0], str(self.workspace / "note.txt"))
        start.assert_called_once_with("a" * 12)
        with self.assertRaises(ToolPermissionError):
            self.execute("file_analyze", query="../other.txt")
        (self.workspace / "paper.pdf").write_bytes(b"%PDF")
        with self.assertRaisesRegex(ValueError, "USE_INDEXED_DOCUMENT_FOR_PDF"):
            self.approved("file_analyze", query="paper.pdf")

    def test_existing_web_registry_adapter_is_unchanged(self):
        with mock.patch.object(self.app, "tool_search_web", return_value={"results": [{"url": "https://example.org"}]}) as search:
            result = self.execute("search_web", query="example")
        self.assertEqual(result["results"][0]["url"], "https://example.org")
        self.assertEqual(search.call_args.args[0].prompt, "example")

    def test_shell_approval_resumes_original_runtime_and_workspace(self):
        from fastapi.testclient import TestClient
        replies = iter([
            {"action": "shell_workspace", "query": "pwd", "reason": "Inspect workspace"},
            {"action": "final", "answer": "Workspace checked"},
        ])
        provider = mock.Mock()
        provider.complete.side_effect = lambda request, **kwargs: ModelResponse(
            json.dumps(next(replies)), "fake-local", request.role, {},
        )
        with mock.patch.object(self.app, "agent_model_provider", return_value=provider), \
             mock.patch.object(self.app, "PENDING_AGENT_ACTIONS", {}), \
             mock.patch.object(self.app, "ACTIVE_AGENT_RUNS", {}):
            with TestClient(self.app.app, base_url="http://localhost") as client:
                response = client.post("/api/agent/run", json={
                    "goal": "Inspect workspace", "mode": "diagnostic",
                    "run_id": "a" * 32, "chat_id": "adapter-chat",
                })
                self.assertEqual(response.status_code, 200, response.text)
                pending_action = response.json()["pending_action"]
                self.assertEqual(pending_action["permission_decision"]["decision"], "CONFIRM")
                pending = self.app.PENDING_AGENT_ACTIONS[pending_action["approval_id"]]
                original_runtime = pending["runtime"]
                self.assertIs(original_runtime.context, pending["run_context"])
                other = self.base / "other"
                other.mkdir()
                code_workspaces.add_workspace(str(other))
                resumed = client.post("/api/agent/approve/" + pending_action["approval_id"], json={"approved": True})
                self.assertEqual(resumed.status_code, 200, resumed.text)
                result = resumed.json()
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["steps"][-1]["result"]["stdout"].strip(), str(self.workspace))
                self.assertEqual(client.get("/api/agent/runs/" + "a" * 32).json()["status"], "completed")
                self.assertEqual(client.post("/api/agent/approve/" + pending_action["approval_id"], json={"approved": True}).status_code, 404)

    def test_git_approval_exposes_selected_paths_and_message(self):
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        target = self.workspace / "selected.txt"
        target.write_text("first\n")
        subprocess.run(["git", "-C", str(self.workspace), "add", "--", "selected.txt"], check=True)
        runtime = self.app.agent_runtime(self.context, provider=mock.Mock())
        arguments = {"goal": "Commit", "query": None, "instruction": None, "files": None,
                     "options": {"paths": ["selected.txt"], "message": "Add selected"}}
        with mock.patch.object(self.app, "PENDING_AGENT_ACTIONS", {}) as pending_store:
            approvals = self.app.agent_approvals(runtime)
            approval = approvals.create(
                "Commit", [], 1, "coding", "git_commit", None, "Commit selected",
                runtime=runtime, tool_request=arguments,
            )
            target.write_text("changed\n")
            subprocess.run(["git", "-C", str(self.workspace), "add", "--", "selected.txt"], check=True)
            with self.assertRaisesRegex(ValueError, "GIT_STAGED_CONTENT_CHANGED"):
                approvals.execute(pending_store[approval["approval_id"]])
        self.assertEqual(approval["paths"], ["selected.txt"])
        self.assertEqual(approval["message"], "Add selected")

    def test_stage_approval_rejects_changed_file_content(self):
        target = self.workspace / "selected.txt"
        target.write_text("first\n")
        runtime = self.app.agent_runtime(self.context, provider=mock.Mock())
        arguments = {"goal": "Stage", "query": None, "instruction": None, "files": None,
                     "options": {"paths": ["selected.txt"]}}
        with mock.patch.object(self.app, "PENDING_AGENT_ACTIONS", {}) as pending_store:
            approvals = self.app.agent_approvals(runtime)
            approval = approvals.create(
                "Stage", [], 1, "coding", "git_stage", None, "Stage selected",
                runtime=runtime, tool_request=arguments,
            )
            target.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "GIT_WORKTREE_CONTENT_CHANGED"):
                approvals.execute(pending_store[approval["approval_id"]])


if __name__ == "__main__":
    unittest.main()
