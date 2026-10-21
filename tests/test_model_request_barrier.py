import threading
import unittest

from model_request_barrier import (
    ModelBusyError,
    ModelRequestBarrier,
)


class ModelRequestBarrierTests(unittest.TestCase):
    def test_initially_idle(self):
        self.assertEqual(
            ModelRequestBarrier().snapshot()["active_requests"], 0
        )

    def test_tracks_request(self):
        barrier = ModelRequestBarrier()
        with barrier.request():
            self.assertEqual(
                barrier.snapshot()["active_requests"], 1
            )
        self.assertEqual(
            barrier.snapshot()["active_requests"], 0
        )

    def test_unload_when_idle(self):
        barrier = ModelRequestBarrier()
        with barrier.unload():
            self.assertTrue(barrier.snapshot()["unloading"])
        self.assertFalse(barrier.snapshot()["unloading"])

    def test_unload_refuses_active_request(self):
        barrier = ModelRequestBarrier()
        with barrier.request():
            with self.assertRaises(ModelBusyError):
                with barrier.unload(timeout=0.01):
                    pass
        self.assertFalse(barrier.snapshot()["unloading"])

    def test_exception_releases_request(self):
        barrier = ModelRequestBarrier()
        with self.assertRaises(ValueError):
            with barrier.request():
                raise ValueError("test")
        self.assertEqual(barrier.snapshot()["active_requests"], 0)

    def test_exception_releases_unload(self):
        barrier = ModelRequestBarrier()
        with self.assertRaises(ValueError):
            with barrier.unload():
                raise ValueError("test")
        self.assertFalse(barrier.snapshot()["unloading"])

    def test_new_request_waits_for_unload(self):
        barrier = ModelRequestBarrier()
        started = threading.Event()
        completed = threading.Event()

        def worker():
            started.set()
            with barrier.request():
                completed.set()

        with barrier.unload():
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(completed.wait(0.05))

        self.assertTrue(completed.wait(1))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
