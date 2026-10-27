"""Bounded log reads, independent of the size of long-running service logs."""

import os


MAX_TAIL_BYTES = 1024 * 1024
BLOCK_BYTES = 64 * 1024


def read_log_tail(path, limit, *, strip_nulls=False):
    """Return recent lines using at most 1 MiB of input per file.

    A byte-capped tail omits its incomplete first line when other lines exist.
    For a single oversized line, return its bounded suffix instead. Decode only
    after joining blocks so UTF-8 sequences split across reads remain intact.
    """
    if limit <= 0:
        return []

    chunks = []
    newlines = 0
    remaining = MAX_TAIL_BYTES
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        while position > 0 and remaining > 0 and newlines <= limit:
            size = min(position, remaining, BLOCK_BYTES)
            position -= size
            handle.seek(position)
            chunk = handle.read(size)
            chunks.append(chunk)
            newlines += chunk.count(b"\n")
            remaining -= size

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    if strip_nulls:
        content = content.replace("\x00", "")
    lines = content.splitlines()
    if position > 0 and len(lines) > 1:
        lines = lines[1:]
    return lines[-limit:]
