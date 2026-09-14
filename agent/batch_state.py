"""File-backed persistence primitives for batch job state."""

import json
from pathlib import Path


def load_jobs(path):
    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}



def atomic_write_with(path, writer):
    """Atomically replace a file using a caller-provided temp-file writer."""
    path = Path(path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    try:
        writer(temporary_path)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_text(path, text, encoding="utf-8"):
    """Atomically replace a text file and always remove its temp file."""
    atomic_write_with(
        path,
        lambda temporary_path: temporary_path.write_text(
            text,
            encoding=encoding,
        ),
    )


def save_jobs(directory, path, jobs):
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    atomic_write_text(
        path,
        json.dumps(
            jobs,
            ensure_ascii=False,
            indent=2,
        ),
    )


def checkpoint_directory(root, job_id):
    path = root / job_id
    path.mkdir(
        parents=True,
        exist_ok=True,
    )
    return path


def checkpoint_path(directory, chunk_index):
    return directory / f"{int(chunk_index):08d}.txt"


def completed_checkpoints(directory):
    completed = []

    for path in directory.glob("*.txt"):
        try:
            completed.append(
                int(path.stem)
            )
        except ValueError:
            continue

    return sorted(completed)
