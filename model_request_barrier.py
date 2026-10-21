"""Thread-safe request/unload barrier for MLX model lifecycles.

Pure coordination primitive; no model operations or server integration.
"""

import threading
import time
from contextlib import contextmanager


class ModelBusyError(RuntimeError):
    pass


class ModelRequestBarrier:
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._active = 0
        self._pending = 0
        self._unloading = False

    def snapshot(self):
        with self._condition:
            return {
                "active_requests": self._active,
                "pending_requests": self._pending,
                "unloading": self._unloading,
            }

    @contextmanager
    def request(self):
        with self._condition:
            self._pending += 1
            try:
                while self._unloading:
                    self._condition.wait()
                self._active += 1
            finally:
                self._pending -= 1

        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    @contextmanager
    def unload(self, timeout=10):
        deadline = time.monotonic() + timeout

        with self._condition:
            while self._unloading:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelBusyError("another unload is active")
                self._condition.wait(remaining)

            self._unloading = True

            try:
                while self._active:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ModelBusyError("active requests remain")
                    self._condition.wait(remaining)
            except BaseException:
                self._unloading = False
                self._condition.notify_all()
                raise

        try:
            yield
        finally:
            with self._condition:
                self._unloading = False
                self._condition.notify_all()
