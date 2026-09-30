import threading
import unittest
from unittest import mock

import video_providers


class _FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.terminated = True
        self.returncode = -9


class _FakeLog:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class LTXWarmRuntimeTests(unittest.TestCase):
    def setUp(self):
        with video_providers._RUNTIME_LOCK:
            video_providers._WARM_RUNTIME = None
            video_providers._WARM_TIMER = None
            video_providers._WARM_GENERATION = 0

    def tearDown(self):
        video_providers.shutdown_warm_runtime()

    def test_consecutive_video_jobs_reuse_warm_ltx_runtime(self):
        runtime = (_FakeProcess(), _FakeLog())
        with mock.patch.object(
            video_providers,
            "_start_runtime",
            return_value=runtime,
        ) as start, mock.patch.object(
            video_providers,
            "_chat_runtime_loaded",
            return_value=True,
        ), mock.patch.object(
            video_providers.threading,
            "Timer",
            _FakeTimer,
        ):
            first, reused_first = video_providers._acquire_runtime(
                threading.Event()
            )
            video_providers.unload(first)
            status = video_providers.warm_runtime_status()

            second, reused_second = video_providers._acquire_runtime(
                threading.Event()
            )

        self.assertIs(first, second)
        self.assertFalse(reused_first)
        self.assertTrue(reused_second)
        self.assertTrue(status["loaded"])
        start.assert_called_once()

    def test_video_runtime_is_not_kept_warm_when_chat_was_evicted(self):
        runtime = (_FakeProcess(), _FakeLog())
        with mock.patch.object(
            video_providers,
            "_start_runtime",
            return_value=runtime,
        ), mock.patch.object(
            video_providers,
            "_chat_runtime_loaded",
            return_value=False,
        ):
            acquired, _ = video_providers._acquire_runtime(threading.Event())
            video_providers.unload(acquired)

        self.assertTrue(runtime[0].terminated)
        self.assertTrue(runtime[1].closed)
        self.assertFalse(video_providers.warm_runtime_status()["loaded"])

    def test_failed_runtime_can_be_force_discarded(self):
        runtime = (_FakeProcess(), _FakeLog())
        with mock.patch.object(
            video_providers,
            "_start_runtime",
            return_value=runtime,
        ):
            acquired, _ = video_providers._acquire_runtime(threading.Event())
            video_providers.discard_runtime(acquired)

        self.assertTrue(runtime[0].terminated)
        self.assertTrue(runtime[1].closed)
        self.assertFalse(video_providers.warm_runtime_status()["loaded"])


if __name__ == "__main__":
    unittest.main()
