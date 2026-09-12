import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image
import image_registry as registry
import image_providers as providers
import image_service as service
from agent import app as agent


class ImageRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(registry, "REGISTRY_FILE", self.root / "image-models.json"),
                        patch.object(service, "OUTPUT", self.root / "images"),
                        patch.object(agent, "MODEL_ROLES_FILE", self.root / "model-roles.json")]
        for item in self.patches:
            item.start()
        registry.load_registry()
        self.client = TestClient(service.app, base_url="http://localhost")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def test_persistence_and_safe_default(self):
        data = registry.load_registry()
        self.assertEqual(data["default_model"], "FLUX.1-schnell")
        self.assertGreaterEqual(len(data["models"]), 8)
        self.assertTrue(
            any(
                model["id"] == "mflux-qwen-image-edit-2511"
                for model in data["models"]
            )
        )
        self.assertEqual(
            registry.get_model(
                registry.QWEN_IMAGE_EDIT_ID,
                require_enabled=False,
            )["default_steps"],
            8,
        )
        self.assertEqual(
            registry.get_model(
                "mflux-qwen-image",
                require_enabled=False,
            )["default_steps"],
            30,
        )
        self.assertEqual(
            registry.get_model(
                "mflux-flux1-dev",
                require_enabled=False,
            )["default_steps"],
            28,
        )
        registry.update_model("mflux-z-image-turbo", {"default_steps": 7})
        self.assertEqual(registry.get_model("mflux-z-image-turbo", require_enabled=False)["default_steps"], 7)
        self.assertEqual(json.loads(registry.REGISTRY_FILE.read_text())["version"], 1)
        self.assertEqual(
            json.loads(registry.REGISTRY_FILE.read_text())[
                "builtin_defaults_revision"
            ],
            registry.BUILTIN_DEFAULTS_REVISION,
        )

    def test_existing_registry_migrates_new_builtin_families(self):
        legacy = registry.initial_registry()
        legacy["models"] = [legacy["models"][0]]
        legacy["default_model"] = registry.LEGACY_ID
        legacy["models"][0]["enabled"] = True
        registry.REGISTRY_FILE.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = registry.load_registry()
        ids = {model["id"] for model in migrated["models"]}
        self.assertIn("mflux-flux1-dev", ids)
        self.assertIn("mflux-z-image", ids)
        self.assertEqual(migrated["default_model"], registry.LEGACY_ID)
        legacy_model = next(model for model in migrated["models"] if model["id"] == registry.LEGACY_ID)
        self.assertTrue(legacy_model["enabled"])

    def test_existing_registry_migrates_only_the_old_qwen_edit_default(self):
        data = registry.initial_registry()
        qwen_edit = next(
            model
            for model in data["models"]
            if model["id"] == registry.QWEN_IMAGE_EDIT_ID
        )
        qwen_edit["default_steps"] = 30
        qwen_edit["default_guidance"] = 4.25
        data.pop("builtin_defaults_revision")
        registry.REGISTRY_FILE.write_text(
            json.dumps(data),
            encoding="utf-8",
        )

        migrated = registry.load_registry()
        migrated_edit = next(
            model
            for model in migrated["models"]
            if model["id"] == registry.QWEN_IMAGE_EDIT_ID
        )
        self.assertEqual(migrated_edit["default_steps"], 8)
        self.assertEqual(migrated_edit["default_guidance"], 4.25)
        self.assertEqual(
            registry.get_model(
                "mflux-qwen-image",
                require_enabled=False,
            )["default_steps"],
            30,
        )

        registry.update_model(
            registry.QWEN_IMAGE_EDIT_ID,
            {"default_steps": 12},
        )
        self.assertEqual(
            registry.get_model(
                registry.QWEN_IMAGE_EDIT_ID,
                require_enabled=False,
            )["default_steps"],
            12,
        )

        registry.update_model(
            registry.QWEN_IMAGE_EDIT_ID,
            {"default_steps": 30},
        )
        self.assertEqual(
            registry.get_model(
                registry.QWEN_IMAGE_EDIT_ID,
                require_enabled=False,
            )["default_steps"],
            30,
        )

    def test_legacy_prompt_png_metadata_and_seed(self):
        seen = []
        def generate(model, params, path):
            seen.append(params.copy())
            Image.new("RGB", (params["width"], params["height"]), "red").save(path)
        prompt = 'adult portrait; $(never-run) --model example'
        with patch.object(service, "run_provider", side_effect=generate):
            response = self.client.post("/generate", json={"prompt": prompt, "seed": 0})
            variation = self.client.post("/generate", json={"prompt": prompt})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["model"], registry.LEGACY_ID)
        self.assertEqual(result["prompt"], prompt)
        self.assertEqual(result["seed"], 0)
        self.assertEqual(result["steps"], 4)
        self.assertNotEqual(variation.json()["id"], result["id"])
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual(seen[0]["prompt"], prompt)

    def test_roles_never_resolve_image_through_llm(self):
        data = registry.load_registry()
        for model in data["models"]:
            model["available"] = True
        with patch.object(agent.image_api, "request", return_value=data), patch.object(agent, "load_models", side_effect=AssertionError("LLM aliases accessed")):
            result = agent.resolve_model_role("image")
        self.assertEqual(result["image_model_id"], registry.LEGACY_ID)
        self.assertEqual(result["provider"], "diffusionkit")

    def test_role_change_preserves_chat_and_agent(self):
        agent.save_model_roles({"chat": "chat-model", "agent": "agent-model"})
        with patch.object(agent.image_api, "request", return_value={"enabled": True, "available": True}), patch.object(agent, "resolve_model_role", return_value={}), patch.object(agent, "load_models", side_effect=AssertionError()):
            agent.set_model_role("image", {"alias": "mflux-z-image-turbo"})
        self.assertEqual(agent.load_model_roles()["chat"], "chat-model")
        self.assertEqual(agent.load_model_roles()["agent"], "agent-model")
        self.assertEqual(agent.load_model_roles()["image"], "mflux-z-image-turbo")

    def test_api_generation_resolves_image_role(self):
        agent.save_model_roles({"image": "mflux-qwen-image"})
        with patch.object(agent.image_api, "request", return_value={}) as request:
            agent.image_generate_api({"prompt": "hello"})
        self.assertEqual(request.call_args.args[2]["model"], "mflux-qwen-image")

    def test_bad_ids_paths_families_and_parameters(self):
        model = registry.load_registry()["models"][2]
        for invalid in ({"id": "../escape"}, {"local_path": "/etc"}, {"local_path": "relative"},
                        {"provider": "shell"}, {"base_model": "qwen-image"}, {"quantization": "q99"}):
            with self.assertRaises(ValueError):
                registry.ImageModel(**(model | invalid))
        for invalid in ({"width": 257}, {"seed": -1}, {"model": "../escape"}, {"command": "echo"}, {"steps": 10}):
            response = self.client.post("/generate", json={"prompt": "red apple", **invalid})
            self.assertEqual(response.status_code, 422, response.text)
        with self.assertRaises(ValueError):
            registry.LoRA(path="/etc/passwd")

    def test_multi_lora_fixed_commands_and_unmodified_prompt(self):
        model = registry.load_registry()["models"][1]
        model["loras"] = [registry.LoRA(repository="org/first:one.safetensors", scale=0.5).model_dump(),
                          registry.LoRA(repository="org/second", scale=-0.25).model_dump(),
                          registry.LoRA(repository="org/disabled", enabled=False).model_dump()]
        params = {"prompt": "--malicious $(touch /tmp/evil)", "width": 512, "height": 512, "steps": 4, "guidance": 0, "seed": 42}
        with patch.object(providers, "model_directory", return_value=Path("/models/test")):
            command = providers.mflux_command(model, params, Path("/images/output.png"))
        self.assertIn("--prompt=" + params["prompt"], command)
        self.assertIn("org/first:one.safetensors", command)
        self.assertIn("org/second", command)
        self.assertNotIn("org/disabled", command)
        self.assertIn("-0.25", command)
        model["model_family"] = "z-image-turbo"
        model["base_model"] = "z-image-turbo"
        with patch.object(providers, "model_directory", return_value=Path("/models/test")):
            command = providers.mflux_command(model, params, Path("/images/output.png"))
        self.assertNotIn("--guidance", command)
        self.assertTrue(command[0].endswith("mflux-generate-z-image-turbo"))

    def test_missing_lora_repository_is_not_reported_available(self):
        model = registry.get_model("mflux-flux1-dev", require_enabled=False)
        model["loras"] = [registry.LoRA(repository="org/style", enabled=True).model_dump()]
        fake_cli = self.root / "mflux-generate"
        fake_cli.touch()
        fake_cli.chmod(0o755)
        model_root = self.root / "model"
        model_root.mkdir()
        (model_root / "weights.safetensors").touch()
        with patch.object(providers, "MFLUX_BIN", self.root), patch.object(providers, "model_directory", return_value=model_root):
            ready, reason = providers.availability(model)
        self.assertFalse(ready)
        self.assertIn("LoRA", reason)

    def test_mflux_family_commands_are_explicit(self):
        model = registry.get_model("mflux-flux1-dev", require_enabled=False)
        params = {"prompt": "portrait", "width": 512, "height": 512,
                  "steps": 28, "guidance": 3.5, "seed": 7}
        with patch.object(providers, "model_directory", return_value=Path("/models/dev")):
            command = providers.mflux_command(model, params, Path("/tmp/out.png"))
        self.assertTrue(command[0].endswith("mflux-generate"))
        self.assertIn("--base-model", command)
        self.assertIn("dev", command)

        model = registry.get_model("mflux-z-image", require_enabled=False)
        params.update(prompt="landscape", steps=30, guidance=4, seed=8)
        with patch.object(providers, "model_directory", return_value=Path("/models/z")):
            command = providers.mflux_command(model, params, Path("/tmp/out.png"))
        self.assertTrue(command[0].endswith("mflux-generate-z-image"))
        self.assertIn("z-image", command)

    def test_qwen_edit_command_uses_the_dedicated_cli_contract(self):
        model = registry.get_model(
            "mflux-qwen-image-edit-2511",
            require_enabled=False,
        )
        params = {
            "prompt": "Keep the person and darken the background.",
            "source_path": "/uploads/source image.png",
            "steps": 20,
            "guidance": 3.5,
            "seed": 17,
        }

        with patch.object(
            providers,
            "model_directory",
            return_value=Path("/models/qwen-edit"),
        ):
            command = providers.mflux_command(
                model,
                params,
                Path("/images/output.png"),
            )

        self.assertTrue(
            command[0].endswith("mflux-generate-qwen-edit")
        )
        self.assertEqual(
            command[command.index("--image-paths") + 1],
            params["source_path"],
        )
        self.assertEqual(
            command[command.index("--model") + 1],
            "/models/qwen-edit",
        )
        for option in (
            "--base-model",
            "--width",
            "--height",
            "--quantize",
        ):
            self.assertNotIn(option, command)

    def test_provider_timeout_terminates_the_entire_process_group(self):
        model = registry.get_model(
            "mflux-qwen-image-edit-2511",
            require_enabled=False,
        )
        process = Mock(pid=4321, returncode=None)
        process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired(
            "mflux-generate-qwen-edit",
            2,
        )
        process.wait.side_effect = [
            subprocess.TimeoutExpired("provider", 5),
            -9,
        ]
        params = {
            "prompt": "Edit the image",
            "source_path": "/uploads/source.png",
            "steps": 4,
            "guidance": 3.5,
            "seed": 17,
        }

        with patch.object(
            providers,
            "availability",
            return_value=(True, "ready"),
        ), patch.object(
            providers,
            "model_directory",
            return_value=Path("/models/qwen-edit"),
        ), patch.object(
            providers.subprocess,
            "Popen",
            return_value=process,
        ) as popen, patch.object(
            providers.time,
            "monotonic",
            side_effect=[0, providers.GENERATION_TIMEOUT + 1],
        ), patch.object(
            providers.os,
            "killpg",
        ) as killpg:
            with self.assertRaisesRegex(
                RuntimeError,
                "Zeitlimit",
            ):
                providers.run_provider(
                    model,
                    params,
                    self.root / "timeout.png",
                )

        self.assertTrue(
            popen.call_args.kwargs["start_new_session"]
        )
        self.assertEqual(
            [call.args for call in killpg.call_args_list],
            [
                (4321, providers.signal.SIGTERM),
                (4321, providers.signal.SIGKILL),
            ],
        )
        self.assertEqual(process.wait.call_count, 2)

    def test_provider_rejects_a_non_png_edit_output(self):
        model = registry.get_model(
            "mflux-qwen-image-edit-2511",
            require_enabled=False,
        )
        output = self.root / "provider-output.png"
        Image.new("RGB", (64, 96), "black").save(
            output,
            format="JPEG",
        )
        process = Mock(pid=4321, returncode=0)
        process.poll.return_value = 0
        process.communicate.return_value = (None, None)
        params = {
            "prompt": "Edit the image",
            "source_path": "/uploads/source.png",
            "steps": 4,
            "guidance": 3.5,
            "seed": 17,
        }

        with patch.object(
            providers,
            "availability",
            return_value=(True, "ready"),
        ), patch.object(
            providers,
            "model_directory",
            return_value=Path("/models/qwen-edit"),
        ), patch.object(
            providers.subprocess,
            "Popen",
            return_value=process,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "gültiges PNG",
            ):
                providers.run_provider(model, params, output)

    def test_image_edit_endpoint_validates_source_and_returns_png_metadata(self):
        registry.update_model(
            "mflux-qwen-image-edit-2511",
            {"enabled": True},
        )
        service.OUTPUT.mkdir(parents=True)
        source = service.OUTPUT / "source.png"
        Image.new("RGB", (320, 480), "white").save(source)
        resolved_source = source.resolve()

        provider_params = []

        def edit_provider(_model, params, output):
            self.assertEqual(params["source_path"], str(resolved_source))
            provider_params.append(params.copy())
            Image.new("RGB", (304, 464), "black").save(output)

        with patch.object(
            service,
            "run_provider",
            side_effect=edit_provider,
        ):
            response = self.client.post(
                "/edit",
                json={
                    "prompt": "Darken the background",
                    "source_path": str(source),
                    "model": "mflux-qwen-image-edit-2511",
                    "seed": 17,
                },
            )

            explicit = self.client.post(
                "/edit",
                json={
                    "prompt": "Darken the background",
                    "source_path": str(source),
                    "model": "mflux-qwen-image-edit-2511",
                    "steps": 12,
                    "seed": 18,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(explicit.status_code, 200, explicit.text)
        result = response.json()
        self.assertEqual(result["width"], 304)
        self.assertEqual(result["height"], 464)
        self.assertEqual(result["source_path"], str(resolved_source))
        self.assertEqual(result["steps"], 8)
        self.assertEqual(explicit.json()["steps"], 12)
        self.assertEqual(provider_params[0]["steps"], 8)
        self.assertEqual(provider_params[1]["steps"], 12)
        self.assertTrue(Path(result["path"]).is_file())

        model = registry.get_model(
            registry.QWEN_IMAGE_EDIT_ID,
            require_enabled=False,
        )
        with patch.object(
            providers,
            "model_directory",
            return_value=Path("/models/qwen-edit"),
        ):
            command = providers.mflux_command(
                model,
                provider_params[0],
                Path("/images/output.png"),
            )
        self.assertEqual(
            command[command.index("--steps") + 1],
            "8",
        )

        invalid = self.client.post(
            "/edit",
            json={
                "prompt": "Darken the background",
                "source_path": str(self.root / "outside.png"),
                "model": "mflux-qwen-image-edit-2511",
            },
        )
        self.assertEqual(invalid.status_code, 422)

        with patch.object(
            service,
            "run_provider",
            side_effect=RuntimeError("Provider timeout"),
        ):
            failed = self.client.post(
                "/edit",
                json={
                    "prompt": "Darken the background",
                    "source_path": str(source),
                    "model": "mflux-qwen-image-edit-2511",
                },
            )
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["detail"], "Provider timeout")

    def test_image_intent_routing(self):
        image_context = {
            "kind": "image",
            "mime_type": "image/png",
            "stored_path": str(self.root / "portrait.png"),
        }
        text_context = {
            "kind": "text",
            "mime_type": "text/plain",
            "stored_path": str(self.root / "notes.txt"),
        }

        edit_prompts = (
            "ändere das Kleid in rot",
            "ändere das klein in die farbe rot",
            "mach das Kleid rot",
            "mach das rot",
            "mach den Hintergrund dunkler",
            "entferne die Person links",
            "mach mich etwas jünger",
            "ändere die Haarfarbe zu blond",
            "mach den Hintergrund unscharf",
            "ersetze den Himmel",
            "füge eine Sonnenbrille hinzu",
            "retuschiere das Gesicht",
            "change the dress to red",
            "make it red",
            "remove the person",
            "blur the background",
        )
        for prompt in edit_prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(
                    agent._looks_like_image_edit_request(prompt)
                )
                self.assertEqual(
                    agent._deterministic_chat_action(
                        prompt,
                        image_context,
                    ),
                    "image_edit",
                )

        vision_prompts = (
            "Was ist auf dem Bild?",
            "Beschreibe das Bild",
            "Welche Farbe hat das Kleid?",
            "Wie viele Personen sind zu sehen?",
            "Was hält die Person in der Hand?",
            "Ist das Bild scharf?",
        )
        for prompt in vision_prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(
                    agent._looks_like_image_edit_request(prompt)
                )
                self.assertNotEqual(
                    agent._deterministic_chat_action(
                        prompt,
                        image_context,
                    ),
                    "image_edit",
                )

        self.assertEqual(
            agent._deterministic_chat_action(
                "Erstelle ein Bild von einem roten Kleid"
            ),
            "image_generate",
        )
        self.assertEqual(
            agent._deterministic_chat_action(
                "create an image of a red dress"
            ),
            "image_generate",
        )
        self.assertNotEqual(
            agent._deterministic_chat_action(
                "Ändere diese Datei",
                text_context,
            ),
            "image_edit",
        )

    def test_image_edit_routing_and_artifact_response(self):
        source = self.root / "portrait.png"
        source.write_bytes(b"image")
        image_context = {
            "kind": "image",
            "mime_type": "image/png",
            "stored_path": str(source),
        }
        text_context = {
            "kind": "text",
            "mime_type": "text/plain",
            "stored_path": str(self.root / "notes.txt"),
        }

        self.assertEqual(
            agent._deterministic_chat_action(
                "Mach den Hintergrund dunkel",
                image_context,
            ),
            "image_edit",
        )
        self.assertFalse(agent._file_context_is_image(text_context))
        self.assertNotEqual(
            agent._deterministic_chat_action(
                "Ändere den Text",
                text_context,
            ),
            "image_edit",
        )
        self.assertFalse(
            agent._looks_like_image_edit_request(
                "Beschreibe das Bild"
            )
        )

        image_id = "1234567890-abcdef123456"
        provider_result = {
            "id": image_id,
            "path": str(agent.IMAGE_DIRECTORY / f"{image_id}.png"),
            "width": 832,
            "height": 1248,
            "prompt": "Mach den Hintergrund dunkel",
            "model": "mflux-qwen-image-edit-2511",
            "provider": "mflux",
            "model_family": "qwen-image-edit",
            "quantization": "q4",
            "steps": 4,
            "guidance": 3.5,
            "seed": 17,
            "source_path": str(source),
        }
        request = agent.ChatActionRequest(
            prompt="Mach den Hintergrund dunkel",
            file_context=image_context,
            image_options={"steps": 4},
            trace_id="image-edit-test",
        )

        with patch.object(
            agent.image_api,
            "request",
            return_value=provider_result,
        ) as image_request:
            result = agent.run_chat_action(request)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool"], "image_edit")
        self.assertEqual(
            result["artifacts"][0]["artifact_id"],
            f"image-{image_id}",
        )
        self.assertEqual(
            image_request.call_args.args[1],
            "/edit",
        )
        self.assertEqual(
            image_request.call_args.args[2]["source_path"],
            str(source),
        )
        self.assertEqual(
            image_request.call_args.args[2]["steps"],
            4,
        )

    def test_unsupported_lora_rejected(self):
        model = registry.get_model()
        model["loras"] = [{"repository": "org/lora", "enabled": True}]
        with self.assertRaises(ValueError):
            registry.ImageModel(**model)

    def test_switch_busy_and_failed_provider_cleanup(self):
        with service.exclusive():
            self.assertEqual(self.client.post("/generate", json={"prompt": "apple"}).status_code, 409)
            self.assertEqual(self.client.post("/models/FLUX.1-schnell/activate").status_code, 409)
            self.assertEqual(self.client.post("/unload").status_code, 409)
        with patch.object(service, "run_provider", side_effect=RuntimeError("offline model missing")):
            self.assertEqual(self.client.post("/generate", json={"prompt": "apple"}).status_code, 503)
        self.assertFalse(self.client.get("/health").json()["loaded"])
        self.assertEqual(self.client.post("/unload").status_code, 200)

    def test_missing_models_do_not_download_or_replace_default(self):
        registry.update_model("mflux-z-image-turbo", {"enabled": True})
        with patch.object(service, "availability", return_value=(False, "Gewichte fehlen")):
            self.assertEqual(self.client.post("/models/mflux-z-image-turbo/activate").status_code, 409)
        self.assertEqual(registry.load_registry()["default_model"], registry.LEGACY_ID)

    def test_plain_chat_and_image_routing(self):
        with patch.object(
            agent,
            "semantic_intent_classifier",
            return_value={
                "intent": "normal_chat",
                "confidence": 0.99,
                "requires_tools": False,
                "reason": "Allgemeine Wissensfrage",
            },
        ):
            self.assertEqual(
                agent.classify_chat_action("Erkläre Rekursion"),
                "normal_chat",
            )
        self.assertEqual(agent.classify_chat_action("Erstelle ein Bild von einem Apfel"), "image_generate")


if __name__ == "__main__":
    unittest.main()
