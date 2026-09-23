import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import video_providers
import video_registry
import video_service
from agent import app as agent


class VideoRegistryTests(unittest.TestCase):
    def test_builtin_ltx_model_and_local_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = video_registry.MODEL_ROOT
            video_registry.MODEL_ROOT = Path(tmp)
            try:
                for relative in video_registry.REQUIRED_FILES:
                    target = Path(tmp) / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                model = video_registry.builtin_model()
                self.assertTrue(video_registry.local_files_available(model))
                self.assertEqual(model["id"], "ltx-2.5-22b-distilled")
                self.assertEqual(model["repository"], "Lightricks/LTX-2.5")
                self.assertEqual(model["provider"], "ltx-desktop-headless")
            finally:
                video_registry.MODEL_ROOT = old_root

    def test_missing_checkpoint_is_reported(self):
        with mock.patch.object(video_registry, "local_files_available", return_value=False), \
             mock.patch.object(video_registry, "missing_files", return_value=["missing.safetensors"]):
            ready, reason = video_providers.availability(video_registry.builtin_model())
        self.assertFalse(ready)
        self.assertIn("missing.safetensors", reason)


class VideoProviderTests(unittest.TestCase):
    def test_runtime_availability_requires_runtime_and_weights(self):
        model = video_registry.builtin_model()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            python = runtime / "python"
            server = runtime / "ltx2_server.py"
            python.touch()
            server.touch()
            with mock.patch.object(video_registry, "local_files_available", return_value=True), \
                 mock.patch.object(video_providers, "LTX_PYTHON", python), \
                 mock.patch.object(video_providers, "LTX_SERVER", server):
                ready, reason = video_providers.availability(model)
        self.assertTrue(ready)
        self.assertIn("LTX 2.5 Fast", reason)

    def test_t2v_payload_uses_official_local_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_output = Path(tmp) / "official.mp4"
            source_output.write_bytes(b"mp4")
            output = Path(tmp) / "artifact.mp4"
            with mock.patch.object(video_providers, "availability", return_value=(True, "ok")), \
                 mock.patch.object(video_providers, "_start_runtime", return_value=(mock.Mock(), mock.Mock())), \
                 mock.patch.object(video_providers, "unload") as unload, \
                 mock.patch.object(video_providers, "_generate_request", return_value={
                     "status": "complete", "video_path": str(source_output),
                 }) as generated, \
                 mock.patch.object(video_providers, "_probe_video", return_value={
                     "frames": 121, "width": 1024, "height": 576, "fps": 24,
                     "duration": 5, "audio": True,
                 }):
                result = video_providers.generate(
                    video_registry.builtin_model(), {
                        "prompt": "Red ball rolls", "resolution": "540p", "duration": 5,
                        "fps": 24, "aspect_ratio": "16:9", "width": 1024, "height": 576,
                        "seed": 7, "first_frame": None,
                    }, output, cancel_event=threading.Event(),
                )
            payload = generated.call_args.args[0]
            self.assertEqual(payload["model"], "fast")
            self.assertEqual(payload["resolution"], "540p")
            self.assertEqual(payload["duration"], 5)
            self.assertEqual(payload["seed"], 7)
            self.assertNotIn("imagePath", payload)
            self.assertTrue(result["audio"])
            self.assertEqual(output.read_bytes(), b"mp4")
            unload.assert_called_once()

    def test_i2v_prepares_contained_first_frame_and_reports_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portrait.png"
            source.write_bytes(b"png")
            source_output = Path(tmp) / "official.mp4"
            source_output.write_bytes(b"mp4")
            output = Path(tmp) / "artifact.mp4"
            resize = {
                "source_width": 768, "source_height": 1024,
                "target_width": 704, "target_height": 1280, "resize_mode": "contain",
            }

            def prepare(_source, _width, _height, _mode, destination):
                destination.write_bytes(b"prepared")
                return resize

            with mock.patch.object(video_providers, "availability", return_value=(True, "ok")), \
                 mock.patch.object(video_providers, "validate_first_frame", return_value=source), \
                 mock.patch.object(video_providers, "_start_runtime", return_value=(mock.Mock(), mock.Mock())), \
                 mock.patch.object(video_providers, "unload"), \
                 mock.patch.object(video_providers, "_prepare_first_frame", side_effect=prepare) as prepared, \
                 mock.patch.object(video_providers, "_generate_request", return_value={
                     "status": "complete", "video_path": str(source_output),
                 }) as generated, \
                 mock.patch.object(video_providers, "_probe_video", return_value={
                     "frames": 121, "width": 704, "height": 1280, "fps": 24,
                     "duration": 5, "audio": True,
                 }):
                result = video_providers.generate(
                    video_registry.builtin_model(), {
                        "prompt": "Blink", "resolution": "720p", "duration": 5,
                        "fps": 24, "aspect_ratio": "9:16", "width": 704, "height": 1280,
                        "seed": 7, "first_frame": str(source), "resize_mode": "contain",
                    }, output, cancel_event=threading.Event(),
                )
            prepared.assert_called_once()
            payload = generated.call_args.args[0]
            self.assertTrue(payload["imagePath"].endswith("first-frame.png"))
            self.assertEqual(result["source_width"], 768)
            self.assertEqual(result["target_height"], 1280)
            self.assertEqual(result["resize_mode"], "contain")

    def test_i2v_orientation_and_contain_geometry(self):
        cases = [
            ((768, 1024), (704, 1280), "9:16"),
            ((1600, 900), (1280, 704), "16:9"),
            ((1024, 1024), (1024, 1024), "16:9"),
        ]
        for source, target, aspect in cases:
            with self.subTest(source=source):
                self.assertEqual(video_providers.i2v_target_size(*source), target)
                self.assertEqual(video_providers.i2v_aspect_ratio(*source), aspect)
                content = video_providers.i2v_contained_size(*source, *target)
                self.assertLessEqual(content[0], target[0])
                self.assertLessEqual(content[1], target[1])
                self.assertAlmostEqual(content[0] / content[1], source[0] / source[1])

    def test_square_video_finalization_contains_and_pads_without_stretch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"video")
            output = Path(tmp) / "square.mp4"

            def run(command, **_kwargs):
                output.write_bytes(b"square")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.object(video_providers.subprocess, "run", side_effect=run) as invoked:
                video_providers._finalize_video(source, output, 1024, 1024, 1280, 704)
            command = invoked.call_args.args[0]
            video_filter = command[command.index("-vf") + 1]
            self.assertIn("force_original_aspect_ratio=decrease", video_filter)
            self.assertIn("pad=1024:1024", video_filter)
            self.assertNotIn("crop=", video_filter)

    def test_cancel_posts_official_cancel_and_unloads(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(video_providers, "availability", return_value=(True, "ok")), \
             mock.patch.object(video_providers, "_start_runtime", side_effect=ProviderCancelledForTest):
            with self.assertRaises(video_providers.ProviderCancelled):
                video_providers.generate(
                    video_registry.builtin_model(), {
                        "prompt": "test", "first_frame": None, "width": 1024, "height": 576,
                        "resolution": "540p", "duration": 5, "fps": 24,
                        "aspect_ratio": "16:9", "seed": 1,
                    }, Path("/tmp/never.mp4"), cancel_event=cancel,
                )

    def test_i2v_accepts_only_managed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = video_providers.UPLOAD_ROOT
            video_providers.UPLOAD_ROOT = Path(tmp)
            managed = Path(tmp) / "abcdef123456.jpg"
            managed.write_bytes(b"image")
            outside = Path(tmp).parent / "client.jpg"
            try:
                self.assertEqual(video_providers.validate_first_frame(str(managed)), managed.resolve())
                with self.assertRaises(ValueError):
                    video_providers.validate_first_frame(str(outside))
            finally:
                video_providers.UPLOAD_ROOT = old_root


def ProviderCancelledForTest(_cancel):
    raise video_providers.ProviderCancelled("cancelled")


class VideoServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_jobs, self.old_output = video_service.JOBS, video_service.OUTPUT
        video_service.JOBS = Path(self.tmp.name) / "jobs"
        video_service.OUTPUT = Path(self.tmp.name) / "videos"
        video_service._jobs.clear()

    def tearDown(self):
        if video_service._lock.locked():
            video_service._lock.release()
        video_service._jobs.clear()
        video_service.JOBS, video_service.OUTPUT = self.old_jobs, self.old_output
        self.tmp.cleanup()

    def request(self, operation="t2v", first_frame=None, quality=None):
        payload = {"prompt": "A red ball rolls", "seed": 1, "first_frame": first_frame}
        if quality:
            payload["quality"] = quality
        if operation == "i2v":
            validation = mock.patch.multiple(
                video_service, validate_first_frame=mock.DEFAULT, i2v_source_size=mock.DEFAULT,
            )
            with validation as patched:
                patched["validate_first_frame"].return_value = Path("/managed/image.png")
                patched["i2v_source_size"].return_value = (768, 1024)
                return video_service.JobCreate(
                    operation=operation, chat_id="chat", chat_revision=0, payload=payload,
                )
        return video_service.JobCreate(
            operation=operation, chat_id="chat", chat_revision=0, payload=payload,
        )

    def _job(self, job_id="a" * 24):
        return {
            "id": job_id, "status": "queued", "chat_id": "chat", "run_id": job_id,
            "chat_revision": 0, "operation": "t2v", "current_step": None,
            "total_steps": 11, "result": None, "error": None, "created_at": 1,
            "started_at": None, "finished_at": None, "_cancel_event": threading.Event(),
            "_runtime": None, "_thread": None,
        }

    def test_payload_rules(self):
        with self.assertRaises(ValueError):
            video_service.JobCreate(
                operation="i2v", chat_id="chat", chat_revision=0,
                payload={"prompt": "Animate gently"},
            )
        self.assertEqual(self.request("i2v", "/managed/image.png").operation, "i2v")

    def test_quality_profiles_map_to_ltx_resolution(self):
        expected = {
            "fast": ("540p", (1024, 576)),
            "standard": ("720p", (1280, 704)),
            "quality": ("1080p", (1920, 1088)),
        }
        for quality, (resolution, size) in expected.items():
            request = self.request(quality=quality)
            self.assertEqual(request.payload.resolution, resolution)
            self.assertEqual((request.payload.width, request.payload.height), size)
            self.assertEqual(request.payload.steps, 11)

    def test_default_is_standard(self):
        request = self.request()
        self.assertEqual(request.payload.resolution, "720p")
        self.assertEqual((request.payload.width, request.payload.height), (1280, 704))

    def test_i2v_profiles_preserve_portrait_orientation(self):
        expected = {
            "fast": ("540p", (576, 1024)),
            "standard": ("720p", (704, 1280)),
            "quality": ("1080p", (1088, 1920)),
        }
        for quality, (resolution, size) in expected.items():
            request = self.request("i2v", "/managed/image.png", quality)
            self.assertEqual(request.payload.resolution, resolution)
            self.assertEqual((request.payload.width, request.payload.height), size)
            self.assertEqual(request.payload.aspect_ratio, "9:16")
            self.assertEqual(request.payload.resize_mode, "contain")

    def test_job_lifecycle_artifact_and_memory_metrics(self):
        request = self.request()
        job_id = "a" * 24
        video_service._jobs[job_id] = self._job(job_id)
        video_service._lock.acquire()

        def fake_generate(_model, _payload, output, **callbacks):
            callbacks["phase_callback"]("generating")
            callbacks["progress_callback"]({"step": 4, "total_steps": 8, "progress": 50})
            callbacks["phase_callback"]("decoding")
            callbacks["phase_callback"]("muxing")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mp4")
            return {"width": 1280, "height": 704, "frames": 121, "fps": 24,
                    "duration": 5, "audio": True}

        snapshot = {"ram_used_bytes": 10, "swap_used_bytes": 2}
        with mock.patch.object(video_service.registry, "get_model", return_value=video_registry.builtin_model()), \
             mock.patch.object(video_service, "availability", return_value=(True, "ok")), \
             mock.patch.object(video_service, "_image_idle", return_value=True), \
             mock.patch.object(video_service, "_chat_loaded", return_value=False), \
             mock.patch.object(video_service, "_memory_snapshot", return_value=snapshot), \
             mock.patch.object(video_service, "generate", side_effect=fake_generate):
            video_service._run(job_id, request)
        job = video_service._jobs[job_id]
        self.assertEqual(job["status"], "completed")
        self.assertTrue(Path(job["result"]["path"]).is_file())
        self.assertEqual(job["result"]["pipeline"], "fast")
        self.assertEqual(job["result"]["memory_peak"], snapshot)

    def test_cancel_and_restart_recovery(self):
        path = video_service.JOBS / ("b" * 24 + ".json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"id": "b" * 24, "status": "generating"}))
        video_service._load_jobs()
        self.assertEqual(video_service._jobs["b" * 24]["status"], "failed")

    def test_ram_handoff_stops_and_restores_chat_on_failure(self):
        request = self.request()
        job_id = "e" * 24
        video_service._jobs[job_id] = self._job(job_id)
        video_service._lock.acquire()
        commands = []
        with mock.patch.object(video_service.registry, "get_model", return_value=video_registry.builtin_model()), \
             mock.patch.object(video_service, "availability", return_value=(True, "ok")), \
             mock.patch.object(video_service, "_image_idle", return_value=True), \
             mock.patch.object(video_service, "_chat_loaded", return_value=True), \
             mock.patch.object(video_service, "_chat_command", side_effect=commands.append), \
             mock.patch.object(video_service, "_memory_snapshot", return_value={}), \
             mock.patch.object(video_service.time, "sleep"), \
             mock.patch.object(video_service, "generate", side_effect=RuntimeError("runtime failed")):
            video_service._run(job_id, request)
        self.assertEqual(video_service._jobs[job_id]["status"], "failed")
        self.assertEqual(commands, ["stop", "start"])

    def test_memory_preflight_failure_is_clean(self):
        request = self.request()
        job_id = "f" * 24
        video_service._jobs[job_id] = self._job(job_id)
        video_service._lock.acquire()
        with mock.patch.object(video_service.registry, "get_model", return_value=video_registry.builtin_model()), \
             mock.patch.object(video_service, "availability", return_value=(True, "ok")), \
             mock.patch.object(video_service, "_image_idle", return_value=True), \
             mock.patch.object(video_service, "_chat_loaded", return_value=False), \
             mock.patch.object(video_service, "_memory_snapshot", return_value={}), \
             mock.patch.object(video_service, "generate", side_effect=RuntimeError(
                 "LTX Memory-Preflight fehlgeschlagen: weniger als 15 GB RAM frei"
             )):
            video_service._run(job_id, request)
        self.assertEqual(video_service._jobs[job_id]["status"], "failed")
        self.assertIn("Memory-Preflight", video_service._jobs[job_id]["error"])


class VideoAgentTests(unittest.TestCase):
    def test_chat_routing_and_normal_chat(self):
        self.assertEqual(agent.classify_chat_action("Erstelle ein Video von einem roten Ball"), "video_generate")
        self.assertEqual(agent.classify_chat_action("Mach daraus ein Video"), "video_animate")
        self.assertEqual(agent.classify_chat_action("Animiere dieses Bild"), "video_animate")
        normal = agent.classify_chat_action_details(
            "Wie wird das Wetter?",
            classifier=lambda *_args: {
                "intent": "normal_chat", "confidence": 0.99,
                "requires_tools": False, "reason": "ordinary chat",
            },
        )
        self.assertEqual(normal["intent"], "normal_chat")

    def test_prompt_compiler_fallback_preserves_attributes(self):
        with mock.patch.object(agent, "router_llm", side_effect=RuntimeError("offline")):
            self.assertEqual(agent.compile_video_prompt("rote Kugel, statische Kamera"), "rote Kugel, statische Kamera")

    def test_text_only_video_builds_t2v_without_first_frame(self):
        request = agent.ChatActionRequest(prompt="Erstelle ein Video von einem roten Ball")
        with mock.patch.object(agent, "compile_video_prompt", side_effect=lambda value: value):
            payload = agent._video_payload(request, "t2v")
        self.assertNotIn("first_frame", payload)

    def test_video_quality_is_forwarded_by_agent(self):
        request = agent.ChatActionRequest(
            prompt="Erstelle ein Video von einem roten Ball", quality="quality",
        )
        with mock.patch.object(agent, "compile_video_prompt", side_effect=lambda value: value):
            payload = agent._video_payload(request, "t2v")
        self.assertEqual(payload["quality"], "quality")

    def test_upload_animation_uses_managed_chat_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = agent.VIDEO_UPLOAD_DIRECTORY
            agent.VIDEO_UPLOAD_DIRECTORY = Path(tmp)
            upload = Path(tmp) / "123456abcdef.png"
            upload.write_bytes(b"\x89PNG\r\n\x1a\nmanaged")
            request = agent.ChatActionRequest(
                prompt="Animiere dieses Bild",
                file_context={"kind": "image", "stored_path": str(upload)},
            )
            try:
                with mock.patch.object(agent, "compile_video_prompt", side_effect=lambda value: value):
                    payload = agent._video_payload(request, "i2v")
            finally:
                agent.VIDEO_UPLOAD_DIRECTORY = old_root
        self.assertEqual(payload["first_frame"], str(upload.resolve()))

    def test_active_artifact_animation_uses_artifact(self):
        source = Path("/managed/image.png")
        request = agent.ChatActionRequest(
            prompt="Mach daraus ein Video", active_artifact_id="image-1234567890-abcdef123456",
        )
        with mock.patch.object(agent, "compile_video_prompt", side_effect=lambda value: value), \
             mock.patch.object(agent, "_resolve_image_artifact_source", return_value=source):
            payload = agent._video_payload(request, "i2v")
        self.assertEqual(payload["first_frame"], str(source))

    def test_animation_without_image_has_clear_error(self):
        with self.assertRaises(HTTPException) as raised:
            agent._video_payload(agent.ChatActionRequest(prompt="Animiere dieses Bild"), "i2v")
        self.assertIn("lade ein Bild hoch", str(raised.exception.detail))

    def test_qwen_image_40_step_regression(self):
        import image_service
        model = {"id": "qwen-image21", "default_steps": 40}
        self.assertEqual(image_service._resolved_steps(model, None), 40)


if __name__ == "__main__":
    unittest.main()
