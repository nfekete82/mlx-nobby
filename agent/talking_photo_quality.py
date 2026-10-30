"""High-quality Talking Photo jobs using LTX-2.5 MLX Audio-to-Video."""

from __future__ import annotations

import ai_lifecycle_gate

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time

from fastapi import HTTPException

from agent import talking_photo, talking_photo_ltx, talking_photo_motion, talking_photo_longform, talking_photo_continuity, talking_photo_person_focus
from agent.talking_photo_audio import _analyze_wav


AUDIO_DEBUG_ROOT = talking_photo.ROOT / "audio-debug"


def direct_provider_health() -> dict:
    """Report native LTX A2V availability without requiring MuseTalk."""
    return talking_photo_ltx.provider_health()


def provider_health() -> dict:
    health = direct_provider_health()
    if health["ready"]:
        lipsync = talking_photo.provider_health()
        health["lipsync_provider"] = lipsync["provider"]
        if not lipsync["ready"]:
            health.update(ready=False, detail=lipsync["detail"],
                          setup_command=lipsync["setup_command"])
    return health


def generate(
    job_id: str,
    *args,
    apply_lipsync: bool = True,
    **kwargs,
) -> tuple[bytes, dict]:
    """Render native LTX A2V and optionally apply the final MuseTalk lip pass."""
    video, details = talking_photo_ltx.generate(job_id, *args, **kwargs)
    if not apply_lipsync:
        details["lipsync"] = None
        details["engine"] = ("ltx-distilled" if details.get("a2v_mode") == "distilled"
                             else "ltx-max" if details.get("stage_1_steps") == 30 else "ltx")
        return video, details

    bundle = Path(details["debug_dir"]) if details.get("debug_dir") else None
    if bundle is not None:
        # A failed/cancelled lip pass must not leave a native output.mp4 that
        # the debug CLI would mistake for a completed final result on resume.
        (bundle / "output.mp4").rename(bundle / "ltx-output.mp4")
    cancelled = kwargs["cancelled"]
    if cancelled():
        raise talking_photo_ltx.QualityCancelled()
    # Reuse the exact padded WAV LTX loaded, preserving its onset and frame span.
    conditioning = Path(details["audio_path"]).read_bytes()
    digest = hashlib.sha256(conditioning).hexdigest()
    if digest != details["conditioning_audio_sha256"]:
        raise RuntimeError("Talking-Photo-Conditioning-WAV wurde verändert")
    update = kwargs.get("update")
    if update is not None:
        update(phase="lipsync", progress=0.9)
    started = time.monotonic()
    native_digest = hashlib.sha256(video).hexdigest()
    video, timing = talking_photo._musetalk_lipsync(
        video, conditioning, "quality-" + native_digest[:24],
    )
    if cancelled():
        raise talking_photo_ltx.QualityCancelled()
    details["lipsync"] = {
        "provider": "musetalk-mac", "conditioning_audio_sha256": digest,
        "input_video_sha256": native_digest,
        "timing": timing, "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    details["a2v_elapsed_seconds"] = details["elapsed_seconds"]
    details["elapsed_seconds"] = round(details["elapsed_seconds"] + details["lipsync"]["elapsed_seconds"], 3)
    if bundle is not None:
        (bundle / "output.mp4").write_bytes(video)
        (bundle / "render.json").write_text(
            json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return video, details


def tts_language(language: str) -> str:
    """Qwen CustomVoice expects language names, not ISO UI codes.

    Keep this translation local to Talking Photo; it changes no audio samples
    or shared Speech-Service behavior. Clone generation ignores this field.
    """
    names = {
        "de": "German", "en": "English", "fr": "French", "es": "Spanish",
        "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
        "ru": "Russian", "zh": "Chinese",
    }
    value = str(language).strip()
    return names.get(value.lower().split("-", 1)[0], value)


def _persist_audio_diagnostics(
    job_id: str,
    voice: str | None,
    language: str,
    profile_name: str,
    tts_speed: float,
    postprocess_tempo: float,
    target_leading_silence_ms: float | None,
    wav_bytes: bytes,
    stats: dict,
) -> dict:
    """Keep the source WAV; the renderer separately retains its padded conditioning WAV."""
    AUDIO_DEBUG_ROOT.mkdir(parents=True, exist_ok=True)
    label = str(voice or "default").strip() or "default"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "voice"
    stem = f"{job_id}-{slug[:48]}"
    wav_path = AUDIO_DEBUG_ROOT / f"{stem}.wav"
    json_path = AUDIO_DEBUG_ROOT / f"{stem}.json"
    wav_path.write_bytes(wav_bytes)
    metadata = {
        "job_id": job_id,
        "voice": voice,
        "language": language,
        "profile": profile_name,
        "tts_speed": tts_speed,
        "postprocess_tempo": postprocess_tempo,
        "target_leading_silence_ms": target_leading_silence_ms,
        "wav_path": str(wav_path),
        "stats": stats,
        "stage": "source-before-padding",
    }
    json_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "wav_path": str(wav_path),
        "metadata_path": str(json_path),
        "profile": profile_name,
        "tts_speed": tts_speed,
        "postprocess_tempo": postprocess_tempo,
        "target_leading_silence_ms": target_leading_silence_ms,
        "stats": stats,
    }


def _generate_longform(
    job_id: str,
    image: bytes,
    image_suffix: str,
    wav: bytes,
    work: Path,
    *,
    debug_dir: Path | None,
    cancelled,
    update,
    apply_lipsync: bool,
    distilled: bool,
    stage1_steps: int | None = None,
    person_focus: dict | None = None,
    scene_motion: str = "none",
) -> tuple[bytes, dict]:
    """Render <=18-second speech pieces sequentially and mux the uncut source.

    A separate working directory isolates each LTX runner. No chunk's padded
    audio is ever used in the assembled MP4. The short-clip path is untouched.
    """
    segments = talking_photo_longform.split_at_pauses(wav)
    if len(segments) < 2:
        raise RuntimeError("Longform erwartet mindestens zwei Abschnitte")
    rendered_files: list[Path] = []
    rendered_details: list[dict] = []
    continuity_enabled = talking_photo_continuity.enabled()
    began = time.monotonic()
    for index, segment in enumerate(segments):
        if cancelled():
            raise talking_photo_ltx.QualityCancelled()
        part_work = work / f"part-{index+1:02d}"
        part_debug = debug_dir / f"part-{index+1:02d}" if debug_dir else None
        segment_image, segment_suffix = image, image_suffix
        reference = {"source": "original", "enabled": continuity_enabled}
        if index > 0 and continuity_enabled:
            # Recondition the next LTX render on the last *visible* frame of
            # the previous one, not the original portrait or its padded tail.
            # If video decoding fails, keep the existing stable fallback.
            try:
                segment_image = talking_photo_continuity.extract_tail_frame(
                    rendered_files[-1], segments[index - 1].video_frames,
                    work / f"continuation-{index+1:02d}.png",
                    cancelled=cancelled,
                )
                segment_suffix = ".png"
                reference = {
                    "source": "previous-content-frame",
                    "enabled": True,
                    "after_segment": index,
                    "sha256": hashlib.sha256(segment_image).hexdigest(),
                }
            except talking_photo_ltx.QualityCancelled:
                raise
            except (RuntimeError, OSError, ValueError) as exc:
                reference = {
                    "source": "original-fallback", "enabled": True,
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
        def part_update(*, phase="quality", progress=0.25, **kwargs):
            # Coarse progress: account for completed parts, never claim completion
            # while a later MLX render or the final mux remains.
            fraction = min(1.0, max(0.0, (progress - 0.25) / 0.65))
            update(phase=phase, progress=min(0.91, 0.20 + 0.69 * (index + fraction) / len(segments)))
        video, details = generate(
            job_id, segment_image, segment_suffix, segment.wav, segment.duration_seconds,
            part_work, debug_dir=part_debug, cancelled=cancelled,
            update=part_update, apply_lipsync=apply_lipsync, distilled=distilled,
            stage1_steps=stage1_steps, person_focus=person_focus, scene_motion=scene_motion,
        )
        if cancelled():
            raise talking_photo_ltx.QualityCancelled()
        part_work.mkdir(parents=True, exist_ok=True)
        output_path = part_work / "rendered.mp4"
        output_path.write_bytes(video)
        rendered_files.append(output_path)
        rendered_details.append({
            "segment": segment.index,
            "audio_seconds": round(segment.duration_seconds, 4),
            "audio_start_seconds": round(segment.start_sample / 16000, 4),
            "video_frames": segment.video_frames,
            "seed": details.get("seed"),
            "elapsed_seconds": details.get("elapsed_seconds"),
            "mode": details.get("a2v_mode"),
            "stage_1_steps": details.get("stage_1_steps"),
            "reference": reference,
        })
        update(phase="quality", progress=0.20 + 0.69 * len(rendered_files) / len(segments))

    if cancelled():
        raise talking_photo_ltx.QualityCancelled()
    update(phase="quality", progress=0.92)
    result, assembly = talking_photo_longform.assemble(
        wav, segments, rendered_files, work / "assembly", cancelled=cancelled,
    )
    if cancelled():
        raise talking_photo_ltx.QualityCancelled()
    summary = {
        "provider": "ltx-2.5-mlx-a2v",
        "engine": ("ltx-distilled" if distilled else "ltx-max" if stage1_steps == 30
                   else "ltx" if not apply_lipsync else "quality"),
        "a2v_mode": "distilled" if distilled else "classic",
        "stage_1_steps": 8 if distilled else (stage1_steps or 15),
        "stage_2_steps": 3,
        "longform": True,
        "continuity": {
            "enabled": continuity_enabled,
            "method": "previous last visible frame as next reference",
            "applied": sum(
                item["reference"]["source"] == "previous-content-frame"
                for item in rendered_details
            ),
            "fallbacks": sum(
                item["reference"]["source"] == "original-fallback"
                for item in rendered_details
            ),
        },
        "chunks": rendered_details,
        "assembly": assembly,
        "audio_seconds": assembly["audio_seconds"],
        "elapsed_seconds": round(time.monotonic() - began, 3),
        "source_audio_sha256": assembly["source_audio_sha256"],
        "lipsync": "musetalk-mac" if apply_lipsync else None,
    }
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "longform.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (debug_dir / "output.mp4").write_bytes(result)
    return result, summary


def _run_quality_job(job_id: str, image: bytes, image_suffix: str, request_payload: dict) -> None:
    ltx_only = bool(request_payload.pop("_ltx_only", False))
    distilled = bool(request_payload.pop("_distilled", False))
    stage1_steps = request_payload.pop("_stage1_steps", None)
    engine = "ltx-distilled" if distilled else ("ltx-max" if stage1_steps == 30 else "ltx" if ltx_only else "quality")
    work = talking_photo.ROOT / "work" / job_id
    output = talking_photo.OUTPUT / f"{job_id}.mp4"
    work.mkdir(parents=True, exist_ok=True)
    try:
        with talking_photo._render_lock:
            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            talking_photo._update_job(
                job_id,
                status="tts",
                phase="tts",
                started_at=time.time(),
                error=None,
            )
            tts_payload = {
                "input": request_payload["text"],
                "language": tts_language(request_payload["language"]),
            }
            voice = request_payload.get("voice")
            requested_speed = float(request_payload.get("speed", 1.0))
            profile_name = "standard"
            target_leading_silence_ms = None
            tts_speed = requested_speed
            postprocess_tempo = 1.0
            if voice:
                tts_payload["voice"] = voice
                profile_name = "native"
            # Only an explicitly requested speed is forwarded. No voice-specific
            # timing, second atempo pass, silence trimming or duration matching.
            if tts_speed != 1.0:
                tts_payload["speed"] = tts_speed
            audio = talking_photo._request_tts(tts_payload)

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            wav = talking_photo._audio_to_wav(audio, work)
            audio_seconds = talking_photo_motion.wav_duration_seconds(wav)
            audio_stats = _analyze_wav(wav)
            audio_diagnostics = _persist_audio_diagnostics(
                job_id,
                voice,
                request_payload["language"],
                profile_name,
                tts_speed,
                postprocess_tempo,
                target_leading_silence_ms,
                wav,
                audio_stats,
            )
            talking_photo._update_job(
                job_id,
                status="motion",
                phase="quality",
                progress=0.2,
                audio_diagnostics=audio_diagnostics,
            )
            debug_dir = talking_photo_ltx.debug_directory(job_id)
            if debug_dir is not None:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / "tts-output.bin").write_bytes(audio)
                (debug_dir / "request.json").write_text(
                    json.dumps({"tts_request": tts_payload, "voice": voice,
                                "language": request_payload["language"]},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                )
            try:
                if audio_seconds > talking_photo_longform.MAX_LONGFORM_SECONDS:
                    raise RuntimeError(
                        f"Talking Photo 2.0 unterstützt maximal {talking_photo_longform.MAX_LONGFORM_SECONDS:g} Sekunden Audio."
                    )
                if audio_seconds > talking_photo_ltx.MAX_AUDIO_SECONDS:
                    if request_payload.get("lead_in_ms", 0):
                        raise RuntimeError("Audiovorlauf ist für Longform nicht verfügbar")
                    video, details = _generate_longform(
                        job_id, image, image_suffix, wav, work,
                        debug_dir=debug_dir,
                        cancelled=lambda: talking_photo._cancelled(job_id),
                        update=lambda **changes: talking_photo._update_job(job_id, **changes),
                        apply_lipsync=not ltx_only,
                        distilled=distilled,
                        stage1_steps=stage1_steps,
                        person_focus=request_payload.get("person_focus"),
                        scene_motion=request_payload.get("scene_motion", "none"),
                    )
                else:
                    video, details = generate(
                        job_id,
                        image,
                        image_suffix,
                        wav,
                        audio_seconds,
                        work,
                        debug_dir=debug_dir,
                        cancelled=lambda: talking_photo._cancelled(job_id),
                        update=lambda **changes: talking_photo._update_job(job_id, **changes),
                        apply_lipsync=not ltx_only,
                        lead_in_ms=request_payload.get("lead_in_ms", 0),
                        distilled=distilled,
                        stage1_steps=stage1_steps,
                        person_focus=request_payload.get("person_focus"),
                        scene_motion=request_payload.get("scene_motion", "none"),
                    )
            except talking_photo_ltx.QualityCancelled as exc:
                raise talking_photo.TalkingPhotoCancelled() from exc

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            talking_photo.OUTPUT.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".mp4.tmp")
            temporary.write_bytes(video)
            os.replace(temporary, output)
            talking_photo._update_job(
                job_id,
                status="completed",
                phase="completed",
                progress=1.0,
                result={
                    "id": job_id,
                    "mime_type": "video/mp4",
                    "size_bytes": len(video),
                    "provider": "ltx-2.5-mlx-a2v",
                    "lipsync_provider": None if ltx_only else "musetalk-mac",
                    "engine": engine,
                    "person_focus": request_payload.get("person_focus"),
                    "speaker_selection": "prompt-guided" if request_payload.get("person_focus") else None,
                    "a2v_mode": "distilled" if distilled else "classic",
                    "stage_1_steps": 8 if distilled else (stage1_steps or 15),
                    "stage_2_steps": 3,
                    "motion": "audio-conditioned",
                    "scene_motion": request_payload.get("scene_motion", "none"),
                    "motion_provider": "ltx-2.5-mlx-a2v",
                    "audio_diagnostics": audio_diagnostics,
                    "lead_in_ms": request_payload.get("lead_in_ms", 0),
                    "timing": details,
                    "longform": bool(details.get("longform", False)),
                    "segments": len(details.get("chunks", [])) or 1,
                    "video_url": f"/api/talking-photo/videos/{job_id}",
                },
                finished_at=time.time(),
                error=None,
            )
    except talking_photo.TalkingPhotoCancelled:
        output.unlink(missing_ok=True)
        talking_photo._update_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            result=None,
            error=None,
            finished_at=time.time(),
        )
    except Exception as exc:
        output.unlink(missing_ok=True)
        talking_photo._update_job(
            job_id,
            status="failed",
            phase="failed",
            result=None,
            error=str(exc)[-4000:],
            finished_at=time.time(),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


@ai_lifecycle_gate.admitted
def create_job(payload: dict, *, ltx_only: bool = False, distilled: bool = False,
               stage1_steps: int | None = None) -> dict:
    if distilled and not ltx_only:
        raise ValueError("Distilled ist derzeit nur mit LTX direkt verfügbar")
    if stage1_steps not in (None, 30) or (stage1_steps is not None and (distilled or not ltx_only)):
        raise ValueError("Maximale Qualität ist nur mit LTX direkt und 30 Schritten verfügbar")
    health = direct_provider_health() if ltx_only else provider_health()
    if not health["ready"]:
        raise HTTPException(
            503,
            health.get("detail") or "LTX Quality ist nicht bereit. ./scripts/setup-ltx-video-mlx ausführen.",
        )
    image, extension = talking_photo.decode_image_data_url(payload["image_data_url"])
    if payload.get("person_focus") is not None:
        try:
            talking_photo_person_focus.validate_focus(payload["person_focus"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    job_id = secrets.token_hex(12)
    now = time.time()
    job = {
        "id": job_id,
        "kind": "talking_photo",
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "voice": payload.get("voice"),
        "language": payload["language"],
        "speed": payload.get("speed", 1.0),
        "motion": "audio-conditioned",
        "scene_motion": payload.get("scene_motion", "none"),
        "engine": "ltx-distilled" if distilled else ("ltx-max" if stage1_steps == 30 else "ltx" if ltx_only else "quality"),
        "a2v_mode": "distilled" if distilled else "classic",
        "stage_1_steps": 8 if distilled else (stage1_steps or 15),
        "stage_2_steps": 3,
        "person_focus": payload.get("person_focus"),
        "speaker_selection": "prompt-guided" if payload.get("person_focus") else None,
        "lead_in_ms": payload.get("lead_in_ms", 0),
        "text_characters": len(payload["text"]),
        "provider": "ltx-2.5-mlx-a2v",
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    with talking_photo._jobs_lock:
        talking_photo._write_job(job)
    request_payload = dict(payload)
    request_payload["_ltx_only"] = ltx_only
    request_payload["_distilled"] = distilled
    if stage1_steps is not None:
        request_payload["_stage1_steps"] = stage1_steps
    thread = threading.Thread(
        target=_run_quality_job,
        args=(job_id, image, extension, request_payload),
        daemon=True,
        name=f"talking-photo-{'ltx' if ltx_only else 'quality'}-{job_id}",
    )
    thread.start()
    return job
