"""File-backed persistence primitives for batch job state."""

import json


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


def save_jobs(directory, path, jobs):
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(
            jobs,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary_path.replace(path)


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
