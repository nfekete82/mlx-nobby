"""Role selection at the chat, runtime, tool, router, image and embedding boundaries."""

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from agent import knowledge, run_state, runtime_tools
from agent.model_provider import ModelResponse


class RecordingProvider:
    def __init__(self):
        self.roles = []

    def complete(self, request, *, run_context=None):
        self.roles.append(request.role)
        return ModelResponse('{"action":"final","answer":"Done"}', "selected", request.role, {})


class ModelRoleRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(Path, "home", return_value=Path(directory)):
            from agent import app
        cls.app = app

    def test_runtime_uses_agent_and_coding_roles_for_planning_and_final(self):
        for mode, expected in (("diagnostic", "agent"), ("coding", "coding")):
            with self.subTest(mode=mode):
                provider = RecordingProvider()
                runtime = self.app.agent_runtime(
                    run_state.RunContext.start(), provider=provider,
                )
                result = runtime.run("Explain the task", mode=mode)
                self.assertEqual(result["status"], "completed")
                self.assertTrue(provider.roles)
                self.assertEqual(set(provider.roles), {expected})
                self.assertEqual(runtime.model_role, "agent")

    def test_resolver_uses_configured_roles_not_active_chat_model(self):
        roles = {"chat": "chat-alias", "agent": "agent-alias", "coding": "coding-alias",
                 "vision": "vision-alias", "embedding": "embedding-alias", "image": "auto"}
        models = [{"alias": alias, "repo": f"/models/{alias}"} for alias in roles.values() if alias != "auto"]
        with mock.patch.object(self.app, "load_model_roles", return_value=roles), \
             mock.patch.object(self.app, "load_models", return_value=models), \
             mock.patch.object(self.app, "load_config", return_value={"MODEL": "/models/chat-alias"}), \
             mock.patch.object(self.app.knowledge, "embedding_health", return_value={"ok": True, "model": "embedding-alias"}):
            for role in ("chat", "agent", "coding", "vision"):
                resolved = self.app.resolve_model_role(role)
                self.assertEqual(resolved["repo"], f"/models/{role}-alias")
            embedding = self.app.ensure_model_for_role("embedding")
        self.assertEqual(embedding["resolved"]["alias"], "embedding-alias")
        self.assertFalse(embedding["switched"])
        with mock.patch.object(self.app, "load_model_roles", return_value=roles), \
             mock.patch.object(self.app, "load_models", return_value=models), \
             mock.patch.object(self.app.knowledge, "embedding_health", return_value={"ok": True, "model": "previous-alias"}):
            with self.assertRaisesRegex(RuntimeError, "nicht verfügbar"):
                self.app.ensure_model_for_role("embedding")

    def test_normal_chat_ensures_chat_role(self):
        upstream = io.BytesIO(b'{"choices":[{"message":{"content":"Hello"}}]}')
        upstream.headers = {"Content-Type": "application/json"}
        upstream.status = 200
        with mock.patch.object(self.app, "ensure_model_for_role", return_value={
            "resolved": {"repo": "configured-chat-repo", "alias": "chat-alias"},
        }) as ensure, mock.patch.object(self.app, "load_config", return_value={"PORT": 8000}), \
             mock.patch.object(self.app.urllib.request, "urlopen", return_value=upstream) as urlopen:
            self.app.runtime_chat(self.app.RuntimeChatRequest(messages=[{"role": "user", "content": "Hi"}], stream=False))
        ensure.assert_called_once_with("chat")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["model"], "configured-chat-repo")

    def test_vision_tool_requests_vision_role(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "attached.png"
            image.write_bytes(b"image")
            context = run_state.RunContext.start(chat_id="chat-one", artifact_ids=("image-1234567890-aaaaaaaaaaaa",))
            provider = RecordingProvider()
            with run_state.bind_run_context(context), \
                 mock.patch.object(runtime_tools, "_chat_artifact"), \
                 mock.patch.object(self.app, "_resolve_image_artifact_source", return_value=image), \
                 mock.patch.object(runtime_tools, "current_runtime", return_value=types.SimpleNamespace(provider=provider)):
                runtime_tools._vision("", "Describe", {"artifact_id": context.artifact_ids[0]})
        self.assertEqual(provider.roles, ["vision"])

    def test_router_keeps_dedicated_model(self):
        upstream = io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
        with mock.patch.object(self.app.urllib.request, "urlopen", return_value=upstream) as urlopen, \
             mock.patch.object(self.app, "ensure_model_for_role") as ensure:
            self.app.router_llm([{"role": "user", "content": "Route this"}])
        ensure.assert_not_called()
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["model"], self.app.ROUTER_MODEL)

    def test_image_edit_payload_uses_image_role(self):
        with mock.patch.object(self.app, "_image_source_path", return_value=Path("/tmp/source.png")), \
             mock.patch.object(self.app, "optimize_image_edit_prompt", return_value="Edit"), \
             mock.patch.object(self.app, "load_model_roles", return_value={"image": "configured-image-model"}):
            payload = self.app._image_edit_payload(self.app.ChatActionRequest(prompt="Edit this"))
        self.assertEqual(payload["model"], "configured-image-model")

    def test_auto_image_edit_selects_an_available_edit_model(self):
        import image_service
        catalog = {"default_model": "generation-only", "models": [
            {"id": "generation-only", "enabled": True, "capabilities": ["text_to_image"]},
            {"id": "edit-capable", "enabled": True, "capabilities": ["image_edit"]},
        ]}
        with mock.patch.object(image_service, "registry_call", return_value=catalog), \
             mock.patch.object(image_service, "availability", return_value=(True, None)):
            selected = image_service._edit_model("auto")
        self.assertEqual(selected["id"], "edit-capable")


class EmbeddingRoleTests(unittest.TestCase):
    def test_document_search_does_not_mix_embedding_roles(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(knowledge, "ROOT", Path(directory)), \
             mock.patch.object(knowledge, "DB", Path(directory) / "knowledge.db"), \
             mock.patch.object(knowledge, "embedding_health", return_value={
                 "ok": True, "model": "first-model", "dimensions": 2,
             }), mock.patch.object(knowledge, "_request", return_value={
                 "model": "first-model", "dimensions": 2, "vectors": [[1.0, 0.0]],
             }):
            knowledge.index_uploaded_document("doc-one", "Document", [{"page": 1, "text": "A document"}])
            with mock.patch.object(knowledge, "_request", return_value={
                "model": "second-model", "dimensions": 2, "vectors": [[1.0, 0.0]],
            }):
                result = knowledge.search_uploaded_document("doc-one", "document")
        self.assertEqual(result["results"], [])

    def test_service_loads_registered_local_embedding_role_and_rejects_stale_model(self):
        fake_mx = types.ModuleType("mlx")
        fake_mx.core = types.ModuleType("mlx.core")
        fake_embeddings = types.ModuleType("mlx_embeddings")
        fake_utils = types.ModuleType("mlx_embeddings.utils")
        fake_utils.generate = mock.Mock()
        fake_utils.load = mock.Mock(return_value=(object(), object()))
        with mock.patch.dict(sys.modules, {
            "mlx": fake_mx, "mlx.core": fake_mx.core,
            "mlx_embeddings": fake_embeddings, "mlx_embeddings.utils": fake_utils,
        }), tempfile.TemporaryDirectory() as directory:
            spec = importlib.util.spec_from_file_location("embedding_service_role_test", Path(__file__).resolve().parents[1] / "embedding_service.py")
            service = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(service)
            root = Path(directory)
            model = root / "embedding-model"
            model.mkdir()
            roles = root / "model-roles.json"
            roles.write_text('{"embedding":"selected-alias"}')
            registered = root / "models"
            registered.write_text(f"selected-alias={model}\n")
            with mock.patch.object(service, "MODEL_ROLES_FILE", roles), \
                 mock.patch.object(service, "REGISTERED_MODELS_FILE", registered), \
                 mock.patch.object(service.Embedder, "embed_sync", return_value=[[0.1, 0.2, 0.3]]):
                embedder = service.Embedder()
                embedder.load()
                self.assertEqual(embedder.model_id, "selected-alias")
                self.assertEqual(embedder.dimensions, 3)
                fake_utils.load.assert_called_once_with(str(model.resolve()))
                registered.write_text("selected-alias=owner/embedding-model\n")
                fake_hub = types.ModuleType("huggingface_hub")
                fake_hub.snapshot_download = mock.Mock(return_value=str(model))
                with mock.patch.dict(sys.modules, {"huggingface_hub": fake_hub}):
                    self.assertEqual(service.selected_embedding_model(), ("selected-alias", model.resolve()))
                fake_hub.snapshot_download.assert_called_once_with(
                    repo_id="owner/embedding-model", local_files_only=True,
                )
                roles.write_text('{"embedding":"missing-alias"}')
                with self.assertRaisesRegex(RuntimeError, "nicht registriert"):
                    embedder.load()
                self.assertEqual(embedder.status, "failed")
                self.assertIsNone(embedder.model)


if __name__ == "__main__":
    unittest.main()
