import asyncio
import tempfile
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent import app as agent_app
from backend import observability


class BusyLock:
    def acquire(self, blocking=True):
        return False

    def release(self):
        raise AssertionError("Busy lock must not be released")


class ModelRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        observability.reset_metrics()

    def test_stream_metrics_include_ttft_usage_and_stable_trace(self):
        upstream = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            b'"usage":{"prompt_tokens":9,"completion_tokens":2,'
            b'"total_tokens":11}}\n\n'
            b'data: [DONE]\n\n'
        )
        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }
        client = TestClient(agent_app.app, base_url="http://localhost")
        self.addCleanup(client.close)

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            return_value=upstream,
        ):
            response = client.post(
                "/api/runtime/chat/stream",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "trace_id": "trace-stream-001",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        events = response.text.split("\n\n")
        metric_event = next(
            event for event in events
            if event.startswith("event: metrics")
        )
        snapshot = json.loads(
            next(
                line[5:].strip()
                for line in metric_event.splitlines()
                if line.startswith("data:")
            )
        )
        call = snapshot["calls"][0]
        self.assertEqual(snapshot["trace_id"], "trace-stream-001")
        self.assertEqual(snapshot["model_calls_in_turn"], 1)
        self.assertEqual(call["purpose"], "chat.stream")
        self.assertIsNotNone(call["timings_ms"]["ttft"])
        self.assertIsNotNone(call["timings_ms"]["generation"])
        self.assertEqual(call["finish_reason"], "stop")
        self.assertEqual(call["usage"]["input_tokens"], 9)
        self.assertEqual(call["usage"]["output_tokens"], 2)
        self.assertEqual(call["usage"]["count_method"], "upstream")

    def test_agent_planner_and_final_calls_share_trace_and_have_unique_ids(self):
        runtime = {
            "resolved": {
                "repo": "owner/agent-model",
                "alias": "agent",
                "backend": "mlx_lm",
            },
        }

        def response(content):
            return io.BytesIO(json.dumps({
                "choices": [{
                    "message": {"content": content},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            }).encode("utf-8"))

        with observability.trace_context("trace-agent-001"), mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            side_effect=[response("plan"), response("final")],
        ):
            self.assertEqual(
                agent_app.observed_agent_llm(
                    "agent.plan",
                    [{"role": "user", "content": "goal"}],
                ),
                "plan",
            )
            self.assertEqual(
                agent_app.observed_agent_llm(
                    "agent.final",
                    [{"role": "user", "content": "observations"}],
                ),
                "final",
            )

        snapshot = observability.trace_snapshot("trace-agent-001")
        self.assertEqual(snapshot["model_calls_in_turn"], 2)
        self.assertEqual(
            [call["purpose"] for call in snapshot["calls"]],
            ["agent.plan", "agent.final"],
        )
        self.assertNotEqual(
            snapshot["calls"][0]["request_id"],
            snapshot["calls"][1]["request_id"],
        )
        self.assertEqual(
            snapshot["calls"][1]["parent_request_id"],
            snapshot["calls"][0]["request_id"],
        )
        self.assertTrue(all(
            call["timings_ms"]["generation"] is not None
            for call in snapshot["calls"]
        ))

    def test_failed_stream_exposes_failed_metrics_before_error(self):
        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }
        client = TestClient(agent_app.app, base_url="http://localhost")
        self.addCleanup(client.close)

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            response = client.post(
                "/api/runtime/chat/stream",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "trace_id": "trace-stream-failed-001",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            response.text.index("event: metrics"),
            response.text.index("event: error"),
        )
        snapshot = observability.trace_snapshot("trace-stream-failed-001")
        self.assertEqual(snapshot["model_calls_in_turn"], 1)
        self.assertEqual(snapshot["calls"][0]["status"], "failed")
        self.assertEqual(snapshot["calls"][0]["error_type"], "URLError")

    def test_model_input_compatibility_and_rejection_before_manager(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/model_validation.json').read_text())
        cases.append({'alias': 'a' * 97, 'repo': 'owner/model', 'valid': True})
        client = TestClient(agent_app.app, base_url='http://localhost')
        for case in cases:
            with self.subTest(case=case), mock.patch.object(agent_app, 'load_models', return_value=[]), \
                    mock.patch.object(agent_app.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as manager, \
                    mock.patch.object(agent_app, 'create_background_job', return_value={'id': 'test'}):
                response = client.post('/api/models/add', json={'alias': case['alias'], 'repo': case['repo']})
                self.assertEqual(response.status_code, 200 if case['valid'] else 400, response.text)
                if case['valid']:
                    args = manager.call_args.args[0]
                    self.assertEqual(args[3], case['alias'].strip())
                    self.assertEqual(args[4], str(Path(case['repo'].strip()).expanduser()) if case['repo'].strip().startswith(('~/', '/')) else case['repo'].strip())
                else:
                    manager.assert_not_called()

    def test_existing_local_reference_can_switch_but_unsafe_reference_cannot(self):
        for repo, valid in [('~/Models/Qwen3.8-27B/6-bit', True), ('/Models/a$variable', False)]:
            with self.subTest(repo=repo), mock.patch.object(agent_app, 'load_models', return_value=[{'alias': '_local', 'repo': repo}]), \
                    mock.patch.object(agent_app.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as manager, \
                    mock.patch.object(agent_app, 'wait_for_model_runtime', return_value={'ok': True}):
                if valid:
                    self.assertTrue(agent_app.switch_model_runtime('_local')['ok'])
                    self.assertEqual(manager.call_args.args[0][-1], '_local')
                else:
                    with self.assertRaises(HTTPException):
                        agent_app.switch_model_runtime('_local')
                    manager.assert_not_called()

    def test_cache_summary_uses_real_sizes_and_exposes_path(self):
        items = [
            {
                "repo": "owner/one",
                "alias": "one",
                "path": "/cache/models--owner--one",
                "size_bytes": 1024,
                "size": "1.0 KB",
                "complete": True,
                "incomplete_files": 0,
                "incomplete_bytes": 0,
                "incomplete_size": "0.0 B",
            },
            {
                "repo": "owner/two",
                "alias": None,
                "path": "/cache/models--owner--two",
                "size_bytes": 2048,
                "size": "2.0 KB",
                "complete": False,
                "incomplete_files": 1,
                "incomplete_bytes": 10,
                "incomplete_size": "10.0 B",
            },
        ]
        with mock.patch.object(agent_app, "load_cache", return_value=items), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"MODEL": "owner/one"},
        ):
            result = agent_app.cache()

        self.assertEqual(result["total_size_bytes"], 3072)
        self.assertEqual(result["total_size"], "3.0 KB")
        self.assertTrue(result["path"].endswith(".cache/huggingface/hub"))
        self.assertTrue(result["models"][0]["active"])
        self.assertEqual(result["incomplete"], 1)

    def test_local_model_add_does_not_start_download(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "local-model"
            model_path.mkdir()
            request = agent_app.AddModelRequest(alias="local", repo=str(model_path))
            process = mock.Mock(returncode=0, stdout="added", stderr="")

            with mock.patch.object(agent_app, "load_models", return_value=[]), mock.patch.object(
                agent_app.subprocess,
                "run",
                return_value=process,
            ), mock.patch.object(agent_app, "create_background_job") as download:
                result = agent_app.add_model(request)

        self.assertIsNone(result["job"])
        download.assert_not_called()

    def test_remote_model_add_keeps_background_download(self):
        request = agent_app.AddModelRequest(alias="remote", repo="owner/model")
        process = mock.Mock(returncode=0, stdout="added", stderr="")
        job = {"id": "job-1", "status": "queued"}

        with mock.patch.object(agent_app, "load_models", return_value=[]), mock.patch.object(
            agent_app.subprocess,
            "run",
            return_value=process,
        ), mock.patch.object(agent_app, "create_background_job", return_value=job) as download:
            result = agent_app.add_model(request)

        self.assertEqual(result["job"], job)
        download.assert_called_once_with("download", "remote")

    def test_runtime_mutations_reject_concurrent_action(self):
        with mock.patch.object(agent_app, "MODEL_RUNTIME_LOCK", BusyLock()):
            for action in (
                lambda: agent_app.server_command("restart"),
                lambda: agent_app.model_command("other"),
                lambda: agent_app.thinking_command("on"),
            ):
                with self.assertRaises(HTTPException) as context:
                    action()
                self.assertEqual(context.exception.status_code, 409)
                self.assertIn("Runtime-Aktion", context.exception.detail)



    def test_background_job_thread_start_failure_is_persisted(self):
        with agent_app.JOBS_LOCK:
            agent_app.JOBS.clear()

        agent_app.JOBS_FILE.unlink(missing_ok=True)

        class BrokenThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("thread start failed")

        with (
            mock.patch.object(
                agent_app,
                "resolve_repo",
                return_value="repo/test",
            ),
            mock.patch.object(
                agent_app,
                "has_running_job_for_model",
                return_value=(False, None),
            ),
            mock.patch.object(
                agent_app.threading,
                "Thread",
                BrokenThread,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "thread start failed",
            ):
                agent_app.create_background_job(
                    "download",
                    "test-model",
                )

        with agent_app.JOBS_LOCK:
            self.assertEqual(
                len(agent_app.JOBS),
                1,
            )
            job = next(iter(agent_app.JOBS.values())).copy()

        self.assertEqual(
            job["status"],
            "failed",
        )
        self.assertIn(
            "thread start failed",
            job["error"],
        )
        self.assertIsNotNone(
            job["finished_at"],
        )

        persisted = agent_app.JOBS_FILE.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"status": "failed"',
            persisted,
        )
        self.assertIn(
            "thread start failed",
            persisted,
        )

    def test_hf_subfolder_thread_start_failure_is_persisted(self):
        with agent_app.JOBS_LOCK:
            agent_app.JOBS.clear()

        agent_app.JOBS_FILE.unlink(missing_ok=True)

        class BrokenThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("hf thread start failed")

        with (
            mock.patch.object(
                agent_app,
                "has_running_job_for_model",
                return_value=(False, None),
            ),
            mock.patch.object(
                agent_app.threading,
                "Thread",
                BrokenThread,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "hf thread start failed",
            ):
                agent_app.create_hf_subfolder_job(
                    "test-model",
                    "org/test-model",
                    "4-bit",
                )

        with agent_app.JOBS_LOCK:
            self.assertEqual(
                len(agent_app.JOBS),
                1,
            )
            job = next(iter(agent_app.JOBS.values())).copy()

        self.assertEqual(
            job["status"],
            "failed",
        )
        self.assertIn(
            "hf thread start failed",
            job["error"],
        )
        self.assertIsNotNone(
            job["finished_at"],
        )

        persisted = agent_app.JOBS_FILE.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"status": "failed"',
            persisted,
        )
        self.assertIn(
            "hf thread start failed",
            persisted,
        )


    def test_background_job_creation_fails_when_initial_persistence_fails(self):
        with agent_app.JOBS_LOCK:
            jobs_before = set(agent_app.JOBS)

        with (
            mock.patch.object(
                agent_app,
                "resolve_repo",
                return_value="repo/test",
            ),
            mock.patch.object(
                agent_app,
                "has_running_job_for_model",
                return_value=(False, None),
            ),
            mock.patch.object(
                agent_app,
                "save_jobs",
                side_effect=OSError("disk full"),
            ) as save_jobs,
            mock.patch.object(
                agent_app.threading,
                "Thread",
            ) as thread_class,
        ):
            with self.assertRaisesRegex(
                OSError,
                "disk full",
            ):
                agent_app.create_background_job(
                    "download",
                    "test-model",
                )

        save_jobs.assert_called_once_with(strict=True)
        thread_class.assert_not_called()

        with agent_app.JOBS_LOCK:
            self.assertEqual(
                set(agent_app.JOBS),
                jobs_before,
            )

    def test_hf_job_creation_fails_when_initial_persistence_fails(self):
        with agent_app.JOBS_LOCK:
            jobs_before = set(agent_app.JOBS)

        with (
            mock.patch.object(
                agent_app,
                "has_running_job_for_model",
                return_value=(False, None),
            ),
            mock.patch.object(
                agent_app,
                "save_jobs",
                side_effect=OSError("disk full"),
            ) as save_jobs,
            mock.patch.object(
                agent_app.threading,
                "Thread",
            ) as thread_class,
        ):
            with self.assertRaisesRegex(
                OSError,
                "disk full",
            ):
                agent_app.create_hf_subfolder_job(
                    "test-model",
                    "org/test-model",
                    "4-bit",
                )

        save_jobs.assert_called_once_with(strict=True)
        thread_class.assert_not_called()

        with agent_app.JOBS_LOCK:
            self.assertEqual(
                set(agent_app.JOBS),
                jobs_before,
            )

    def test_stream_generator_close_cancels_worker_and_upstream(self):
        import threading
        import time

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        first_line_consumed = threading.Event()
        allow_next_line = threading.Event()
        upstream_closed = threading.Event()

        class BlockingUpstream:
            def __init__(self):
                self.index = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                upstream_closed.set()
                return False

            def __iter__(self):
                return self

            def __next__(self):
                self.index += 1

                if self.index == 1:
                    first_line_consumed.set()
                    return (
                        b'data: {"choices":[{"delta":'
                        b'{"content":"first"}}]}\n\n'
                    )

                if self.index == 2:
                    allow_next_line.wait(timeout=2)
                    return (
                        b'data: {"choices":[{"delta":'
                        b'{"content":"second"}}]}\n\n'
                    )

                return b'data: [DONE]\n\n'

        upstream = BlockingUpstream()

        request = agent_app.RuntimeChatRequest(
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            trace_id="trace-stream-cancel-001",
        )

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            return_value=upstream,
        ):
            response = agent_app.runtime_chat_stream(request)

            generator = response.body_iterator

            async def read_first():
                return await anext(generator)

            first = asyncio.run(
                read_first()
            )

            self.assertIsNotNone(first)
            self.assertIn('"text": "first"', first)

            self.assertTrue(
                first_line_consumed.wait(timeout=1),
                "worker never consumed first upstream line",
            )

            asyncio.run(
                generator.aclose()
            )
            allow_next_line.set()

            self.assertTrue(
                upstream_closed.wait(timeout=2),
                "upstream response was not closed after cancellation",
            )

            deadline = time.monotonic() + 2

            snapshot = None
            while time.monotonic() < deadline:
                snapshot = observability.trace_snapshot(
                    "trace-stream-cancel-001"
                )

                calls = snapshot.get("calls", [])
                if (
                    calls
                    and calls[0].get("status") == "failed"
                ):
                    break

                time.sleep(0.01)

            self.assertIsNotNone(snapshot)
            self.assertEqual(
                snapshot["calls"][0]["status"],
                "failed",
            )
            self.assertEqual(
                snapshot["calls"][0].get("error_type"),
                "cancelled",
            )

            self.assertLessEqual(
                upstream.index,
                2,
                "worker kept consuming upstream after cancellation",
            )



    def test_stream_generator_close_terminates_worker_thread(self):
        import threading
        import time

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        release = threading.Event()
        first_line_consumed = threading.Event()

        class BlockingUpstream:
            def __init__(self):
                self.index = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                self.index += 1

                if self.index == 1:
                    first_line_consumed.set()
                    return (
                        b'data: {"choices":[{"delta":'
                        b'{"content":"first"}}]}\n\n'
                    )

                release.wait(timeout=2)

                return b'data: [DONE]\n\n'

        request = agent_app.RuntimeChatRequest(
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            trace_id="trace-stream-worker-lifecycle-001",
        )

        before = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "mlx-chat-stream"
        }

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            return_value=BlockingUpstream(),
        ):
            response = agent_app.runtime_chat_stream(request)
            generator = response.body_iterator

            async def read_first():
                return await anext(generator)

            first = asyncio.run(read_first())

            self.assertIn('"text": "first"', first)

            self.assertTrue(
                first_line_consumed.wait(timeout=1),
                "worker never consumed first upstream line",
            )

            active = [
                thread
                for thread in threading.enumerate()
                if (
                    thread.name == "mlx-chat-stream"
                    and thread.ident not in before
                )
            ]

            self.assertEqual(
                len(active),
                1,
                "expected exactly one stream worker",
            )

            worker_thread = active[0]

            asyncio.run(generator.aclose())

            release.set()

            deadline = time.monotonic() + 2

            while (
                worker_thread.is_alive()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)

            self.assertFalse(
                worker_thread.is_alive(),
                "mlx-chat-stream worker survived stream cancellation",
            )



    def test_stream_applies_backpressure_to_fast_upstream(self):
        import threading
        import time

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        produced = 0
        produced_lock = threading.Lock()
        producer_started = threading.Event()

        class FastUpstream:
            def __init__(self):
                self.index = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                nonlocal produced

                self.index += 1

                if self.index > 10000:
                    return b'data: [DONE]\n\n'

                with produced_lock:
                    produced += 1

                producer_started.set()

                return (
                    b'data: {"choices":[{"delta":'
                    b'{"content":"x"}}]}\n\n'
                )

        request = agent_app.RuntimeChatRequest(
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            trace_id="trace-stream-backpressure-001",
        )

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            return_value=FastUpstream(),
        ):
            response = agent_app.runtime_chat_stream(request)
            generator = response.body_iterator

            self.assertTrue(
                producer_started.wait(timeout=1),
                "upstream producer never started",
            )

            # Deliberately do not consume the downstream stream.
            #
            # A bounded queue should apply backpressure and prevent
            # the worker from racing arbitrarily far ahead.
            time.sleep(0.1)

            with produced_lock:
                produced_before_close = produced

            asyncio.run(generator.aclose())

            deadline = time.monotonic() + 1.0

            while time.monotonic() < deadline:
                live_stream_threads = [
                    thread
                    for thread in threading.enumerate()
                    if (
                        thread.name == "mlx-chat-stream"
                        and thread.is_alive()
                    )
                ]

                if not live_stream_threads:
                    break

                time.sleep(0.01)

            self.assertFalse(
                [
                    thread
                    for thread in threading.enumerate()
                    if (
                        thread.name == "mlx-chat-stream"
                        and thread.is_alive()
                    )
                ],
                (
                    "backpressure test leaked an "
                    "mlx-chat-stream worker"
                ),
            )

            self.assertLessEqual(
                produced_before_close,
                128,
                (
                    "stream worker consumed too much upstream data "
                    "without downstream consumption; event queue "
                    "appears to be unbounded"
                ),
            )


    def test_cancelled_stream_does_not_emit_normal_done_event(self):
        import threading
        import time

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        release = threading.Event()

        class ControlledUpstream:
            def __init__(self):
                self.index = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                self.index += 1

                if self.index == 1:
                    return (
                        b'data: {"choices":[{"delta":'
                        b'{"content":"hello"}}]}\n\n'
                    )

                release.wait(timeout=2)

                return (
                    b'data: {"choices":[{"delta":'
                    b'{"content":"must-not-complete"}}]}\n\n'
                )

        request = agent_app.RuntimeChatRequest(
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            trace_id="trace-stream-cancel-002",
        )

        captured = []

        with mock.patch.object(
            agent_app,
            "ensure_model_for_role",
            return_value=runtime,
        ), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"PORT": 8000},
        ), mock.patch.object(
            agent_app.urllib.request,
            "urlopen",
            return_value=ControlledUpstream(),
        ):
            response = agent_app.runtime_chat_stream(request)
            generator = response.body_iterator

            async def read_first_and_close():
                try:
                    return await anext(generator)
                finally:
                    await generator.aclose()

            captured.append(
                asyncio.run(
                    read_first_and_close()
                )
            )

            release.set()

            deadline = time.monotonic() + 2

            while time.monotonic() < deadline:
                snapshot = observability.trace_snapshot(
                    "trace-stream-cancel-002"
                )

                calls = snapshot.get("calls", [])
                if (
                    calls
                    and calls[0].get("status") != "running"
                ):
                    break

                time.sleep(0.01)

        joined = "".join(captured)

        self.assertNotIn(
            "event: done",
            joined,
            "cancelled stream emitted normal done event",
        )

        snapshot = observability.trace_snapshot(
            "trace-stream-cancel-002"
        )

        self.assertEqual(
            snapshot["calls"][0]["status"],
            "failed",
        )
        self.assertEqual(
            snapshot["calls"][0].get("error_type"),
            "cancelled",
        )


    def test_runtime_chat_forwards_thinking_config(self):
        import json

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        class FakeResponse:
            status = 200
            headers = {
                "Content-Type": "application/json",
            }

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"ok"}}]}'
                )

        for config_value, expected in (
            ("false", False),
            ("true", True),
        ):
            captured = {}

            def fake_urlopen(request, timeout=900):
                captured["payload"] = json.loads(
                    request.data.decode("utf-8")
                )
                return FakeResponse()

            with mock.patch.object(
                agent_app,
                "ensure_model_for_role",
                return_value=runtime,
            ), mock.patch.object(
                agent_app,
                "load_config",
                return_value={
                    "PORT": 8000,
                    "THINKING": config_value,
                },
            ), mock.patch.object(
                agent_app.urllib.request,
                "urlopen",
                side_effect=fake_urlopen,
            ):
                request = agent_app.RuntimeChatRequest(
                    messages=[
                        {
                            "role": "user",
                            "content": "hello",
                        }
                    ],
                    stream=False,
                )

                agent_app.runtime_chat(request)

            self.assertEqual(
                captured["payload"]["chat_template_kwargs"][
                    "enable_thinking"
                ],
                expected,
            )

    def test_runtime_chat_stream_forwards_thinking_config(self):
        import asyncio
        import json

        runtime = {
            "resolved": {
                "repo": "owner/chat-model",
                "alias": "chat",
                "backend": "mlx_lm",
            },
        }

        captured_payloads = []

        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return iter([
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
                    b'data: [DONE]\n\n',
                ])

        for config_value, expected in (
            ("false", False),
            ("true", True),
        ):
            def fake_urlopen(request, timeout=900):
                payload = json.loads(
                    request.data.decode("utf-8")
                )
                captured_payloads.append(payload)
                return FakeStream()

            with mock.patch.object(
                agent_app,
                "ensure_model_for_role",
                return_value=runtime,
            ), mock.patch.object(
                agent_app,
                "load_config",
                return_value={
                    "PORT": 8000,
                    "THINKING": config_value,
                },
            ), mock.patch.object(
                agent_app.urllib.request,
                "urlopen",
                side_effect=fake_urlopen,
            ):
                request = agent_app.RuntimeChatRequest(
                    messages=[
                        {
                            "role": "user",
                            "content": "hello",
                        }
                    ],
                    trace_id=(
                        "trace-thinking-"
                        + config_value
                    ),
                )

                response = agent_app.runtime_chat_stream(request)
                generator = response.body_iterator

                async def consume():
                    chunks = []
                    async for chunk in generator:
                        chunks.append(chunk)
                    return chunks

                asyncio.run(consume())

            self.assertEqual(
                captured_payloads[-1][
                    "chat_template_kwargs"
                ]["enable_thinking"],
                expected,
            )


if __name__ == "__main__":
    unittest.main()
