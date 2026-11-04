"""Private SQLite connections with deterministic transaction/FD cleanup."""
import os
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def connect(path, *, timeout):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Do not briefly create a group/world-readable database before chmod.
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    connection = sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute('PRAGMA foreign_keys=ON')
        return connection
    except BaseException:
        connection.close()
        raise
