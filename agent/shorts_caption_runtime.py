"""Optional word-timed caption runtime for Shorts.

Before FFmpeg composition, the generated voiceover is aligned by the local
speech service. Alignment JSON is cached next to the Short job. If alignment is
unavailable, composition deliberately falls back to the existing scene-timed
ASS captions rather than failing the whole Short.
"""

import hashlib
import json
import os
from pathlib import Path

from agent import batch_state, service_proxy, shorts_jobs
from agent.shorts_captions import animated_subtitles_for_words
from agent.shorts_planner import ShortProject


_ORIGINAL_RUN_COMPOSE = None
_INSTALLED = False


def _alignment_output_path(job_id):
    return shorts_jobs.SHORTS_DIRECTORY / job_id / "caption-alignment.json"


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _alignment_identity(project, tts_path):
    narration = shorts_jobs.narration_for_project(project)
    return {
        "audio_sha256": _sha256_file(tts_path),
        "text_sha256": hashlib.sha256(narration.encode("utf-8")).hexdigest(),
    }


def _load_cached_alignment(path, identity):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if any(data.get(key) != value for key, value in identity.items()):
        return None
    if not isinstance(data.get("words"), list) or not data["words"]:
        return None
    return data


def _request_alignment(project, tts_path):
    url = os.environ.get(
        "SPEECH_SERVICE_URL", "http://127.0.0.1:8050",
    ).rstrip("/") + "/v1/audio/align"
    payload = {
        "source_path": str(tts_path),
        "text": shorts_jobs.narration_for_project(project),
        "language": project.language,
    }
    response = service_proxy.forward(
        url,
        json.dumps(payload).encode("utf-8"),
        timeout=900,
    )
    if response.status_code >= 400:
        detail = bytes(response.body or b"").decode("utf-8", errors="replace")
        raise RuntimeError(detail[:2000] or "caption alignment failed")
    try:
        data = json.loads(bytes(response.body or b"").decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("caption alignment returned invalid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        raise RuntimeError("caption alignment returned no word timings")
    if not data["words"]:
        raise RuntimeError("caption alignment returned empty word timings")
    return data


def _alignment_for_job(job_id, job):
    project = ShortProject.model_validate(job["project"])
    tts_path = Path(str(job.get("tts_path") or ""))
    if (
        not project.subtitles_enabled
        or not project.voice_enabled
        or not tts_path.is_file()
        or tts_path.stat().st_size <= 0
    ):
        return None

    identity = _alignment_identity(project, tts_path)
    output_path = _alignment_output_path(job_id)
    cached = _load_cached_alignment(output_path, identity)
    if cached is not None:
        shorts_jobs._update_job(
            job_id,
            caption_alignment_status="completed",
            caption_alignment_path=str(output_path),
            caption_word_count=len(cached.get("words") or []),
            caption_alignment_error=None,
        )
        return cached

    shorts_jobs._update_job(
        job_id,
        caption_alignment_status="running",
        caption_alignment_error=None,
    )
    data = _request_alignment(project, tts_path)
    stored = dict(data)
    stored.update(identity)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch_state.atomic_write_text(
        output_path,
        json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    shorts_jobs._update_job(
        job_id,
        caption_alignment_status="completed",
        caption_alignment_path=str(output_path),
        caption_word_count=len(stored.get("words") or []),
        caption_alignment_error=None,
    )
    return stored


def _patched_run_compose(job_id, request_fn, compose_fn):
    job = shorts_jobs.get_short_job(job_id)
    project = ShortProject.model_validate(job["project"])
    aligned_ass = None

    if project.subtitles_enabled and project.voice_enabled:
        try:
            alignment = _alignment_for_job(job_id, job)
            if alignment is not None:
                aligned_ass = animated_subtitles_for_words(project, alignment)
                if not aligned_ass:
                    raise RuntimeError("caption alignment contained no usable timings")
        except Exception as exc:
            shorts_jobs._update_job(
                job_id,
                caption_alignment_status="fallback",
                caption_alignment_error=str(exc)[:2000],
            )
            aligned_ass = None
    elif project.subtitles_enabled:
        shorts_jobs._update_job(
            job_id,
            caption_alignment_status="fallback",
            caption_alignment_error="voiceover disabled; using scene-timed captions",
        )
    else:
        shorts_jobs._update_job(
            job_id,
            caption_alignment_status="disabled",
            caption_alignment_error=None,
        )

    if aligned_ass is None:
        return _ORIGINAL_RUN_COMPOSE(job_id, request_fn, compose_fn)

    def compose_with_aligned_captions(command, *, cwd, cancel_check, timeout):
        subtitle_path = Path(cwd) / "subtitles.ass"
        batch_state.atomic_write_text(subtitle_path, aligned_ass)
        return compose_fn(
            command,
            cwd=cwd,
            cancel_check=cancel_check,
            timeout=timeout,
        )

    return _ORIGINAL_RUN_COMPOSE(
        job_id,
        request_fn,
        compose_with_aligned_captions,
    )


def install_runtime():
    """Install the compose wrapper exactly once."""
    global _INSTALLED, _ORIGINAL_RUN_COMPOSE
    if _INSTALLED:
        return
    _ORIGINAL_RUN_COMPOSE = shorts_jobs._run_compose
    shorts_jobs._run_compose = _patched_run_compose
    _INSTALLED = True
