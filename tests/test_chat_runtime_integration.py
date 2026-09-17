"""The chat boundary keeps selected resources and routing stable for a run."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agent import code_workspaces, run_state, runtime_tools
from agent.model_provider import ModelResponse
from agent.permissions import Decision, ToolPermissionError


class ChatRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(Path, "home", return_value=Path(directory)):
            from agent import app
        cls.app = app

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        storage = self.base / "state"
        patch = mock.patch.multiple(
            code_workspaces, ROOT=storage, WORKSPACES=storage / "workspaces.json",
            PATCHES=storage / "patches", SNAPSHOTS=storage / "snapshots",
            TESTS=storage / "tests", AUDIT=storage / "audit" / "changes.jsonl",
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.workspace = self.base / "project"
        self.workspace.mkdir()
        code_workspaces.add_workspace(str(self.workspace))
        self.upload_root = self.base / "uploads"
        self.upload_root.mkdir()
        upload_patch = mock.patch.object(self.app, "BATCH_UPLOAD_DIRECTORY", self.upload_root)
        upload_patch.start()
        self.addCleanup(upload_patch.stop)

    def request(self, **values):
        return self.app.AgentRunRequest(goal="Analysiere den Anhang", chat_id="chat-one", **values)

    def test_text_chat_and_web_use_existing_router(self):
        with mock.patch.object(self.app, "classify_chat_action_details", return_value={
            "intent": "normal_chat", "confidence": 0.99, "requires_tools": False,
            "method": "semantic_manager",
        }):
            plain = self.app.run_chat_action(self.app.ChatActionRequest(prompt="Hallo"))
        self.assertEqual(plain["tool"], "normal_chat")
        with mock.patch.object(self.app, "classify_chat_action_details", return_value={
            "intent": "web_search", "confidence": 0.99, "requires_tools": True,
            "method": "semantic_manager",
        }):
            web = self.app.run_chat_action(self.app.ChatActionRequest(prompt="Suche im Web nach MLX"))
        self.assertEqual(web["tool"], "web_search")

    def test_plain_image_analysis_stays_normal_chat_without_agent(self):
        route = self.app.run_chat_action(
            self.app.ChatActionRequest(
                prompt="Beschreibe dieses Bild.",
                file_context={
                    "kind": "image",
                    "stored_path": "/tmp/test-image.png",
                },
            )
        )

        self.assertEqual(route["tool"], "normal_chat")
        self.assertEqual(route["status"], "not_applicable")
        self.assertEqual(route["data"]["routing"]["intent"], "normal_chat")
        self.assertEqual(
            route["data"]["routing"]["method"],
            "deterministic_vision",
        )
        self.assertFalse(
            route["data"]["routing"]["requires_tools"]
        )

    def test_plain_image_analysis_beats_active_workspace_routing(self):
        route = self.app.run_chat_action(
            self.app.ChatActionRequest(
                prompt="Was ist auf dem Bild?",
                file_context={
                    "kind": "image",
                    "stored_path": "/tmp/test-image.png",
                },
            )
        )

        self.assertEqual(route["tool"], "normal_chat")
        self.assertNotEqual(route["tool"], "coding_agent")
        self.assertNotEqual(route["tool"], "diagnostic_agent")
        self.assertEqual(
            route["data"]["routing"]["method"],
            "deterministic_vision",
        )

    def test_workspace_read_write_git_and_tests_route_to_runtime(self):
        for prompt in (
            "Lies example.py und ändere sie.",
            "Gehe in dieses Projekt und behebe den Fehler.",
            "Führe die Tests aus.",
            "Zeig mir den Git-Diff.",
        ):
            with self.subTest(prompt=prompt):
                result = self.app.run_chat_action(self.app.ChatActionRequest(prompt=prompt))
                self.assertEqual(result["tool"], "coding_agent")
                self.assertEqual(result["data"]["workspace_id"], code_workspaces.active_workspace_id())

    def test_document_routes_to_runtime_and_bound_id_is_enforced(self):
        route = self.app.run_chat_action(self.app.ChatActionRequest(
            prompt="Analysiere diese PDF", file_context={"kind": "document", "document_id": "doc-one"},
        ))
        self.assertEqual(route["tool"], "research_agent")
        context = run_state.RunContext.start(chat_id="chat-one", document_ids=("doc-one",), resources_bound=True)
        with mock.patch.object(runtime_tools.knowledge, "search_uploaded_document", return_value={"results": []}):
            result = self.app.AGENT_TOOL_REGISTRY.execute(
                "document_search", run_context=context, goal="PDF", query="Inhalt",
                options={"document_id": "doc-one"},
            )
        self.assertEqual(result["results"], [])
        with self.assertRaises(ToolPermissionError) as denied:
            self.app.AGENT_TOOL_REGISTRY.execute(
                "document_search", run_context=context, goal="PDF", query="Inhalt",
                options={"document_id": "other"},
            )
        self.assertEqual(denied.exception.decision.decision, Decision.DENY)

    def test_run_binds_upload_workspace_and_conversation(self):
        upload = self.upload_root / "photo.png"
        upload.write_bytes(b"image")
        request = self.request(attachments=[
            {"kind": "image", "stored_path": str(upload)},
            {"kind": "document", "document_id": "doc-one"},
        ], conversation_context=[{"role": "user", "content": "Vorherige Frage"}])
        captured = {}

        def run(goal, **kwargs):
            captured.update(kwargs)
            return {"status": "completed", "goal": goal, "steps": [], "answer": "OK"}

        with mock.patch.object(self.app, "run_agent_v2", side_effect=run):
            result = self.app.api_agent_run(request)
        self.assertEqual(result["answer"], "OK")
        context = captured["run_context"]
        self.assertEqual(context.chat_id, "chat-one")
        self.assertEqual(context.upload_paths, (upload.resolve(),))
        self.assertEqual(context.document_ids, ("doc-one",))
        self.assertEqual(context.conversation, (("user", "Vorherige Frage"),))
        self.assertIn("Vorherige Frage", str(captured["conversation_context"]))
        other = self.base / "other"
        other.mkdir()
        code_workspaces.add_workspace(str(other))
        self.assertEqual(Path(context.workspace()["root_path"]).resolve(), self.workspace.resolve())
        self.assertEqual(context.upload_paths, (upload.resolve(),))
        self.assertEqual(context.document_ids, ("doc-one",))

    def test_explicit_absent_workspace_stays_absent(self):
        context = run_state.RunContext.start(chat_id="chat-one", workspace_bound=True)
        self.assertIsNone(context.workspace_id)
        with self.assertRaisesRegex(ValueError, "WORKSPACE_SELECTION_REQUIRED"):
            context.workspace()

    def test_upload_vision_and_image_edit_are_permission_gated(self):
        upload = self.upload_root / "photo.png"
        upload.write_bytes(b"image")
        context = run_state.RunContext.start(chat_id="chat-one", upload_paths=(upload,), resources_bound=True)
        provider = mock.Mock()
        provider.complete.return_value = ModelResponse("A picture", "vision", "vision", {})
        with mock.patch.object(runtime_tools, "current_runtime", return_value=mock.Mock(provider=provider)):
            vision = self.app.AGENT_TOOL_REGISTRY.execute(
                "vision_analyze", run_context=context, goal="Describe", query="",
                options={"upload_path": str(upload)},
            )
        self.assertEqual(vision["answer"], "A picture")
        with self.assertRaises(ToolPermissionError):
            self.app.AGENT_TOOL_REGISTRY.execute(
                "vision_analyze", run_context=context, goal="Describe", query="",
                options={"upload_path": str(self.base / "other.png")},
            )
        with self.assertRaises(ToolPermissionError) as confirmation:
            self.app.AGENT_TOOL_REGISTRY.execute(
                "image_edit", run_context=context, goal="Edit", query="Make it brighter",
                options={"upload_path": str(upload)},
            )
        self.assertEqual(confirmation.exception.decision.decision, Decision.CONFIRM)

    def test_artifact_and_upload_cannot_be_swapped_after_start(self):
        image_id = "1234567890-aaaaaaaaaaaa"
        artifact_id = f"image-{image_id}"
        chat = {"id": "chat-one", "revision": 4, "messages": [{"image_id": image_id}]}
        with mock.patch.object(self.app, "read_chat", return_value=chat):
            context = self.app._chat_run_context(self.request(
                chat_revision=4, active_artifact_id=artifact_id,
            ), "run-one")
        self.assertEqual(context.artifact_ids, (artifact_id,))
        self.assertEqual(context.chat_revision, 4)
        with self.assertRaises(ToolPermissionError) as denied:
            self.app.AGENT_TOOL_REGISTRY.execute(
                "vision_analyze", run_context=context, goal="Describe", query="",
                options={"artifact_id": "image-1234567890-bbbbbbbbbbbb"},
            )
        self.assertEqual(denied.exception.decision.decision, Decision.DENY)
        with self.assertRaisesRegex(ValueError, "UPLOAD_OUTSIDE_RUN"):
            self.app._chat_run_context(self.request(attachments=[{
                "stored_path": str(self.base / "elsewhere.png"),
            }]), "run-two")

    def test_file_job_keeps_chat_and_run_identity(self):
        source = self.base / "file.txt"
        source.write_text("content")
        with mock.patch.object(self.app, "BATCH_LOCK"), mock.patch.object(self.app, "load_batch_jobs", return_value={}), mock.patch.object(self.app, "save_batch_jobs"):
            job = self.app.create_file_analysis_job(
                str(source), "Analyse", "text", 1000, "analyze",
                chat_id="chat-one", run_id="run-one",
            )
        self.assertEqual((job["chat_id"], job["run_id"]), ("chat-one", "run-one"))


    def test_natural_workspace_review_prompts_route_to_coding_agent(self):
        prompts = (
            "check mal das blackjack spiel, also die html datei und gib feedback",
            "check die html datei",
            "checke die datei",
            "review die datei",
            "analysiere die html datei",
            "prüfe die datei",
            "schau dir die datei an",
            "prüfe mal die datei blackjack.html und ob man das spiel verbessern kann?",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(
                    self.app._looks_like_coding_action(prompt, [])
                )
                self.assertEqual(
                    self.app._deterministic_chat_action(
                        prompt,
                        None,
                        [],
                    ),
                    "coding_agent",
                )

    def test_generic_programming_questions_do_not_route_to_coding_agent(self):
        prompts = (
            "Was ist HTML?",
            "Erkläre mir JavaScript.",
            "Wie funktioniert CSS?",
            "Was ist eine PHP Session?",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotEqual(
                    self.app._deterministic_chat_action(
                        prompt,
                        None,
                        [],
                    ),
                    "coding_agent",
                )


if __name__ == "__main__":
    unittest.main()
