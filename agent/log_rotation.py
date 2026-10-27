"""Byte-bounded service output, including native writes to stdout/stderr."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sys
import threading
import time


MAX_LOG_BYTES = 16 * 1024 * 1024
BACKUPS = 3


class RotatingLog:
    """One writer per log; rename rotation never truncates an open inode.

    An existing oversized log is preserved once as a legacy archive, outside
    automatic retention. Only numbered backups created by this writer expire.
    """

    def __init__(self, path, *, max_bytes=MAX_LOG_BYTES, backups=BACKUPS):
        if max_bytes < 1 or backups < 1:
            raise ValueError("Positive log size and retention are required")
        self.path = Path(path)
        self.max_bytes, self.backups = max_bytes, backups
        self.handle = None
        self.lock = self.path.with_name(self.path.name + ".rotate.lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.is_symlink():
                raise ValueError("Service log must not be a symlink")
            if self.path.exists() and self.path.stat().st_size > max_bytes:
                self.path.rename(self.path.with_name(self.path.name + f".legacy-{time.time_ns()}"))
            self._open()
        except BaseException:
            self.lock.close()
            raise

    def _open(self):
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.handle = os.fdopen(fd, "ab", buffering=0)
        self.size = os.fstat(fd).st_size

    def _rotate(self):
        self.handle.close()
        self.path.with_name(self.path.name + f".{self.backups}").unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(self.path.name + f".{index}")
            if source.exists():
                source.rename(self.path.with_name(self.path.name + f".{index + 1}"))
        self.path.rename(self.path.with_name(self.path.name + ".1"))
        self._open()

    def write(self, data):
        data = memoryview(data)
        while data:
            if self.size >= self.max_bytes:
                self._rotate()
            written = self.handle.write(data[:self.max_bytes - self.size])
            if not written:
                raise OSError("Service log write made no progress")
            self.size += written
            data = data[written:]

    def close(self):
        try:
            if self.handle is not None:
                self.handle.close()
        finally:
            self.lock.close()


@contextmanager
def capture_output(fd, path, **options):
    """Keep the service PID/signals unchanged; drain a bounded OS pipe in a thread."""
    log = RotatingLog(path, **options)
    saved = os.dup(fd)
    read_fd, write_fd = os.pipe()

    def drain():
        failed = False
        try:
            while chunk := os.read(read_fd, 65536):
                if not failed:
                    try:
                        log.write(chunk)
                    except OSError:
                        # Disk errors must not fill the pipe and deadlock jobs.
                        failed = True
                        os.write(saved, b"MLX service log write failed; output is being drained.\n")
        finally:
            os.close(read_fd)
            log.close()

    thread = threading.Thread(target=drain, name=f"mlx-log-{fd}", daemon=True)
    try:
        thread.start()
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        os.close(saved)
        log.close()
        raise
    try:
        try:
            os.dup2(write_fd, fd)
        finally:
            os.close(write_fd)
        yield
    finally:
        stream = sys.stdout if fd == 1 else sys.stderr
        try:
            stream.flush()
        finally:
            os.dup2(saved, fd)
            # Descendants may still hold their copy of the pipe. Never hang exit.
            thread.join(timeout=2)
            if not thread.is_alive():
                os.close(saved)
