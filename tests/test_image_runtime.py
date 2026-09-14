import copy
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from backend import observability
import image_registry as registry
import image_providers as providers
import image_service as service
import sdxl_worker
from agent import app as agent


FAKE_SDXL_WORKER = r'''
import json
import os
import sys
import time

boot_id = f"{os.getpid()}-{time.time_ns()}"
loaded_model = None
for line in sys.stdin:
    request = json.loads(line)
    params = request["params"]
    log_path = params["test_log"]
    model = (request["checkpoint"], request["config"])
    event = {
        "boot_id": boot_id,
        "kind": "request",
        "params": params,
    }
    if model != loaded_model:
        event["loaded"] = True
        loaded_model = model
    with open(log_path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")
    if params.get("behavior") == "crash":
        os._exit(17)
    if params.get("behavior") == "wait":
        time.sleep(10)
    print(json.dumps({
        "type": "runtime",
        "request_id": request["request_id"],
        "phase": "generate",
        "step": 1,
        "total_steps": params["steps"],
    }), flush=True)
    print(json.dumps({
        "type": "complete",
        "request_id": request["request_id"],
    }), flush=True)
'''


class ImageRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(registry, "REGISTRY_FILE", self.root / "image-models.json"),
                        patch.object(service, "OUTPUT", self.root / "images"),
                        patch.object(agent, "IMAGE_DIRECTORY", self.root / "images"),
                        patch.object(agent, "CHAT_DIRECTORY", self.root / "chats"),
                        patch.object(agent, "MODEL_ROLES_FILE", self.root / "model-roles.json")]
        for item in self.patches:
            item.start()
        with service._jobs_lock:
            service._jobs.clear()
            service._active_job_id = None
        registry.load_registry()
        self.client = TestClient(service.app, base_url="http://localhost")

        # Existing image-runtime tests predate chat-bound image jobs.
        # Supply neutral chat metadata for direct /jobs calls unless a test
        # explicitly provides its own identity.
        original_post = self.client.post

        def post_with_chat_identity(url, *args, **kwargs):
            if (
                url == "/jobs"
                and isinstance(kwargs.get("json"), dict)
            ):
                payload = copy.deepcopy(kwargs["json"])
                payload.setdefault("chat_id", "test-chat")
                payload.setdefault("chat_revision", 0)
                kwargs["json"] = payload

            return original_post(url, *args, **kwargs)

        self.client.post = post_with_chat_identity

    def tearDown(self):
        with service._jobs_lock:
            jobs = list(service._jobs.values())
        for job in jobs:
            job.get("_cancel_event", threading.Event()).set()
            thread = job.get("_thread")
            if thread:
                thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def make_chat_action_request(
        self,
        *,
        chat_id="test-image-chat",
        revision=0,
        **kwargs,
    ):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": chat_id,
            "title": "Test chat",
            "created": 1,
            "updated": time.time() * 1000,
            "revision": revision,
            "messages": [],
        })

        return agent.ChatActionRequest(
            chat_id=chat_id,
            chat_revision=revision,
            **kwargs,
        )

    def wait_for_image_job(self, job_id, statuses, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.client.get(f"/jobs/{job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            if job["status"] in statuses:
                return job
            time.sleep(0.01)
        self.fail(f"Image job {job_id} did not reach {statuses}")

    def make_sdxl_worker_manager(self, idle_timeout=5):
        worker = self.root / "fake_sdxl_worker.py"
        worker.write_text(FAKE_SDXL_WORKER, encoding="utf-8")
        return providers.SDXLWorkerManager(
            worker_path=worker,
            idle_timeout=idle_timeout,
            monitor_rss=False,
        )

    def run_fake_sdxl(
        self,
        manager,
        *,
        process_callback=None,
        progress_callback=None,
        **overrides,
    ):
        params = {
            "prompt": "First prompt",
            "negative_prompt": "blurry",
            "width": 512,
            "height": 512,
            "steps": 1,
            "guidance": 6.5,
            "seed": 42,
            "test_log": str(self.root / "sdxl-worker.jsonl"),
        } | overrides
        manager.generate(
            self.root / "juggernaut.safetensors",
            self.root / "config",
            params,
            self.root / "output.png",
            environment=os.environ.copy(),
            process_callback=process_callback,
            progress_callback=progress_callback,
        )

    def sdxl_worker_log(self):
        return [
            json.loads(line)
            for line in (self.root / "sdxl-worker.jsonl").read_text().splitlines()
        ]

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

    def test_juggernaut_registry_entry_is_local_and_opt_in(self):
        model = registry.get_model(
            registry.JUGGERNAUT_XL_ID,
            require_enabled=False,
        )
        self.assertEqual(model["provider"], "sdxl")
        self.assertEqual(model["model_family"], "sdxl")
        self.assertEqual(model["local_path"], str(registry.JUGGERNAUT_XL_DIRECTORY))
        self.assertFalse(model["enabled"])
        self.assertIn("photorealistic", model["capabilities"])

    def test_sdxl_checkpoint_resolution_is_local_and_unambiguous(self):
        model_root = self.root / "JuggernautXL"
        model_root.mkdir()
        checkpoint = model_root / "juggernaut.safetensors"
        model = registry.get_model(
            registry.JUGGERNAUT_XL_ID,
            require_enabled=False,
        ) | {"local_path": str(model_root)}

        with patch.object(registry, "MODEL_ROOTS", (self.root,)):
            with self.assertRaisesRegex(RuntimeError, "genau einen"):
                providers.sdxl_files(model)
            checkpoint.write_bytes(b"checkpoint")
            with self.assertRaisesRegex(RuntimeError, "Konfiguration fehlt"):
                providers.sdxl_files(model)
            config = model_root / "config"
            config.mkdir()
            (config / "model_index.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                providers.sdxl_files(model),
                (checkpoint, config),
            )
            (model_root / "second.safetensors").write_bytes(b"checkpoint")
            with self.assertRaisesRegex(RuntimeError, "genau einen"):
                providers.sdxl_files(model)

        with self.assertRaises(ValueError):
            registry.ImageModel(**(model | {"local_path": "/etc/model.safetensors"}))

    def test_sdxl_idle_timeout_is_configurable_with_safe_default(self):
        with patch.dict(
            os.environ,
            {"MLX_IMAGE_SDXL_IDLE_TIMEOUT": "75"},
        ):
            manager = providers.SDXLWorkerManager()
        self.assertEqual(manager.idle_timeout, 75)

        with patch.dict(
            os.environ,
            {"MLX_IMAGE_SDXL_IDLE_TIMEOUT": "invalid"},
        ):
            manager = providers.SDXLWorkerManager()
        self.assertEqual(
            manager.idle_timeout,
            providers.DEFAULT_SDXL_IDLE_TIMEOUT,
        )

    def test_sdxl_provider_uses_the_warm_worker_contract(self):
        model = registry.get_model(
            registry.JUGGERNAUT_XL_ID,
            require_enabled=False,
        )
        checkpoint = self.root / "juggernaut.safetensors"
        config = self.root / "config"
        output = self.root / "output.png"
        Image.new("RGB", (512, 512), "white").save(output)
        manager = Mock()
        params = {
            "prompt": "Studio portrait",
            "negative_prompt": "blurry",
            "width": 512,
            "height": 512,
            "steps": 12,
            "guidance": 6.5,
            "seed": 42,
        }

        with patch.object(
            providers,
            "availability",
            return_value=(True, "ready"),
        ), patch.object(
            providers,
            "sdxl_files",
            return_value=(checkpoint, config),
        ), patch.object(
            providers,
            "_sdxl_worker_manager",
            manager,
        ):
            providers.run_provider(model, params, output)

        args = manager.generate.call_args.args
        self.assertEqual(args[:2], (checkpoint, config))
        self.assertEqual(args[2]["negative_prompt"], "blurry")
        self.assertEqual(args[3], output)

    def test_sdxl_worker_starts_once_reuses_pipeline_and_isolates_parameters(self):
        manager = self.make_sdxl_worker_manager()
        try:
            self.assertIsNone(manager._process)
            processes = []
            progress = []
            self.run_fake_sdxl(
                manager,
                process_callback=processes.append,
                progress_callback=progress.append,
            )
            first_process = manager._process
            self.assertIsNotNone(first_process)
            self.assertEqual(processes, [first_process, None])
            self.assertEqual(progress, [{
                "phase": "generate",
                "step": 1,
                "total_steps": 1,
            }])
            self.run_fake_sdxl(
                manager,
                prompt="Second prompt",
                negative_prompt="",
                seed=99,
                guidance=4.0,
            )
            self.assertIs(manager._process, first_process)
            log = self.sdxl_worker_log()
            self.assertEqual(len({entry["boot_id"] for entry in log}), 1)
            self.assertEqual(sum(bool(entry.get("loaded")) for entry in log), 1)
            self.assertEqual(log[0]["params"]["prompt"], "First prompt")
            self.assertEqual(log[0]["params"]["seed"], 42)
            self.assertEqual(log[1]["params"]["prompt"], "Second prompt")
            self.assertEqual(log[1]["params"]["seed"], 99)
            self.assertEqual(log[1]["params"]["negative_prompt"], "")
            self.assertEqual(log[1]["params"]["guidance"], 4.0)
        finally:
            manager.close()

    def test_sdxl_worker_reuses_one_pipeline_with_fresh_request_state(self):
        loads = []
        calls = []

        class FakeGenerator:
            def __init__(self, device):
                self.device = device
                self.seed = None

            def manual_seed(self, seed):
                self.seed = seed
                return self

        class FakeImage:
            def save(self, *_args, **_kwargs):
                pass

        class FakePipeline:
            @classmethod
            def from_single_file(cls, checkpoint, **options):
                loads.append((checkpoint, options))
                return cls()

            def to(self, device):
                self.device = device
                return self

            def __call__(self, **options):
                calls.append(options)
                return types.SimpleNamespace(images=[FakeImage()])

        fake_torch = types.ModuleType("torch")
        fake_torch.float16 = "float16"
        fake_torch.Generator = FakeGenerator
        fake_torch.backends = types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: True)
        )
        fake_torch.mps = types.SimpleNamespace(empty_cache=lambda: None)
        fake_diffusers = types.ModuleType("diffusers")
        fake_diffusers.StableDiffusionXLPipeline = FakePipeline
        requests = [
            {
                "request_id": "first",
                "checkpoint": "juggernaut.safetensors",
                "config": "config",
                "output": "first.png",
                "params": {
                    "prompt": "First",
                    "negative_prompt": "blurry",
                    "width": 512,
                    "height": 512,
                    "steps": 12,
                    "guidance": 6.5,
                    "seed": 42,
                },
            },
            {
                "request_id": "second",
                "checkpoint": "juggernaut.safetensors",
                "config": "config",
                "output": "second.png",
                "params": {
                    "prompt": "Second",
                    "negative_prompt": "",
                    "width": 768,
                    "height": 512,
                    "steps": 8,
                    "guidance": 4.0,
                    "seed": 99,
                },
            },
        ]
        worker_input = io.StringIO(
            "".join(json.dumps(request) + "\n" for request in requests)
        )

        with patch.dict(
            "sys.modules",
            {"torch": fake_torch, "diffusers": fake_diffusers},
        ), patch.object(
            sdxl_worker.sys,
            "stdin",
            worker_input,
        ), patch.object(
            sdxl_worker.sys,
            "stdout",
            io.StringIO(),
        ):
            sdxl_worker.main()

        self.assertEqual(len(loads), 1)
        self.assertEqual([call["prompt"] for call in calls], ["First", "Second"])
        self.assertEqual([call["width"] for call in calls], [512, 768])
        self.assertEqual([call["num_inference_steps"] for call in calls], [12, 8])
        self.assertEqual([call["guidance_scale"] for call in calls], [6.5, 4.0])
        self.assertEqual([call["generator"].seed for call in calls], [42, 99])
        self.assertIsNot(calls[0]["generator"], calls[1]["generator"])

    def test_sdxl_idle_shutdown_releases_worker_and_next_request_restarts(self):
        manager = self.make_sdxl_worker_manager(idle_timeout=0.05)
        try:
            self.run_fake_sdxl(manager)
            first_boot = self.sdxl_worker_log()[-1]["boot_id"]
            deadline = time.monotonic() + 2
            while manager._process is not None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNone(manager._process)
            self.run_fake_sdxl(manager, prompt="After idle")
            self.assertNotEqual(self.sdxl_worker_log()[-1]["boot_id"], first_boot)
        finally:
            manager.close()

    def test_sdxl_worker_crash_is_recoverable(self):
        manager = self.make_sdxl_worker_manager()
        try:
            with self.assertRaisesRegex(RuntimeError, "Worker"):
                self.run_fake_sdxl(manager, behavior="crash")
            self.assertIsNone(manager._process)
            crashed_boot = self.sdxl_worker_log()[-1]["boot_id"]
            self.run_fake_sdxl(manager, prompt="Recovered")
            self.assertNotEqual(self.sdxl_worker_log()[-1]["boot_id"], crashed_boot)
        finally:
            manager.close()

    def test_terminal_image_job_statuses_are_immutable(self):
        terminal_statuses = (
            "completed",
            "failed",
            "cancelled",
        )

        attempted_statuses = (
            "queued",
            "loading",
            "running",
            "saving",
            "completed",
            "failed",
            "cancelled",
        )

        with service._jobs_lock:
            for current_status in terminal_statuses:
                job_id = f"job-{current_status}"

                service._jobs[job_id] = {
                    "id": job_id,
                    "status": current_status,
                    "result": None,
                    "error": None,
                }

                for requested_status in attempted_statuses:
                    applied = service._update_job(
                        job_id,
                        status=requested_status,
                    )

                    job = service._jobs[job_id]

                    if requested_status == current_status:
                        self.assertTrue(
                            applied,
                            (
                                current_status,
                                requested_status,
                            ),
                        )
                        self.assertEqual(
                            job["status"],
                            current_status,
                        )
                    else:
                        self.assertFalse(
                            applied,
                            (
                                current_status,
                                requested_status,
                            ),
                        )
                        self.assertEqual(
                            job["status"],
                            current_status,
                        )

    def test_cancelled_job_ignores_late_progress_callbacks(self):
        job_id = "cancelled-progress-test"

        with service._jobs_lock:
            service._jobs[job_id] = {
                "id": job_id,
                "status": "cancelled",
                "current_step": 3,
                "total_steps": 10,
                "result": None,
                "error": None,
            }

        service._provider_progress(
            job_id,
            {
                "phase": "generate",
                "step": 7,
                "total_steps": 10,
            },
        )

        with service._jobs_lock:
            job = service._jobs[job_id]

            self.assertEqual(
                job["status"],
                "cancelled",
            )
            # A terminal job is frozen completely. Late provider
            # callbacks must not mutate either status or progress.
            self.assertEqual(
                job["current_step"],
                3,
            )
            self.assertEqual(
                job["total_steps"],
                10,
            )

    def test_cancelled_job_cannot_be_completed_after_cancel(self):
        job_id = "cancelled-complete-test"

        with service._jobs_lock:
            service._jobs[job_id] = {
                "id": job_id,
                "status": "cancelled",
                "result": None,
                "error": None,
                "finished_at": 123.0,
            }

        applied = service._update_job(
            job_id,
            status="completed",
            result={"image": "late"},
            finished_at=456.0,
        )

        self.assertFalse(applied)

        with service._jobs_lock:
            job = service._jobs[job_id]

            self.assertEqual(
                job["status"],
                "cancelled",
            )
            self.assertIsNone(
                job["result"],
            )
            self.assertEqual(
                job["finished_at"],
                123.0,
            )

    def test_failed_job_cannot_be_completed_later(self):
        job_id = "failed-complete-test"

        with service._jobs_lock:
            service._jobs[job_id] = {
                "id": job_id,
                "status": "failed",
                "result": None,
                "error": "provider failed",
            }

        applied = service._update_job(
            job_id,
            status="completed",
            result={"image": "late"},
        )

        self.assertFalse(applied)

        with service._jobs_lock:
            job = service._jobs[job_id]

            self.assertEqual(
                job["status"],
                "failed",
            )
            self.assertIsNone(
                job["result"],
            )
            self.assertEqual(
                job["error"],
                "provider failed",
            )


    def test_cancelled_job_stays_cancelled_when_provider_returns_late(self):
        entered_provider = threading.Event()

        def late_generate(
            request,
            *,
            provider_options=None,
            prepared_callback=None,
            saving_callback=None,
        ):
            entered_provider.set()

            cancel_event = provider_options["cancel_event"]

            if not cancel_event.wait(timeout=2):
                raise RuntimeError(
                    "test provider did not receive cancellation"
                )

            # Simulate a provider that still returns a result after the
            # cancellation request was already issued.
            return {
                "ok": True,
                "provider": "test",
            }

        with patch.object(
            service,
            "_generate_result",
            side_effect=late_generate,
        ):
            response = self.client.post(
                "/jobs",
                json={
                    "operation": "generate",
                    "payload": {
                        "prompt": "Cancellation race test",
                        "model": "auto",
                        "width": 512,
                        "height": 512,
                        "steps": 1,
                        "guidance": 1.0,
                        "seed": 1,
                    },
                },
            )

            self.assertEqual(
                response.status_code,
                202,
                response.text,
            )

            job_id = response.json()["id"]

            self.assertTrue(
                entered_provider.wait(timeout=1),
                "provider did not start",
            )

            cancel_response = self.client.post(
                f"/jobs/{job_id}/cancel"
            )

            self.assertEqual(
                cancel_response.status_code,
                200,
                cancel_response.text,
            )

            cancelled = cancel_response.json()

            self.assertEqual(
                cancelled["status"],
                "cancelled",
            )
            self.assertIsNone(
                cancelled["result"],
            )

            # Give any late worker code another chance to run.
            time.sleep(0.05)

            final_response = self.client.get(
                f"/jobs/{job_id}"
            )

            self.assertEqual(
                final_response.status_code,
                200,
                final_response.text,
            )

            final_job = final_response.json()

            self.assertEqual(
                final_job["status"],
                "cancelled",
            )
            self.assertIsNone(
                final_job["result"],
            )


    def test_legacy_chat_defaults_to_revision_zero(self):
        chat = agent.normalize_chat({
            "id": "legacy-chat",
            "title": "Legacy",
            "created": 1,
            "updated": 2,
            "messages": [],
        })

        self.assertIsNotNone(chat)
        self.assertEqual(chat["revision"], 0)

        invalid = agent.normalize_chat({
            "id": "legacy-invalid-revision",
            "title": "Legacy",
            "created": 1,
            "updated": 2,
            "revision": True,
            "messages": [],
        })

        self.assertEqual(invalid["revision"], 0)

    def test_chat_reset_increments_and_persists_revision(self):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": "revision-reset-chat",
            "title": "Before reset",
            "created": 1,
            "updated": 2,
            "revision": 4,
            "messages": [],
        })

        result = agent.reset_chat(
            "revision-reset-chat"
        )

        self.assertEqual(
            result["chat"]["revision"],
            5,
        )

        persisted = agent.read_chat(
            "revision-reset-chat"
        )

        self.assertEqual(
            persisted["revision"],
            5,
        )
        self.assertEqual(
            persisted["messages"],
            [],
        )

    def test_chat_put_cannot_roll_back_server_revision(self):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": "revision-put-chat",
            "title": "Server",
            "created": 1,
            "updated": 100,
            "revision": 7,
            "messages": [],
        })

        request = agent.ChatSessionRequest(
            id="revision-put-chat",
            title="Client",
            created=1,
            updated=200,
            revision=1,
            messages=[],
        )

        result = agent.put_chat(
            "revision-put-chat",
            request,
        )

        self.assertFalse(result["conflict"])
        self.assertEqual(
            result["chat"]["revision"],
            7,
        )

        persisted = agent.read_chat(
            "revision-put-chat"
        )

        self.assertEqual(
            persisted["revision"],
            7,
        )

    def test_image_job_chat_identity_accepts_current_revision(self):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": "image-chat-current",
            "title": "Image",
            "created": 1,
            "updated": 2,
            "revision": 3,
            "messages": [],
        })

        request = agent.ChatActionRequest(
            prompt="Generate an image",
            chat_id="image-chat-current",
            chat_revision=3,
        )

        self.assertEqual(
            agent._validated_image_job_chat_identity(
                request
            ),
            ("image-chat-current", 3),
        )

    def test_image_job_stale_chat_revision_is_rejected(self):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": "image-chat-stale",
            "title": "Image",
            "created": 1,
            "updated": 2,
            "revision": 5,
            "messages": [],
        })

        request = agent.ChatActionRequest(
            prompt="Generate an image",
            chat_id="image-chat-stale",
            chat_revision=4,
        )

        with self.assertRaises(HTTPException) as caught:
            agent._validated_image_job_chat_identity(
                request
            )

        self.assertEqual(
            caught.exception.status_code,
            409,
        )

    def test_start_image_job_forwards_chat_identity(self):
        agent.CHAT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        agent.write_chat({
            "id": "image-chat-forward",
            "title": "Image",
            "created": 1,
            "updated": 2,
            "revision": 8,
            "messages": [],
        })

        request = agent.ChatActionRequest(
            prompt="Generate an image",
            chat_id="image-chat-forward",
            chat_revision=8,
        )

        with (
            patch.object(
                agent,
                "_image_generate_payload",
                return_value={
                    "prompt": "A test image",
                    "model": "test-model",
                },
            ),
            patch.object(
                agent.image_api,
                "request",
                return_value={
                    "id": "a" * 24,
                    "status": "queued",
                },
            ) as image_request,
        ):
            agent._start_chat_image_job(
                "image_generate",
                request,
            )

        call = image_request.call_args

        self.assertEqual(
            call.args[0],
            "POST",
        )
        self.assertEqual(
            call.args[1],
            "/jobs",
        )
        self.assertEqual(
            call.args[2]["chat_id"],
            "image-chat-forward",
        )
        self.assertEqual(
            call.args[2]["chat_revision"],
            8,
        )

    def test_image_job_snapshot_preserves_chat_identity(self):
        snapshot = service._job_snapshot({
            "id": "b" * 24,
            "operation": "generate",
            "chat_id": "snapshot-chat",
            "chat_revision": 12,
            "status": "running",
            "current_step": 1,
            "total_steps": 2,
            "_cancel_event": threading.Event(),
        })

        self.assertEqual(
            snapshot["chat_id"],
            "snapshot-chat",
        )
        self.assertEqual(
            snapshot["chat_revision"],
            12,
        )
        self.assertNotIn(
            "_cancel_event",
            snapshot,
        )

    def test_image_job_get_and_cancel_preserve_chat_identity(self):
        job_id = "c" * 24

        with service._jobs_lock:
            service._jobs[job_id] = {
                "id": job_id,
                "operation": "generate",
                "chat_id": "job-route-chat",
                "chat_revision": 6,
                "status": "running",
                "model": None,
                "current_step": 1,
                "total_steps": 10,
                "result": None,
                "error": None,
                "created_at": 1,
                "started_at": 2,
                "finished_at": None,
                "_cancel_event": threading.Event(),
                "_process": None,
                "_thread": None,
                "_output_path": None,
            }

        get_response = self.client.get(
            f"/jobs/{job_id}"
        )

        self.assertEqual(
            get_response.status_code,
            200,
            get_response.text,
        )
        self.assertEqual(
            get_response.json()["chat_id"],
            "job-route-chat",
        )
        self.assertEqual(
            get_response.json()["chat_revision"],
            6,
        )

        cancel_response = self.client.post(
            f"/jobs/{job_id}/cancel"
        )

        self.assertEqual(
            cancel_response.status_code,
            200,
            cancel_response.text,
        )
        self.assertEqual(
            cancel_response.json()["chat_id"],
            "job-route-chat",
        )
        self.assertEqual(
            cancel_response.json()["chat_revision"],
            6,
        )

    def test_image_unload_stops_sdxl_worker(self):
        with patch.object(
            service,
            "shutdown_sdxl_worker",
        ) as shutdown, patch.object(
            service,
            "sdxl_worker_running",
            return_value=False,
        ):
            response = self.client.post("/unload")

        self.assertEqual(response.status_code, 200, response.text)
        shutdown.assert_called_once_with()

        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["loaded"])
        self.assertFalse(payload["sdxl_worker_loaded"])

    def test_image_unload_reports_shutdown_failure(self):
        with patch.object(
            service,
            "shutdown_sdxl_worker",
            side_effect=RuntimeError("termination failed"),
        ):
            response = self.client.post("/unload")

        self.assertEqual(response.status_code, 500, response.text)
        self.assertNotIn(
            "termination failed",
            response.text,
        )

    def test_sdxl_close_terminates_running_worker(self):
        manager = self.make_sdxl_worker_manager()

        try:
            self.run_fake_sdxl(manager)

            self.assertTrue(manager.is_running())
            process = manager._process
            self.assertIsNotNone(process)

            manager.close()

            self.assertFalse(manager.is_running())
            self.assertIsNone(manager._process)
            self.assertIsNotNone(process.poll())
        finally:
            try:
                manager.close()
            except Exception:
                pass

    def test_sdxl_failed_close_retains_running_state(self):
        manager = self.make_sdxl_worker_manager()

        try:
            self.run_fake_sdxl(manager)

            process = manager._process
            self.assertIsNotNone(process)
            self.assertTrue(manager.is_running())

            with patch.object(
                providers,
                "terminate_process_tree",
                side_effect=RuntimeError("simulated stop failure"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "could not be terminated",
                ):
                    manager.close()

            self.assertIs(manager._process, process)
            self.assertTrue(manager.is_running())

            # After the simulated failure, a real close must still be able
            # to terminate the retained worker.
            manager.close()

            self.assertFalse(manager.is_running())
            self.assertIsNone(manager._process)
        finally:
            try:
                manager.close()
            except Exception:
                pass


    def test_sdxl_worker_cancellation_terminates_and_recovers(self):
        manager = self.make_sdxl_worker_manager()
        cancel_event = threading.Event()
        timer = threading.Timer(0.05, cancel_event.set)
        timer.start()
        try:
            with self.assertRaises(providers.ProviderCancelled):
                manager.generate(
                    self.root / "juggernaut.safetensors",
                    self.root / "config",
                    {
                        "prompt": "Wait",
                        "width": 512,
                        "height": 512,
                        "steps": 1,
                        "guidance": 6.5,
                        "seed": 42,
                        "test_log": str(self.root / "sdxl-worker.jsonl"),
                        "behavior": "wait",
                    },
                    self.root / "output.png",
                    environment=os.environ.copy(),
                    cancel_event=cancel_event,
                )
            self.assertIsNone(manager._process)
            cancelled_boot = self.sdxl_worker_log()[-1]["boot_id"]
            self.run_fake_sdxl(manager, prompt="After cancel")
            self.assertNotEqual(self.sdxl_worker_log()[-1]["boot_id"], cancelled_boot)
        finally:
            timer.cancel()
            manager.close()

    def test_explicit_sdxl_generation_preserves_parameters(self):
        registry.update_model(registry.JUGGERNAUT_XL_ID, {"enabled": True})
        calls = []

        def generate(model, params, output, **_options):
            calls.append((model, params.copy()))
            Image.new("RGB", (512, 512), "white").save(output)

        with patch.object(service, "run_provider", side_effect=generate):
            response = self.client.post(
                "/generate",
                json={
                    "prompt": "Studio portrait",
                    "negative_prompt": "blurry",
                    "model": registry.JUGGERNAUT_XL_ID,
                    "steps": 12,
                    "guidance": 6.5,
                    "seed": 42,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["provider"], "sdxl")
        self.assertEqual(calls[0][0]["id"], registry.JUGGERNAUT_XL_ID)
        self.assertEqual(calls[0][1]["negative_prompt"], "blurry")
        self.assertEqual(calls[0][1]["steps"], 12)
        self.assertEqual(calls[0][1]["guidance"], 6.5)

    def test_agent_automatic_image_dimensions(self):
        self.assertEqual(
            agent._automatic_image_dimensions(
                "Photorealistic full body portrait of a woman"
            ),
            (768, 1024),
        )
        self.assertEqual(
            agent._automatic_image_dimensions(
                "Cinematic mountain landscape"
            ),
            (1024, 768),
        )
        self.assertEqual(
            agent._automatic_image_dimensions(
                "Minimal square app icon"
            ),
            (1024, 1024),
        )
        self.assertEqual(
            agent._automatic_image_dimensions(
                "A red apple"
            ),
            (1024, 1024),
        )

    def test_agent_uses_ai_selected_image_dimensions(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value={
                "prompt": "A cinematic mountain valley at sunset",
                "layout": "wide",
                "width": 1024,
                "height": 768,
            },
        ):
            payload = agent._image_generate_payload(
                agent.ChatActionRequest(
                    prompt="Erstelle ein Bild eines Bergtals bei Sonnenuntergang",
                )
            )

        self.assertEqual(
            payload["prompt"],
            "A cinematic mountain valley at sunset",
        )
        self.assertEqual(payload["width"], 1024)
        self.assertEqual(payload["height"], 768)

    def test_agent_ai_tall_layout(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value={
                "prompt": "Full body fashion portrait of an adult woman",
                "layout": "tall",
                "width": 768,
                "height": 1024,
            },
        ):
            payload = agent._image_generate_payload(
                agent.ChatActionRequest(
                    prompt="Ganzkörper Fashion Portrait einer erwachsenen Frau",
                )
            )

        self.assertEqual(payload["width"], 768)
        self.assertEqual(payload["height"], 1024)

    def test_agent_plain_text_translation_keeps_dimension_fallback(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value="Full body portrait of a woman",
        ):
            payload = agent._image_generate_payload(
                agent.ChatActionRequest(
                    prompt="Ganzkörperporträt einer Frau",
                )
            )

        self.assertEqual(payload["width"], 768)
        self.assertEqual(payload["height"], 1024)

    def test_agent_explicit_image_dimensions_override_auto(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value="Full body portrait of a woman",
        ):
            payload = agent._image_generate_payload(
                agent.ChatActionRequest(
                    prompt="Erstelle ein Ganzkörperporträt",
                    image_options={
                        "width": 896,
                        "height": 1152,
                    },
                )
            )

        self.assertEqual(payload["width"], 896)
        self.assertEqual(payload["height"], 1152)

    def test_image_prompt_router_controls_layout_and_chat_controls_translation(self):
        router_result = (
            '{"prompt":"Kinoreife Aufnahme eines Sportwagens auf einer '
            'Küstenstraße bei Sonnenuntergang","layout":"wide"}'
        )

        with (
            patch.object(
                agent,
                "router_llm",
                return_value=router_result,
            ),
            patch.object(
                agent,
                "_retry_image_prompt_translation",
                return_value=(
                    "Cinematic shot of a sports car "
                    "on a coastal road at sunset"
                ),
            ) as translator,
        ):
            result = agent.translate_image_prompt_to_english(
                "Kinoreife Aufnahme eines Sportwagens "
                "auf einer Küstenstraße bei Sonnenuntergang"
            )

        self.assertEqual(result["layout"], "wide")
        self.assertEqual(result["width"], 1024)
        self.assertEqual(result["height"], 768)
        self.assertEqual(
            result["prompt"],
            "Cinematic shot of a sports car "
            "on a coastal road at sunset",
        )
        translator.assert_called_once()


    def test_image_prompt_accepts_unchanged_english_translation(self):
        source = (
            "Full-body photograph of an adult man "
            "standing on a city street at night"
        )

        router_result = (
            '{"prompt":"Full-body photograph of an adult man '
            'standing on a city street at night","layout":"tall"}'
        )

        with (
            patch.object(
                agent,
                "router_llm",
                return_value=router_result,
            ),
            patch.object(
                agent,
                "_retry_image_prompt_translation",
                return_value=source,
            ),
        ):
            result = agent.translate_image_prompt_to_english(source)

        self.assertEqual(result["prompt"], source)
        self.assertEqual(result["layout"], "tall")
        self.assertEqual(result["width"], 768)
        self.assertEqual(result["height"], 1024)


    def test_agent_forwards_sdxl_negative_prompt_option(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value="A studio portrait",
        ):
            payload = agent._image_generate_payload(
                agent.ChatActionRequest(
                    prompt="Erstelle ein Studioporträt",
                    image_options={"negative_prompt": "blurry"},
                )
            )
        self.assertEqual(payload["negative_prompt"], "blurry")

    def test_auto_generation_uses_capabilities_and_availability(self):
        for model_id in (
            registry.JUGGERNAUT_XL_ID,
            "mflux-qwen-image",
            "mflux-z-image-turbo",
        ):
            registry.update_model(model_id, {"enabled": True})

        with patch.object(service, "availability", return_value=(True, "ready")):
            self.assertEqual(
                service._generation_model(
                    "auto",
                    "A photorealistic studio portrait of a woman",
                )["id"],
                registry.JUGGERNAUT_XL_ID,
            )
            self.assertEqual(
                service._generation_model(
                    "auto",
                    "A realistic person in natural light",
                )["id"],
                registry.JUGGERNAUT_XL_ID,
            )
            self.assertEqual(
                service._generation_model(
                    "auto",
                    "A poster with clear typography and text",
                )["id"],
                "mflux-qwen-image",
            )
            self.assertEqual(
                service._generation_model("auto", "A red apple")["id"],
                "mflux-z-image-turbo",
            )
            self.assertEqual(
                service._generation_model(
                    "mflux-qwen-image",
                    "A photorealistic portrait",
                )["id"],
                "mflux-qwen-image",
            )

        def without_juggernaut(model):
            return (model["id"] != registry.JUGGERNAUT_XL_ID, "test")

        with patch.object(service, "availability", side_effect=without_juggernaut):
            self.assertEqual(
                service._generation_model(
                    "auto",
                    "A photorealistic studio portrait of a woman",
                )["id"],
                "mflux-z-image-turbo",
            )

        def without_qwen(model):
            return (model["id"] != "mflux-qwen-image", "test")

        with patch.object(service, "availability", side_effect=without_qwen):
            self.assertEqual(
                service._generation_model(
                    "auto",
                    "A typography poster with text",
                )["id"],
                "mflux-z-image-turbo",
            )

        def without_turbo(model):
            return (model["id"] != "mflux-z-image-turbo", "test")

        with patch.object(service, "availability", side_effect=without_turbo):
            self.assertEqual(
                service._generation_model("auto", "A generic landscape")["id"],
                registry.LEGACY_ID,
            )

        registry.update_model("mflux-z-image-turbo", {"enabled": False})
        with patch.object(service, "availability", return_value=(True, "ready")):
            self.assertEqual(
                service._generation_model("auto", "A generic landscape")["id"],
                registry.LEGACY_ID,
            )

    def test_agent_preserves_auto_image_role_for_service_routing(self):
        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value="A photorealistic portrait of an adult woman",
        ), patch.object(
            agent,
            "load_model_roles",
            return_value={"image": "auto"},
        ), patch.object(
            agent.image_api,
            "request",
            return_value={"id": "a" * 24, "status": "queued"},
        ) as image_request:
            agent._start_chat_image_job(
                "image_generate",
                self.make_chat_action_request(
                    prompt="Create a photorealistic portrait",
                ),
            )

        self.assertEqual(
            image_request.call_args.args[2]["payload"]["model"],
            "auto",
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

    def test_provider_cancel_terminates_the_process_group(self):
        model = registry.get_model(
            "mflux-qwen-image-edit-2511",
            require_enabled=False,
        )
        cancel_event = threading.Event()
        process = Mock(pid=4321, returncode=None)
        process.poll.return_value = None

        def communicate(**_kwargs):
            cancel_event.set()
            raise subprocess.TimeoutExpired(
                "mflux-generate-qwen-edit",
                providers.PROVIDER_POLL_INTERVAL,
            )

        process.communicate.side_effect = communicate
        process.wait.return_value = -15
        params = {
            "prompt": "Edit the image",
            "source_path": "/uploads/source.png",
            "steps": 8,
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
            providers.subprocess,
            "run",
            return_value=Mock(stdout="0\n"),
        ), patch.object(
            providers.os,
            "killpg",
        ) as killpg:
            with self.assertRaises(providers.ProviderCancelled):
                providers.run_provider(
                    model,
                    params,
                    self.root / "cancelled.png",
                    cancel_event=cancel_event,
                    progress_callback=lambda _event: None,
                )

        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("--json-events", popen.call_args.args[0])
        killpg.assert_called_once_with(4321, providers.signal.SIGTERM)
        process.wait.assert_called_once_with(
            timeout=providers.PROCESS_TERMINATION_TIMEOUT
        )

    def test_provider_runtime_events_report_only_real_step_progress(self):
        events = []
        stream = io.BytesIO(
            b'{"type":"runtime","phase":"progress","step":2,"total_steps":8}\n'
            b'{"type":"runtime","phase":"progress","step":1,"total_steps":5}\n'
            b'provider diagnostic\n'
            b'{"type":"runtime","phase":"save","step":8,"total_steps":8}\n'
        )

        remainder = providers._read_runtime_events(
            stream,
            "",
            events.append,
            8,
        )

        self.assertEqual(remainder, "")
        self.assertEqual(
            events,
            [
                {"phase": "progress", "step": 2, "total_steps": 8},
                {"phase": "progress", "step": None, "total_steps": None},
                {"phase": "save", "step": 8, "total_steps": 8},
            ],
        )

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

    def test_image_job_lifecycle_reports_real_progress_and_completion(self):
        registry.update_model(
            "mflux-qwen-image-edit-2511",
            {"enabled": True},
        )
        service.OUTPUT.mkdir(parents=True)
        source = service.OUTPUT / "source.png"
        Image.new("RGB", (320, 480), "white").save(source)
        started = threading.Event()
        release = threading.Event()

        def provider(_model, params, output, **options):
            options["process_callback"](Mock(pid=4321))
            options["progress_callback"]({
                "phase": "progress",
                "step": 2,
                "total_steps": params["steps"],
            })
            started.set()
            self.assertTrue(release.wait(timeout=2))
            Image.new("RGB", (304, 464), "black").save(output)
            options["progress_callback"]({
                "phase": "save",
                "step": params["steps"],
                "total_steps": params["steps"],
            })
            options["process_callback"](None)

        with patch.object(service, "run_provider", side_effect=provider):
            created = self.client.post(
                "/jobs",
                json={
                    "operation": "edit",
                    "payload": {
                        "prompt": "Darken the background",
                        "source_path": str(source),
                        "model": "mflux-qwen-image-edit-2511",
                        "seed": 17,
                    },
                },
            )
            self.assertEqual(created.status_code, 202, created.text)
            job_id = created.json()["id"]
            self.assertEqual(created.json()["status"], "queued")
            self.assertTrue(started.wait(timeout=2))

            running = self.client.get(f"/jobs/{job_id}").json()
            self.assertEqual(running["status"], "running")
            self.assertEqual(running["current_step"], 2)
            self.assertEqual(running["total_steps"], 8)
            self.assertEqual(running["progress"], 0.25)
            self.assertEqual(self.client.get("/health").json()["status"], "busy")

            busy = self.client.post(
                "/jobs",
                json={
                    "operation": "generate",
                    "payload": {"prompt": "A red apple"},
                },
            )
            self.assertEqual(busy.status_code, 409)

            release.set()
            completed = self.wait_for_image_job(job_id, {"completed"})

        self.assertEqual(completed["operation"], "edit")
        self.assertEqual(completed["current_step"], 8)
        self.assertEqual(completed["result"]["steps"], 8)
        self.assertTrue(Path(completed["result"]["path"]).is_file())
        self.assertEqual(self.client.get("/health").json()["status"], "ready")

    def test_image_job_failure_has_no_result_or_partial_artifact(self):
        output_paths = []

        def provider(_model, _params, output, **_options):
            output_paths.append(output)
            output.write_bytes(b"partial")
            raise RuntimeError("Provider failed")

        with patch.object(service, "run_provider", side_effect=provider):
            created = self.client.post(
                "/jobs",
                json={
                    "operation": "generate",
                    "payload": {"prompt": "A red apple"},
                },
            )
            failed = self.wait_for_image_job(
                created.json()["id"],
                {"failed"},
            )

        self.assertEqual(failed["error"], "Provider failed")
        self.assertIsNone(failed["result"])
        self.assertFalse(output_paths[0].exists())
        self.assertEqual(self.client.get("/health").json()["status"], "ready")

    def test_image_job_cancel_cleans_output_and_allows_the_next_job(self):
        registry.update_model(
            "mflux-qwen-image-edit-2511",
            {"enabled": True},
        )
        service.OUTPUT.mkdir(parents=True)
        source = service.OUTPUT / "source.png"
        Image.new("RGB", (320, 480), "white").save(source)
        started = threading.Event()
        output_paths = []
        process = Mock(pid=4321)

        def cancellable(_model, _params, output, **options):
            output_paths.append(output)
            output.write_bytes(b"partial")
            options["process_callback"](process)
            started.set()
            self.assertTrue(options["cancel_event"].wait(timeout=2))
            options["process_callback"](None)
            raise providers.ProviderCancelled("cancelled")

        with patch.object(
            service,
            "run_provider",
            side_effect=cancellable,
        ), patch.object(
            service,
            "terminate_process_tree",
        ) as terminate:
            created = self.client.post(
                "/jobs",
                json={
                    "operation": "edit",
                    "payload": {
                        "prompt": "Darken the background",
                        "source_path": str(source),
                        "model": "mflux-qwen-image-edit-2511",
                    },
                },
            )
            job_id = created.json()["id"]
            self.assertTrue(started.wait(timeout=2))
            cancelled_response = self.client.post(f"/jobs/{job_id}/cancel")

        self.assertEqual(cancelled_response.status_code, 200)
        cancelled = cancelled_response.json()
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled["result"])
        terminate.assert_called_once_with(process)
        self.assertFalse(output_paths[0].exists())
        self.assertEqual(self.client.get("/health").json()["status"], "ready")

        def successful(_model, params, output, **_options):
            Image.new(
                "RGB",
                (params["width"], params["height"]),
                "red",
            ).save(output)

        with patch.object(service, "run_provider", side_effect=successful):
            next_job = self.client.post(
                "/jobs",
                json={
                    "operation": "generate",
                    "payload": {"prompt": "A red apple"},
                },
            )
            completed = self.wait_for_image_job(
                next_job.json()["id"],
                {"completed"},
            )
        self.assertIsNotNone(completed["result"])

    def test_image_followup_shorthand_routes_to_edit(self):
        for prompt in (
            "bitte ganzkörper",
            "ganzkörper",
            "mehr ganzkörper",
            "weiter raus",
            "noch realistischer",
            "full body",
            "zoom out",
        ):
            self.assertTrue(
                agent._looks_like_image_edit_request(prompt),
                prompt,
            )

        self.assertFalse(
            agent._looks_like_image_edit_request(
                "Was ist ein Ganzkörperfoto?"
            )
        )

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
        request = self.make_chat_action_request(
            prompt="Mach den Hintergrund dunkel",
            file_context=image_context,
            image_options={"steps": 4},
            trace_id="image-edit-test",
        )

        job_id = "a" * 24
        queued_job = {
            "id": job_id,
            "operation": "edit",
            "status": "queued",
            "current_step": None,
            "total_steps": None,
            "progress": None,
            "result": None,
            "error": None,
        }
        completed_job = {
            **queued_job,
            "status": "completed",
            "current_step": 4,
            "total_steps": 4,
            "progress": 1.0,
            "result": provider_result,
        }

        with patch.object(
            agent,
            "optimize_image_edit_prompt",
            return_value=request.prompt,
        ), patch.object(
            agent.image_api,
            "request",
            side_effect=[queued_job, completed_job],
        ) as image_request:
            queued = agent.run_chat_action(request)
            result = agent.image_job_api(job_id)

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["data"]["job"]["id"], job_id)
        self.assertEqual(queued["artifacts"], [])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool"], "image_edit")
        self.assertEqual(
            result["artifacts"][0]["artifact_id"],
            f"image-{image_id}",
        )
        self.assertEqual(
            image_request.call_args_list[0].args[1],
            "/jobs",
        )
        self.assertEqual(
            image_request.call_args_list[0].args[2]["operation"],
            "edit",
        )
        self.assertEqual(
            image_request.call_args_list[0].args[2]["payload"]["source_path"],
            str(source),
        )
        self.assertEqual(
            image_request.call_args_list[0].args[2]["payload"]["steps"],
            4,
        )
        self.assertEqual(
            image_request.call_args_list[1].args[1],
            f"/jobs/{job_id}",
        )

    def test_image_upscale_job_uses_uploaded_source_and_runtime_options(self):
        source = self.root / "uploaded.png"
        Image.new("RGB", (32, 24), "green").save(source)
        request = self.make_chat_action_request(
            prompt="Upscale this image four times.",
            action="image_upscale",
            file_context={
                "kind": "image",
                "mime_type": "image/png",
                "stored_path": str(source),
            },
            image_options={
                "preset": "anime-4x",
                "scale": 4,
                "tile": 256,
            },
        )
        queued_job = {
            "id": "d" * 24,
            "operation": "upscale",
            "status": "queued",
        }
        with patch.object(
            agent,
            "classify_chat_action_details",
            side_effect=AssertionError(
                "Explicit upscale must not invoke semantic routing"
            ),
        ), patch.object(
            agent,
            "load_model_roles",
            side_effect=AssertionError(
                "Upscale must not resolve a generative image model"
            ),
        ), patch.object(
            agent.image_api,
            "request",
            return_value=queued_job,
        ) as image_request:
            result = agent.run_chat_action(request)

        self.assertEqual(result["tool"], "image_upscale")
        self.assertEqual(result["status"], "queued")
        image_request.assert_called_once_with(
            "POST",
            "/jobs",
            {
                "operation": "upscale",
                "payload": {
                    "source_path": str(source),
                    "preset": "anime-4x",
                    "tile": 256,
                },
                "chat_id": "test-image-chat",
                "chat_revision": 0,
            },
            timeout=10,
        )
        self.assertNotIn(
            "model",
            image_request.call_args.args[2]["payload"],
        )

    def test_image_upscale_resolves_active_artifact_and_scale_alias(self):
        image_directory = agent.IMAGE_DIRECTORY
        image_directory.mkdir(parents=True)
        image_id = "1234567890-cccccccccccc"
        source = image_directory / f"{image_id}.png"
        Image.new("RGB", (24, 16), "blue").save(source)

        payload = agent._image_upscale_payload(
            agent.ChatActionRequest(
                prompt="Upscale this image.",
                active_artifact_id=f"image-{image_id}",
                image_options={"scale": 2},
            )
        )

        self.assertEqual(payload, {
            "source_path": str(source.resolve()),
            "preset": "photo-2x",
        })

    def test_completed_image_upscale_job_returns_metadata_artifact(self):
        image_id = "1234567890-dddddddddddd"
        source = self.root / "source.png"
        result = agent._image_job_tool_result({
            "id": "e" * 24,
            "operation": "upscale",
            "status": "completed",
            "result": {
                "id": image_id,
                "path": str(agent.IMAGE_DIRECTORY / f"{image_id}.png"),
                "source_path": str(source),
                "source_width": 320,
                "source_height": 240,
                "width": 640,
                "height": 480,
                "scale": 2,
                "preset": "photo-2x",
                "tile": 0,
                "model": "realesrgan-x4plus",
                "provider": "realesrgan",
                "model_family": "realesrgan",
            },
            "error": None,
        })

        self.assertEqual(result["tool"], "image_upscale")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["artifacts"]), 1)
        artifact = result["artifacts"][0]
        self.assertEqual(artifact["artifact_id"], f"image-{image_id}")
        for field in (
            "source_path",
            "source_width",
            "source_height",
            "width",
            "height",
            "scale",
            "preset",
            "tile",
            "provider",
            "model",
            "model_family",
        ):
            self.assertEqual(
                artifact[field],
                result["data"]["job"]["result"][field],
            )

    def test_image_upscale_rejects_missing_source_and_invalid_options(self):
        with self.assertRaises(HTTPException) as missing:
            agent._image_upscale_payload(
                agent.ChatActionRequest(
                    prompt="Upscale this image.",
                    image_options={"scale": 2},
                )
            )
        self.assertEqual(missing.exception.status_code, 404)

        source = self.root / "uploaded.png"
        Image.new("RGB", (16, 16), "white").save(source)
        context = {
            "kind": "image",
            "mime_type": "image/png",
            "stored_path": str(source),
        }
        for options in (
            {"steps": 8},
            {"scale": 3},
            {"preset": "photo-2x", "scale": 4},
        ):
            with self.subTest(options=options), self.assertRaises(
                HTTPException
            ) as invalid:
                agent._image_upscale_payload(
                    agent.ChatActionRequest(
                        prompt="Upscale this image.",
                        file_context=context,
                        image_options=options,
                    )
                )
            self.assertEqual(invalid.exception.status_code, 422)

    def test_image_job_dispatch_preserves_generate_and_edit_behavior(self):
        source = self.root / "source.png"
        Image.new("RGB", (16, 16), "white").save(source)
        queued_job = {
            "id": "f" * 24,
            "status": "queued",
        }

        with patch.object(
            agent,
            "translate_image_prompt_to_english",
            return_value="A red apple",
        ), patch.object(
            agent,
            "optimize_image_edit_prompt",
            return_value="Darken the background",
        ), patch.object(
            agent,
            "load_model_roles",
            return_value={"image": "FLUX.1-schnell"},
        ), patch.object(
            agent.image_api,
            "request",
            return_value=queued_job,
        ) as image_request:
            agent._start_chat_image_job(
                "image_generate",
                self.make_chat_action_request(
                    prompt="Erstelle ein Bild von einem roten Apfel",
                ),
            )
            agent._start_chat_image_job(
                "image_edit",
                self.make_chat_action_request(
                    prompt="Mach den Hintergrund dunkler",
                    file_context={
                        "stored_path": str(source),
                    },
                    image_options={"steps": 12},
                ),
            )

        generate_call, edit_call = image_request.call_args_list
        self.assertEqual(generate_call.args[2]["operation"], "generate")
        self.assertEqual(
            generate_call.args[2]["payload"]["model"],
            "FLUX.1-schnell",
        )
        self.assertEqual(edit_call.args[2]["operation"], "edit")
        self.assertEqual(
            edit_call.args[2]["payload"]["model"],
            "mflux-qwen-image-edit-2511",
        )
        self.assertEqual(edit_call.args[2]["payload"]["steps"], 12)

    def test_active_image_artifact_resolution_and_edit_chaining(self):
        image_directory = agent.IMAGE_DIRECTORY
        image_directory.mkdir(parents=True)
        image_a = "1234567890-aaaaaaaaaaaa"
        image_b = "1234567891-bbbbbbbbbbbb"
        for image_id, color in ((image_a, "red"), (image_b, "blue")):
            Image.new("RGB", (32, 32), color).save(
                image_directory / f"{image_id}.png"
            )

        first_followup = agent.ChatActionRequest(
            prompt="Mach es noch dunkler.",
            active_artifact_id=f"image-{image_a}",
        )
        second_followup = agent.ChatActionRequest(
            prompt="Mach das Bild etwas wärmer.",
            active_artifact_id=f"image-{image_b}",
        )

        with patch.object(
            agent,
            "optimize_image_edit_prompt",
            side_effect=lambda prompt: prompt,
        ):
            self.assertEqual(
                agent._image_edit_payload(first_followup)["source_path"],
                str((image_directory / f"{image_a}.png").resolve()),
            )
            self.assertEqual(
                agent._image_edit_payload(second_followup)["source_path"],
                str((image_directory / f"{image_b}.png").resolve()),
            )
        self.assertTrue(
            agent._looks_like_image_edit_request(
                "Und jetzt etwas wärmer."
            )
        )

    def test_uploaded_image_takes_priority_over_active_artifact(self):
        image_directory = agent.IMAGE_DIRECTORY
        image_directory.mkdir(parents=True)
        image_id = "1234567890-aaaaaaaaaaaa"
        Image.new("RGB", (32, 32), "red").save(
            image_directory / f"{image_id}.png"
        )
        upload = self.root / "uploaded.png"
        Image.new("RGB", (32, 32), "green").save(upload)
        request = agent.ChatActionRequest(
            prompt="Mach das Bild dunkler.",
            file_context={
                "kind": "image",
                "mime_type": "image/png",
                "stored_path": str(upload),
            },
            active_artifact_id=f"image-{image_id}",
        )

        with patch.object(
            agent,
            "optimize_image_edit_prompt",
            return_value=request.prompt,
        ):
            self.assertEqual(
                agent._image_edit_payload(request)["source_path"],
                str(upload),
            )

    def test_active_image_artifact_validation(self):
        image_directory = agent.IMAGE_DIRECTORY
        image_directory.mkdir(parents=True)
        missing_id = "1234567890-aaaaaaaaaaaa"
        corrupt_id = "1234567891-bbbbbbbbbbbb"
        (image_directory / f"{corrupt_id}.png").write_text(
            "not an image",
            encoding="utf-8",
        )

        invalid_ids = (
            "file-1234567890-aaaaaaaaaaaa",
            "image-../../private",
            "image-1234567890-aaaaaaaaaaaa/../secret",
        )
        for artifact_id in invalid_ids:
            with self.subTest(artifact_id=artifact_id), self.assertRaises(
                HTTPException
            ) as raised:
                agent._resolve_image_artifact_source(artifact_id)
            self.assertEqual(raised.exception.status_code, 422)

        with self.assertRaises(HTTPException) as missing:
            agent._resolve_image_artifact_source(f"image-{missing_id}")
        self.assertEqual(missing.exception.status_code, 404)

        with self.assertRaises(HTTPException) as corrupt:
            agent._resolve_image_artifact_source(f"image-{corrupt_id}")
        self.assertEqual(corrupt.exception.status_code, 422)

    def test_active_image_routes_followup_without_affecting_plain_chat(self):
        image_directory = agent.IMAGE_DIRECTORY
        image_directory.mkdir(parents=True)
        image_id = "1234567890-aaaaaaaaaaaa"
        Image.new("RGB", (32, 32), "red").save(
            image_directory / f"{image_id}.png"
        )
        queued_job = {
            "id": "c" * 24,
            "operation": "edit",
            "status": "queued",
        }
        request = self.make_chat_action_request(
            prompt="Mach es noch dunkler.",
            active_artifact_id=f"image-{image_id}",
        )

        with patch.object(
            agent,
            "optimize_image_edit_prompt",
            return_value=request.prompt,
        ), patch.object(
            agent.image_api,
            "request",
            return_value=queued_job,
        ) as image_request:
            result = agent.run_chat_action(request)

        self.assertEqual(result["tool"], "image_edit")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(
            image_request.call_args.args[2]["payload"]["source_path"],
            str((image_directory / f"{image_id}.png").resolve()),
        )

        with patch.object(
            agent,
            "semantic_intent_classifier",
            return_value={
                "intent": "normal_chat",
                "confidence": 0.99,
                "requires_tools": False,
                "reason": "general question",
            },
        ):
            without_image = agent.run_chat_action(
                self.make_chat_action_request(prompt="Mach es noch dunkler.")
            )
            docker = agent.run_chat_action(
                self.make_chat_action_request(
                    prompt="Wie funktioniert Docker?",
                    active_artifact_id=f"image-{image_id}",
                )
            )

        self.assertNotEqual(without_image["tool"], "image_edit")
        self.assertEqual(docker["tool"], "normal_chat")

    def test_active_artifact_workspace_is_persisted_per_chat(self):
        artifact_id = "image-1234567890-aaaaaaaaaaaa"
        first = agent.ChatSessionRequest(
            id="first-chat",
            title="First",
            created=1,
            updated=2,
            messages=[],
            workspace={"active_artifact_id": artifact_id},
        )
        second = agent.ChatSessionRequest(
            id="second-chat",
            title="Second",
            created=1,
            updated=2,
            messages=[],
        )

        agent.put_chat("first-chat", first)
        agent.put_chat("second-chat", second)

        self.assertEqual(
            agent.read_chat("first-chat")["workspace"][
                "active_artifact_id"
            ],
            artifact_id,
        )
        self.assertNotIn("workspace", agent.read_chat("second-chat"))

    def test_completed_image_generate_job_returns_an_artifact(self):
        image_id = "1234567890-fedcba654321"
        result = agent._image_job_tool_result({
            "id": "b" * 24,
            "operation": "generate",
            "status": "completed",
            "result": {
                "id": image_id,
                "path": str(agent.IMAGE_DIRECTORY / f"{image_id}.png"),
                "width": 512,
                "height": 512,
                "prompt": "A red apple",
                "model": "FLUX.1-schnell",
                "provider": "diffusionkit",
                "steps": 4,
                "seed": 17,
            },
            "error": None,
        })

        self.assertEqual(result["tool"], "image_generate")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["artifacts"][0]["artifact_id"],
            f"image-{image_id}",
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

def test_hierarchical_router_escalates_only_when_needed(monkeypatch):
    from agent import app as agent_app

    calls = {
        "manager": 0,
    }

    def manager(
        prompt,
        small_router_result,
        trigger_reasons,
        file_context=None,
        conversation_context=None,
    ):
        calls["manager"] += 1

        mapping = {
            "Mach den Button im Frontend größer": "coding_agent",
            "Warum reagiert mein Docker Container nicht?": "diagnostic_agent",
            "Vergleiche mehrere aktuelle Quellen zu Qwen und Gemma": "research_agent",
            "Prüfe mein Projekt und recherchiere online, wie man den gefundenen Fehler am besten behebt": "orchestrator",
        }

        intent = mapping[prompt]

        return {
            "intent": intent,
            "confidence": 0.95,
            "requires_tools": True,
            "reason": "manager test route",
        }

    def classifier(prompt, *_args):
        responses = {
            "Warum ist der Himmel blau?": {
                "intent": "normal_chat",
                "confidence": 0.90,
                "requires_tools": False,
                "reason": "general knowledge",
            },
            "Mach den Button im Frontend größer": {
                "intent": "",
                "confidence": 0.0,
                "requires_tools": False,
                "reason": "invalid json",
            },
            "Warum reagiert mein Docker Container nicht?": {
                "intent": "coding_agent",
                "confidence": 0.90,
                "requires_tools": True,
                "reason": "wrong small-router route",
            },
            "Vergleiche mehrere aktuelle Quellen zu Qwen und Gemma": {
                "intent": "web_search",
                "confidence": 0.90,
                "requires_tools": False,
                "reason": "wrong tool flag",
            },
            "Prüfe mein Projekt und recherchiere online, wie man den gefundenen Fehler am besten behebt": {
                "intent": "web_search",
                "confidence": 0.90,
                "requires_tools": False,
                "reason": "cross capability missed",
            },
        }

        return responses[prompt]

    normal = agent_app.classify_chat_action_details(
        "Warum ist der Himmel blau?",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert normal["intent"] == "normal_chat"
    assert normal["method"] == "semantic_llm"
    assert calls["manager"] == 0

    coding = agent_app.classify_chat_action_details(
        "Mach den Button im Frontend größer",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert coding["intent"] == "coding_agent"
    assert coding["method"] == "semantic_manager"
    assert "coding_conflict" in coding["manager_trigger_reasons"]

    diagnostic = agent_app.classify_chat_action_details(
        "Warum reagiert mein Docker Container nicht?",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert diagnostic["intent"] == "diagnostic_agent"
    assert diagnostic["method"] == "semantic_manager"
    assert "diagnostic_conflict" in diagnostic["manager_trigger_reasons"]

    research = agent_app.classify_chat_action_details(
        "Vergleiche mehrere aktuelle Quellen zu Qwen und Gemma",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert research["intent"] == "research_agent"
    assert research["method"] == "semantic_manager"
    assert "research_conflict" in research["manager_trigger_reasons"]

    orchestrator = agent_app.classify_chat_action_details(
        "Prüfe mein Projekt und recherchiere online, wie man den gefundenen Fehler am besten behebt",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert orchestrator["intent"] == "orchestrator"
    assert orchestrator["method"] == "semantic_manager"
    assert "cross_capability_conflict" in orchestrator["manager_trigger_reasons"]

    assert calls["manager"] == 4

def test_hierarchical_router_keeps_creative_chat_on_normal_chat():
    from agent import app as agent_app

    def classifier(_prompt, *_args):
        return {
            "intent": "normal_chat",
            "confidence": 0.90,
            "requires_tools": False,
            "reason": "creative chat",
        }

    def manager(*_args, **_kwargs):
        raise AssertionError("manager must not run")

    result = agent_app.classify_chat_action_details(
        "Du agierst als Spielleiter und Rollenspiel-Partner. "
        "Beginne direkt mit der ersten Szene.",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert result["intent"] == "normal_chat"
    assert result["method"] == "semantic_llm"
    assert result["manager_trigger_reasons"] == []

def test_hierarchical_router_manager_failure_uses_safe_fallback():
    from agent import app as agent_app

    def classifier(_prompt, *_args):
        return {
            "intent": "",
            "confidence": 0.0,
            "requires_tools": False,
            "reason": "broken small router",
        }

    def manager(*_args, **_kwargs):
        raise RuntimeError("manager unavailable")

    result = agent_app.classify_chat_action_details(
        "Mach den Button im Frontend größer",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert result["intent"] in {
        "coding_agent",
        "normal_chat",
    }
    assert result["method"] == "safe_fallback"
    assert result["manager_error"] == "manager unavailable"

def test_hierarchical_router_rejects_low_confidence_manager_agent():
    from agent import app as agent_app

    def classifier(_prompt, *_args):
        return {
            "intent": "",
            "confidence": 0.0,
            "requires_tools": False,
            "reason": "small router failed",
        }

    def manager(*_args, **_kwargs):
        return {
            "intent": "research_agent",
            "confidence": 0.40,
            "requires_tools": True,
            "reason": "uncertain",
        }

    result = agent_app.classify_chat_action_details(
        "Vergleiche mehrere aktuelle Quellen zu Qwen und Gemma",
        classifier=classifier,
        manager_classifier=manager,
    )

    assert result["method"] == "safe_fallback"
    assert result["intent"] != "research_agent"


def test_long_roleplay_prompt_does_not_route_to_web_search():
    from agent import app as agent_app

    prompt = """Nimm die Rolle einer weiblichen Hauptfigur und gleichzeitig
des Spielleiters für ein Erwachsenen-Rollenspiel ein.

Sprich immer aus der Ich-Perspektive als die Frau im Szenario.

Erstelle zum Start ein komplett zufälliges Szenario.
Erfinde deine Figur, Persönlichkeit und Beziehung zu mir.

Wähle einen zufälligen Ort und Zeitpunkt, zum Beispiel ein spätes
Büro-Meeting, eine verregnete Nacht, ein verlassenes Hotel oder
eine Party im Hinterzimmer.

Baue spontan unvorhersehbare Ereignisse ein, zum Beispiel Geräusche,
jemand klopft, einen Stromausfall oder einen Stimmungswechsel.

Starte jetzt direkt mit dem zufälligen Szenario."""

    assert agent_app._looks_like_creative_chat_request(
        prompt
    )

    assert not agent_app._looks_like_external_information_request(
        prompt
    )

    # This is the regression that previously failed:
    # deterministic routing must not force web_search.
    assert agent_app._direct_chat_action(
        prompt
    ) is None

    manager_calls = []

    def classifier(_prompt, *_args):
        return {
            "intent": "normal_chat",
            "confidence": 0.95,
            "requires_tools": False,
            "reason": "creative roleplay",
        }

    def manager(*args, **kwargs):
        manager_calls.append((args, kwargs))
        raise AssertionError(
            "Manager must not run for a clear creative-chat route"
        )

    result = agent_app.classify_chat_action_details(
        prompt,
        classifier=classifier,
        manager_classifier=manager,
    )

    assert result["intent"] == "normal_chat"
    assert result["method"] == "semantic_llm"
    assert result["requires_tools"] is False
    assert manager_calls == []


def test_creative_prompt_can_still_request_external_research():
    from agent import app as agent_app

    prompt = (
        "Schreibe ein Rollenspiel, aber recherchiere zuerst "
        "im Web die aktuellen Nachrichten aus Berlin."
    )

    assert agent_app._looks_like_creative_chat_request(
        prompt
    )

    assert agent_app._looks_like_external_information_request(
        prompt
    )


def test_qwen_image_edit_command_includes_enabled_loras(tmp_path, monkeypatch):
    from image_providers import mflux_command

    model_dir = tmp_path / "model"
    model_dir.mkdir()

    lora_a = tmp_path / "a.safetensors"
    lora_b = tmp_path / "b.safetensors"

    lora_a.write_bytes(b"x")
    lora_b.write_bytes(b"y")

    model = {
        "model_family": "qwen-image-edit",
        "loras": [
            {
                "path": str(lora_a),
                "repository": None,
                "scale": 0.7,
                "enabled": True,
            },
            {
                "path": str(lora_b),
                "repository": None,
                "scale": 1.2,
                "enabled": True,
            },
            {
                "path": str(tmp_path / "disabled.safetensors"),
                "repository": None,
                "scale": 1.0,
                "enabled": False,
            },
        ],
    }

    monkeypatch.setattr(
        "image_providers.model_directory",
        lambda _model: model_dir,
    )

    params = {
        "source_path": "/tmp/source.png",
        "prompt": "test edit",
        "steps": 8,
        "guidance": 3.5,
        "seed": 123,
    }

    command = mflux_command(
        model,
        params,
        tmp_path / "output.png",
    )

    assert "--lora-paths" in command
    assert "--lora-scales" in command

    paths_index = command.index("--lora-paths")
    scales_index = command.index("--lora-scales")

    assert command[paths_index + 1:scales_index] == [
        str(lora_a),
        str(lora_b),
    ]

    assert command[scales_index + 1:] == [
        "0.7",
        "1.2",
    ]


def test_qwen_image_edit_command_omits_disabled_loras(tmp_path, monkeypatch):
    from image_providers import mflux_command

    model_dir = tmp_path / "model"
    model_dir.mkdir()

    model = {
        "model_family": "qwen-image-edit",
        "loras": [
            {
                "path": str(tmp_path / "disabled.safetensors"),
                "repository": None,
                "scale": 1.0,
                "enabled": False,
            },
        ],
    }

    monkeypatch.setattr(
        "image_providers.model_directory",
        lambda _model: model_dir,
    )

    params = {
        "source_path": "/tmp/source.png",
        "prompt": "test edit",
        "steps": 8,
        "guidance": 3.5,
        "seed": 123,
    }

    command = mflux_command(
        model,
        params,
        tmp_path / "output.png",
    )

    assert "--lora-paths" not in command
    assert "--lora-scales" not in command


def test_qwen_image_edit_capabilities_include_lora():
    from image_registry import ImageModel

    model = ImageModel(
        id="test-qwen-edit",
        name="Test Qwen Edit",
        provider="mflux",
        repository="example/example",
        model_family="qwen-image-edit",
        base_model="qwen-image-edit-2511",
        quantization="q4",
    )

    assert "image_edit" in model.capabilities
    assert "lora" in model.capabilities
    assert "multi_lora" in model.capabilities


def test_qwen_image_edit_command_uses_registry_quantization(
    tmp_path,
    monkeypatch,
):
    from image_providers import mflux_command

    model_dir = tmp_path / "model"
    model_dir.mkdir()

    model = {
        "model_family": "qwen-image-edit",
        "quantization": "q8",
        "quantize_on_load": True,
        "loras": [],
    }

    monkeypatch.setattr(
        "image_providers.model_directory",
        lambda _model: model_dir,
    )

    command = mflux_command(
        model,
        {
            "source_path": "/tmp/source.png",
            "prompt": "test edit",
            "steps": 8,
            "guidance": 3.5,
            "seed": 123,
        },
        tmp_path / "output.png",
    )

    index = command.index("--quantize")

    assert command[index + 1] == "8"


def test_validate_lora_path_preserves_huggingface_snapshot_symlink(
    tmp_path,
    monkeypatch,
):
    import image_registry

    cache = tmp_path / "hub"
    blobs = cache / "models--test--lora" / "blobs"
    snapshot = (
        cache
        / "models--test--lora"
        / "snapshots"
        / "revision"
    )

    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)

    blob = blobs / "abcdef123456"
    blob.write_bytes(b"test")

    link = snapshot / "adapter.safetensors"
    link.symlink_to(Path("../../blobs") / blob.name)

    monkeypatch.setattr(
        image_registry,
        "MODEL_ROOTS",
        [cache],
    )

    result = image_registry.validate_path(
        str(link),
        file=True,
    )

    assert result == str(link)
    assert Path(result).suffix == ".safetensors"
    assert Path(result).resolve() == blob.resolve()


def test_realesrgan_photo_2x_command(tmp_path, monkeypatch):
    import image_providers as providers

    binary = tmp_path / "realesrgan-ncnn-vulkan"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    models = tmp_path / "models"
    models.mkdir()

    for suffix in (".param", ".bin"):
        (
            models / f"realesrgan-x4plus{suffix}"
        ).write_bytes(b"model")

    monkeypatch.setattr(
        providers,
        "REALESRGAN_BIN",
        binary,
    )
    monkeypatch.setattr(
        providers,
        "REALESRGAN_MODELS",
        models,
    )

    source = tmp_path / "source.png"
    output = tmp_path / "output.png"

    command = providers.realesrgan_command(
        source,
        output,
        preset="photo-2x",
    )

    assert command == [
        str(binary),
        "-i",
        str(source),
        "-o",
        str(output),
        "-m",
        str(models),
        "-n",
        "realesrgan-x4plus",
        "-s",
        "2",
        "-t",
        "0",
        "-f",
        "png",
        "-v",
    ]


def test_realesrgan_anime_4x_command(tmp_path, monkeypatch):
    import image_providers as providers

    binary = tmp_path / "realesrgan-ncnn-vulkan"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    models = tmp_path / "models"
    models.mkdir()

    for suffix in (".param", ".bin"):
        (
            models / f"realesrgan-x4plus-anime{suffix}"
        ).write_bytes(b"model")

    monkeypatch.setattr(
        providers,
        "REALESRGAN_BIN",
        binary,
    )
    monkeypatch.setattr(
        providers,
        "REALESRGAN_MODELS",
        models,
    )

    command = providers.realesrgan_command(
        tmp_path / "source.png",
        tmp_path / "output.png",
        preset="anime-4x",
        tile=256,
    )

    assert command[
        command.index("-n") + 1
    ] == "realesrgan-x4plus-anime"

    assert command[
        command.index("-s") + 1
    ] == "4"

    assert command[
        command.index("-t") + 1
    ] == "256"


def test_realesrgan_rejects_unknown_preset():
    import image_providers as providers
    import pytest

    with pytest.raises(
        ValueError,
        match="Unbekanntes Real-ESRGAN-Preset",
    ):
        providers.realesrgan_command(
            "/tmp/source.png",
            "/tmp/output.png",
            preset="potato-16x",
        )


def test_image_upscale_endpoint_returns_png_metadata(
    tmp_path,
    monkeypatch,
):
    import image_service as service

    monkeypatch.setattr(service, "OUTPUT", tmp_path / "images")
    service.OUTPUT.mkdir(parents=True, exist_ok=True)

    source = service.OUTPUT / "upscale-source.png"

    from PIL import Image

    Image.new(
        "RGB",
        (320, 240),
        "white",
    ).save(source)

    def fake_command(
        source_path,
        output_path,
        *,
        preset,
        tile,
    ):
        assert Path(source_path) == source
        assert preset == "photo-2x"
        assert tile == 0

        return [
            "fake-realesrgan",
            str(source_path),
            str(output_path),
        ]

    class FakeStdout:
        def __init__(self):
            self.lines = iter([
                "0.00%\n",
                "50.00%\n",
                "100.00%\n",
            ])

        def readline(self):
            return next(self.lines, "")

        def read(self):
            return ""

    class FakeProcess:
        def __init__(self, command):
            self.command = command
            self.stdout = FakeStdout()
            self.returncode = None
            self.pid = 12345
            self._polls = 0

            output = Path(command[-1])

            Image.new(
                "RGB",
                (640, 480),
                "white",
            ).save(output)

        def poll(self):
            self._polls += 1

            if self._polls >= 3:
                self.returncode = 0

            return self.returncode

    def fake_popen(
        command,
        stdout,
        stderr,
        text,
        bufsize,
        start_new_session,
    ):
        assert stdout == service.subprocess.PIPE
        assert stderr == service.subprocess.STDOUT
        assert text is True
        assert bufsize == 1
        assert start_new_session is True

        return FakeProcess(command)

    monkeypatch.setattr(
        service,
        "realesrgan_command",
        fake_command,
    )

    monkeypatch.setattr(
        service.subprocess,
        "Popen",
        fake_popen,
    )

    monkeypatch.setattr(
        service,
        "terminate_process_tree",
        lambda process: None,
    )

    result = service._upscale_result(
        service.Upscale(
            source_path=str(source),
            preset="photo-2x",
        )
    )

    assert result["width"] == 640
    assert result["height"] == 480
    assert result["source_width"] == 320
    assert result["source_height"] == 240
    assert result["scale"] == 2
    assert result["preset"] == "photo-2x"
    assert result["provider"] == "realesrgan"
    assert Path(result["path"]).is_file()


def test_image_job_create_accepts_upscale():
    import image_service as service

    job = service.ImageJobCreate(
        operation="upscale",
        payload={
            "source_path": "/tmp/source.png",
            "preset": "photo-2x",
        },
    )

    assert job.operation == "upscale"


def test_image_edit_prompt_normalizer_expands_tattoo_removal():
    import agent.app as agent

    prompt = agent.normalize_image_edit_prompt("Tatoos entfernen")

    assert "Remove all visible tattoos" in prompt
    assert "natural, realistic skin" in prompt
    assert "Preserve the person's identity" in prompt


def test_image_edit_prompt_normalizer_expands_background_blur():
    import agent.app as agent

    prompt = agent.normalize_image_edit_prompt(
        "Mach den Hintergrund unscharf"
    )

    assert "depth-of-field blur" in prompt
    assert "main subject perfectly sharp" in prompt


def test_image_edit_prompt_normalizer_preserves_detailed_prompt():
    import agent.app as agent

    original = (
        "Remove the small tattoo on the left forearm only. "
        "Keep the large tattoo on the right shoulder unchanged. "
        "Preserve the exact face, pose, clothing, lighting and background."
    )

    assert agent.normalize_image_edit_prompt(original) == original


def _optimizer_response(content=None, body=None):
    if body is None:
        body = {
            "choices": [{
                "message": {"content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 40,
                "completion_tokens": 25,
                "total_tokens": 65,
            },
        }
    return io.BytesIO(json.dumps(body).encode("utf-8"))


def _run_mocked_image_edit_optimizer(prompt, content=None, body=None):
    import agent.app as agent

    runtime = {
        "resolved": {
            "repo": "owner/chat-model",
            "alias": "chat",
            "backend": "mlx_lm",
        },
    }
    with patch.object(
        agent,
        "ensure_model_for_role",
        return_value=runtime,
    ), patch.object(
        agent,
        "load_config",
        return_value={"PORT": 8000},
    ), patch.object(
        agent.urllib.request,
        "urlopen",
        return_value=_optimizer_response(content, body),
    ) as network:
        result = agent.optimize_image_edit_prompt(prompt)

    request = network.call_args.args[0]
    return result, json.loads(request.data.decode("utf-8")), network


def test_image_edit_prompt_optimizer_uses_original_instruction_and_metrics():
    import agent.app as agent

    optimized = (
        "Remove all visible tattoos from the person's skin. Preserve the "
        "person's identity, pose, clothing, background, and all unrelated "
        "image details."
    )
    observability.reset_metrics()
    with observability.trace_context("image-edit-optimize-001"):
        result, payload, network = _run_mocked_image_edit_optimizer(
            "  Tatoos\n entfernen  ",
            f'"{optimized}"',
        )

    assert result == optimized
    assert result != agent.normalize_image_edit_prompt("Tatoos entfernen")
    assert payload["messages"][1] == {
        "role": "user",
        "content": "Tatoos entfernen",
    }
    assert "tattoo" not in payload["messages"][0]["content"].casefold()
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 650
    assert payload["stream"] is False
    assert payload["chat_template_kwargs"] == {
        "enable_thinking": False,
    }
    assert network.call_args.kwargs["timeout"] == 180

    snapshot = observability.trace_snapshot("image-edit-optimize-001")
    assert snapshot["model_calls_in_turn"] == 1
    metric = snapshot["calls"][0]
    assert metric["purpose"] == "image.edit_prompt_optimize"
    assert metric["status"] == "completed"
    assert metric["model"]["role"] == "chat"
    assert metric["model"]["identifier"] == "owner/chat-model"
    assert metric["timings_ms"]["queue_wait"] is not None
    assert metric["timings_ms"]["upstream_connect"] is not None
    assert metric["finish_reason"] == "stop"
    assert metric["usage"]["count_method"] == "upstream"
    assert metric["usage"]["total_tokens"] == 65


def test_image_edit_prompt_optimizer_preserves_multiple_edits():
    optimized = (
        "Reduce the gray in the beard and remove all visible tattoos. "
        "Preserve identity and every unrelated image detail."
    )
    result, payload, _network = _run_mocked_image_edit_optimizer(
        "Mach den Bart weniger grau und entferne die Tattoos",
        optimized,
    )

    assert "gray in the beard" in result
    assert "remove all visible tattoos" in result
    assert payload["messages"][1]["content"] == (
        "Mach den Bart weniger grau und entferne die Tattoos"
    )


def _assert_image_edit_optimizer_refusal_falls_back(refusal):
    import agent.app as agent

    original = "Tattoos entfernen"
    trace_id = "image-edit-refusal-fallback"
    observability.reset_metrics()
    with observability.trace_context(trace_id):
        result, _payload, _network = _run_mocked_image_edit_optimizer(
            original,
            refusal,
        )

    assert result == agent.normalize_image_edit_prompt(original)
    assert refusal not in result
    snapshot = observability.trace_snapshot(trace_id)
    assert snapshot["model_calls_in_turn"] == 1
    metric = snapshot["calls"][0]
    assert metric["status"] == "failed"
    assert metric["error_type"] == "optimizer_refusal_fallback"


def test_image_edit_prompt_optimizer_rejects_german_refusal():
    for refusal in (
        "Ich kann diese Anforderung leider nicht erfüllen.",
        "ich kann dabei nicht helfen.",
    ):
        _assert_image_edit_optimizer_refusal_falls_back(refusal)


def test_image_edit_prompt_optimizer_rejects_english_refusal():
    for refusal in (
        "I can't comply with that request.",
        "I cannot comply with that request.",
        "I can't help with that image edit.",
        "I cannot help with that image edit.",
        "I cannot fulfill that request.",
        "I'm unable to perform that edit.",
        "I am unable to perform that edit.",
    ):
        _assert_image_edit_optimizer_refusal_falls_back(refusal)


def test_image_edit_prompt_optimizer_rejects_ai_assistant_meta_output():
    for refusal in (
        "Als KI-Assistent bin ich darauf ausgelegt, respektvoll zu bleiben.",
        "ALS KI kann ich diese Bearbeitung nicht vornehmen.",
        "As an AI, I cannot perform that edit.",
    ):
        _assert_image_edit_optimizer_refusal_falls_back(refusal)


def test_image_edit_prompt_optimizer_accepts_valid_english_output():
    optimized = (
        "Remove all visible tattoos while preserving the person's identity, "
        "skin texture, clothing, lighting, background, and composition."
    )

    result, _payload, _network = _run_mocked_image_edit_optimizer(
        "Tattoos entfernen",
        optimized,
    )

    assert result == optimized


def test_image_edit_prompt_optimizer_falls_back_for_invalid_responses():
    import agent.app as agent

    original = "Tatoos entfernen"
    fallback = agent.normalize_image_edit_prompt(original)
    cases = (
        {"choices": [{"message": {"content": ""}}]},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": "```markdown"}}]},
        {
            "choices": [{
                "message": {"content": "Here is the optimized prompt: Edit it"},
            }],
        },
        {
            "choices": [{
                "message": {"content": "A valid but incomplete edit prompt"},
                "finish_reason": "length",
            }],
        },
        {
            "choices": [{
                "message": {"content": "A" * 6001},
            }],
        },
    )

    for body in cases:
        result, _payload, _network = _run_mocked_image_edit_optimizer(
            original,
            body=body,
        )
        assert result == fallback


def test_image_edit_prompt_optimizer_falls_back_when_model_unavailable():
    import agent.app as agent

    original = "Tatoos entfernen"
    with patch.object(
        agent,
        "ensure_model_for_role",
        side_effect=RuntimeError("model unavailable"),
    ), patch.object(
        agent.urllib.request,
        "urlopen",
    ) as network:
        result = agent.optimize_image_edit_prompt(original)

    assert result == agent.normalize_image_edit_prompt(original)
    network.assert_not_called()


def test_image_edit_prompt_optimizer_falls_back_on_network_error():
    import agent.app as agent

    original = "Mach den Hintergrund unscharf"
    runtime = {
        "resolved": {
            "repo": "owner/chat-model",
            "alias": "chat",
            "backend": "mlx_lm",
        },
    }
    with patch.object(
        agent,
        "ensure_model_for_role",
        return_value=runtime,
    ), patch.object(
        agent,
        "load_config",
        return_value={"PORT": 8000},
    ), patch.object(
        agent.urllib.request,
        "urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        result = agent.optimize_image_edit_prompt(original)

    assert result == agent.normalize_image_edit_prompt(original)


def test_image_edit_payload_uses_optimizer_result(tmp_path):
    import agent.app as agent

    source = tmp_path / "source.png"
    source.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01"
        b"\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
    )

    request = agent.ChatActionRequest(
        prompt="Tattoos entfernen",
        file_context={
            "stored_path": str(source),
        },
    )

    with patch.object(
        agent,
        "optimize_image_edit_prompt",
        return_value="Remove the requested tattoos and preserve all else.",
    ) as optimizer:
        payload = agent._image_edit_payload(request)

    assert payload["source_path"] == str(source)
    assert payload["prompt"] == (
        "Remove the requested tattoos and preserve all else."
    )
    assert payload["model"] == "mflux-qwen-image-edit-2511"
    optimizer.assert_called_once_with("Tattoos entfernen")


def test_image_edit_payload_never_forwards_optimizer_refusal(tmp_path):
    import agent.app as agent

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    request = agent.ChatActionRequest(
        prompt="Tattoos entfernen",
        file_context={"stored_path": str(source)},
    )
    refusal = "I can't comply with that request."
    runtime = {
        "resolved": {
            "repo": "owner/chat-model",
            "alias": "chat",
            "backend": "mlx_lm",
        },
    }

    with patch.object(
        agent,
        "ensure_model_for_role",
        return_value=runtime,
    ), patch.object(
        agent,
        "load_config",
        return_value={"PORT": 8000},
    ), patch.object(
        agent.urllib.request,
        "urlopen",
        return_value=_optimizer_response(refusal),
    ):
        payload = agent._image_edit_payload(request)

    assert payload["prompt"] == agent.normalize_image_edit_prompt(
        request.prompt
    )
    assert refusal not in payload["prompt"]


def test_image_edit_payload_preserves_explicit_prompt_override(tmp_path):
    import agent.app as agent

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    request = agent.ChatActionRequest(
        prompt="Tatoos entfernen",
        file_context={"stored_path": str(source)},
        image_options={
            "prompt": "Exact low-level edit instruction",
            "model": "custom-edit-model",
        },
    )

    with patch.object(
        agent,
        "optimize_image_edit_prompt",
        side_effect=AssertionError(
            "Explicit prompt must bypass optimization"
        ),
    ) as optimizer:
        payload = agent._image_edit_payload(request)

    optimizer.assert_not_called()
    assert payload["prompt"] == "Exact low-level edit instruction"
    assert payload["source_path"] == str(source)
    assert payload["model"] == "custom-edit-model"
