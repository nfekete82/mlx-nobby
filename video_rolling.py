"""Experimental 540p/720p, 10-second LTX rolling-window continuation.

The native distilled extend CLI carries the last 25 decoded video frames and
audio into a short denoising window. Do not feed it the accumulated movie:
extract exactly 25 frames, extend by 48 frames (6 LTX latents), keep only
the newly generated 48 frames and append them to verified disk checkpoints.

Default segmented and normal direct-video paths remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import ai_lifecycle_gate as gate
import runtime_coordinator
import video_long
import video_registry
from video_providers import ProviderCancelled, _probe_video
from video_providers_mlx import shutdown_warm_runtime
from video_segmented import FFMPEG, _ffmpeg

FPS = 24
CONTEXT_FRAMES = 25  # 1 second of motion + inclusive end frame
EXTEND_LATENTS = 6
NEW_FRAMES = 8 * EXTEND_LATENTS  # 2 seconds per extension
CLIP_CRF = 0  # Lossless decoded YUV transport; do not degrade the next VAE input.
OUTPUT_CRF = 10  # Encode once to browser-compatible H.264 after assembling the timeline.
CONDITIONING_VERSION = 3
SEGMENT_SECONDS = (6, 2, 2)
RESOLUTIONS = frozenset({"540p", "720p"})
STRATEGY = "rolling-extend-25f-v1"
# This integration forwards video and prompt only. Native image guides exist
# in 0.18 but are pose-bearing anchors, not facial embeddings; leave them off
# until their motion and memory cost have been validated in a separate pilot.
# Positive, short guidance preserves natural expressions and blinking.
INITIAL_FACE_GUIDANCE = (
    "Keep the same person as in the source image with consistent facial proportions, "
    "eye shape and spacing, eyelids, iris placement, skin texture and hairstyle. "
    "Allow gentle natural eye movements, blinking and facial expressions. "
)
EXTEND_FACE_GUIDANCE = (
    "Continue the same person's natural movement from the input video. "
    "Maintain consistent facial proportions, eye shape and spacing, eyelids, "
    "iris placement, skin texture and hairstyle with natural blinking. "
)
MINIMAL_INITIAL_FACE_GUIDANCE = (
    "Maintain the same person's identity and natural facial proportions. "
    "Allow realistic blinking, relaxed eye movement, natural smiling and subtle expressions. "
)
MINIMAL_EXTEND_FACE_GUIDANCE = (
    "Continue the same person's natural movement and facial identity from the video. "
    "Allow realistic blinking, relaxed eye movement and subtle expressions. "
)
WARNING = (
    "Experimentelles Rolling-Window-Extend: 25 Frames Bewegungs- und Audiokontext "
    "statt nur eines Standbilds. I2V-Gesichtshinweise sind kein harter Identity Lock; "
    "Farb- und Identitätskonstanz sind nicht garantiert."
)


def needed(params):
    return params.get("continuation_mode", "segmented") == "rolling"


def _face_guidance_mode(params):
    """Explicit rolling-only text choice; None preserves all previous defaults."""
    if not params.get("first_frame"):
        return "off"
    explicit = params.get("face_guidance")
    if explicit is None:
        return "full" if params.get("identity_lock", True) else "off"
    if explicit not in {"off", "minimal", "full"}:
        raise ValueError("Unbekannter Rolling-Gesichtshinweismodus")
    return explicit


def _face_prompt(params, *, extension):
    """Only change positive text conditioning, never the native first-frame anchor."""
    prompt = params["prompt"]
    mode = _face_guidance_mode(params)
    if mode == "off":
        return prompt
    if mode == "minimal":
        guidance = MINIMAL_EXTEND_FACE_GUIDANCE if extension else MINIMAL_INITIAL_FACE_GUIDANCE
    else:
        guidance = EXTEND_FACE_GUIDANCE if extension else INITIAL_FACE_GUIDANCE
    return guidance + prompt


def plan(duration, resolution, fps=FPS):
    if duration != 10 or resolution not in RESOLUTIONS or fps != FPS:
        raise ValueError("Rolling-Window-Pilot unterstützt 10 s bei 540p/720p und 24 FPS")
    total = 0
    stages = []
    for index, seconds in enumerate(SEGMENT_SECONDS):
        total += seconds
        stages.append({
            "index": index, "seconds": seconds,
            "frames": seconds * FPS + (1 if index == 0 else 0),
            "confirmed_duration": total,
            "extend_latents": 0 if index == 0 else EXTEND_LATENTS,
        })
    return {"strategy": STRATEGY, "duration": 10, "resolution": resolution,
            "fps": FPS, "context_frames": CONTEXT_FRAMES, "stages": stages,
            "frames": duration * FPS + 1}


def _validate_canvas(params):
    width, height = int(params["width"]), int(params["height"])
    expected = ((1024, 576), (576, 1024)) if params["resolution"] == "540p" else (
        (1280, 704), (704, 1280))
    if (width, height) not in expected:
        raise ValueError("Rolling-Window benötigt die volle 540p/720p-Profilauflösung")


def _check(cancel):
    if cancel.is_set() or gate.blocked():
        raise ProviderCancelled("Rolling-Window wegen Abbruch oder Lifecycle-Stopp unterbrochen")


def _validate_part(path, expected_frames, params):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Rolling-Window-Checkpoint fehlt oder ist ein Symlink")
    info = _probe_video(path)
    if ((info["width"], info["height"]) != (params["width"], params["height"])
            or abs(info["fps"] - FPS) > 0.01 or info["frames"] != expected_frames
            or abs(info["duration"] - expected_frames / FPS) > 0.15):
        raise RuntimeError("Rolling-Window-Checkpoint besitzt unerwartete Bildparameter")
    return info


def _clip_frames(source, destination, *, start, count, cancel, owner):
    """Trim a small tail/window via one decoder; no arbitrary input paths."""
    _check(cancel)
    if start < 0 or count <= 0:
        raise ValueError("Ungültiger Rolling-Window-Ausschnitt")
    info = _probe_video(source)
    if start + count > info["frames"]:
        raise ValueError("Zu wenig Frames für den zeitlichen Kontext")
    duration = count / FPS
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source), "-map", "0:v:0",
        "-vf", f"select='between(n,{start},{start+count-1})',setpts=N/({FPS}*TB)",
        "-frames:v", str(count), "-r", str(FPS), "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CLIP_CRF),
        "-pix_fmt", "yuv420p",
    ]
    if info["audio"]:
        cmd += [
            "-map", "0:a:0",
            "-af", f"atrim=start={start/FPS:.9f}:duration={duration:.9f},"
                   "asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
                   f"apad,atrim=duration={duration:.9f}",
            "-c:a", "alac", "-ar", "48000",
        ]
    cmd += ["-movflags", "+faststart", str(destination)]
    _ffmpeg(cmd, cancel, owner, timeout=600)
    result = _validate_part(destination, count, {
        "width": info["width"], "height": info["height"],
    })
    if bool(result["audio"]) != bool(info["audio"]):
        raise RuntimeError("Rolling-Window hat beim Trimmen Audio verloren")
    return result


def _concat(parts, output, params, cancel, owner):
    """Three bounded CPU decoders, no Metal. Rebuild exact frame/sample clocks.

    AAC priming/padding in an MP4 concat demuxer shifted video by 21 ms and
    could introduce packet-rounded gaps. Trim decoded audio to each segment's
    exact sample count and encode AAC only once, with H.264 for browser playback.
    """
    signature = None
    filters, streams = [], []
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for index, part in enumerate(parts):
        expected = SEGMENT_SECONDS[index] * FPS + (1 if index == 0 else 0)
        info = _validate_part(part, expected, params)
        current = (info["width"], info["height"], info["fps"], info["audio"])
        if signature is None:
            signature = current
        if current != signature:
            raise RuntimeError("Rolling-Window-Segmente besitzen unterschiedliche Codecs/Streams")
        command += ["-threads", "1", "-i", str(part)]
        filters.append(f"[{index}:v]setpts=N/({FPS}*TB)[v{index}]")
        streams.append(f"[v{index}]")
        if info["audio"]:
            samples = expected * 48000 // FPS
            filters.append(f"[{index}:a]aresample=48000,apad=whole_len={samples},"
                           f"atrim=end_sample={samples},asetpts=N/SR/TB[a{index}]")
            streams.append(f"[a{index}]")
    has_audio = bool(signature[3])
    filters.append("".join(streams) + f"concat=n={len(parts)}:v=1:a={int(has_audio)}"
                   + ("[v][a]" if has_audio else "[v]"))
    command += ["-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
                "-map", "[v]", "-r", str(FPS), "-fps_mode", "cfr",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(OUTPUT_CRF),
                "-pix_fmt", "yuv420p", "-threads", "2"]
    if has_audio:
        command += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    command += ["-movflags", "+faststart", str(output)]
    _ffmpeg(command, cancel, owner, timeout=600)
    result = _probe_video(output)
    if (result["frames"] != 241 or abs(result["fps"] - FPS) > 0.01
            or abs(result["duration"] - 10) > 0.2):
        raise RuntimeError("Rolling-Window-Ausgabe hat nicht 241 Frames bei 24 FPS")
    return result


def _fingerprint(model, params, planner, version):
    root = video_registry.model_path(model).resolve()
    config = root / "embedded_config.json"
    if not config.is_file():
        raise RuntimeError("LTX-Modellkonfiguration fehlt")
    source = Path(params["first_frame"]) if params.get("first_frame") else None
    payload = {
        "strategy": STRATEGY, "conditioning_version": CONDITIONING_VERSION,
        "transport": {"clip_crf": CLIP_CRF, "audio": "alac", "output_crf": OUTPUT_CRF},
        "model": model["id"], "runtime": version,
        "config": video_long.digest(config), "plan": planner,
        "params": {k: v for k, v in params.items() if k != "resume_from"
                   and not (k in {"i2v_image_crf", "face_guidance"} and v is None)},
        "source": video_long.digest(source) if source else None,
        "weights": [(str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in sorted(root.rglob("*.safetensors"))],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run(model, params, output, *, job_id, checkpoints, resume_job, generate,
        cancel_event, response_callback, progress_callback, phase_callback, update):
    if model.get("provider") != "ltx-mlx" or params.get("profile", "standard") != "standard":
        raise ValueError("Rolling-Window benötigt natives Standard-LTX-MLX")
    planner = plan(params["duration"], params["resolution"], params["fps"])
    guidance_mode = _face_guidance_mode(params)
    face_guidance = guidance_mode != "off"
    _validate_canvas(params)
    version = video_long.runtime_version()
    fingerprint = _fingerprint(model, params, planner, version)
    directory = checkpoints / job_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_file = directory / "checkpoint.json"
    manifest = {"version": 2, "fingerprint": fingerprint, "plan": planner, "stages": []}
    owner = "video:rolling:" + job_id

    if resume_job:
        if (resume_job.get("status") == "cancelled" or
                (resume_job.get("cancel_requested") and
                 resume_job.get("cancel_reason") != "lifecycle")):
            raise ValueError("Explizit abgebrochene Rolling-Jobs dürfen nicht fortgesetzt werden")
        previous = checkpoints / resume_job["id"]
        saved = json.loads((previous / "checkpoint.json").read_text())
        if saved.get("fingerprint") != fingerprint or saved.get("plan") != planner:
            raise ValueError("Rolling-Checkpoint gehört zu einer anderen Konfiguration")
        for index, entry in enumerate(saved.get("stages") or []):
            if index >= len(planner["stages"]) or entry.get("index") != index:
                raise RuntimeError("Rolling-Checkpoint-Reihenfolge ungültig")
            source = previous / f"part-{index}.mp4"
            _validate_part(source, planner["stages"][index]["frames"], params)
            if video_long.digest(source) != entry["sha256"]:
                raise RuntimeError("Rolling-Checkpoint wurde verändert")
            shutil.copy2(source, directory / source.name)
            manifest["stages"].append(entry)
    video_long.atomic_json(manifest_file, manifest)
    completed = len(manifest["stages"])
    # Keep only diagnostic numbers. Do not persist original images/prompts in
    # telemetry. Previously verified checkpoints retain their measurements.
    stage_memory = [dict(entry.get("memory") or {}) for entry in manifest["stages"]]
    update(automatic_continuation=True, long_plan=planner,
           stage_count=len(planner["stages"]), target_duration=10,
           confirmed_duration=(planner["stages"][completed-1]["confirmed_duration"]
                               if completed else 0),
           checkpoint_count=completed, resumable=completed > 0,
           continuity_warning=WARNING,
           rolling_window_frames=CONTEXT_FRAMES,
           rolling_identity_prompt_guidance=face_guidance,
           rolling_face_guidance_mode=guidance_mode,
           rolling_stage_memory=stage_memory)

    for index, stage in enumerate(planner["stages"]):
        _check(cancel_event)
        update(stage_number=index+1, status="generating", phase="generating",
               progress=None, phase_progress=None, last_activity_at=time.time(),
               progress_message="LTX Rolling-Window: 25 Frames Bewegungs-/Audiokontext")
        if index < completed:
            continue
        part = directory / f"part-{index}.mp4"
        prepared = directory / f"part-{index}.partial.mp4"
        raw = directory / f"raw-{index}.partial.mp4"
        context = directory / f"context-{index}.partial.mp4"
        stage_started = time.monotonic()
        before = runtime_coordinator.memory_budget_snapshot()
        try:
            runtime_coordinator.ensure_active_memory_safe(before)
            if index == 0:
                initial = dict(params, duration=6, frames=145,
                               prompt=_face_prompt(params, extension=False),
                               _active_memory_guard=True, resume_from=None)
                generate(model, initial, raw, cancel_event=cancel_event,
                         response_callback=response_callback,
                         progress_callback=progress_callback,
                         phase_callback=phase_callback)
                shutdown_warm_runtime()
                _validate_part(raw, 145, params)
                _clip_frames(raw, prepared, start=0, count=145,
                             cancel=cancel_event, owner=owner)
            else:
                previous = directory / f"part-{index-1}.mp4"
                previous_frames = planner["stages"][index-1]["frames"]
                _clip_frames(previous, context, start=previous_frames-CONTEXT_FRAMES,
                             count=CONTEXT_FRAMES, cancel=cancel_event, owner=owner)
                video_long.extend(context, raw, EXTEND_LATENTS,
                    dict(params, model_path=str(video_registry.model_path(model).resolve()),
                         prompt=_face_prompt(params, extension=True)),
                    cancel_event, update, owner)
                _validate_part(raw, CONTEXT_FRAMES + NEW_FRAMES, params)
                _clip_frames(raw, prepared, start=CONTEXT_FRAMES, count=NEW_FRAMES,
                             cancel=cancel_event, owner=owner)
            _check(cancel_event)
            info = _validate_part(prepared, stage["frames"], params)
            if index and bool(info["audio"]) != bool(manifest["stages"][0]["info"]["audio"]):
                raise RuntimeError("Audioformat beim Rolling-Extend verändert")
            after = runtime_coordinator.memory_budget_snapshot()
            memory = {
                "stage": index + 1,
                "resolution": params["resolution"],
                "aspect_ratio": params.get("aspect_ratio"),
                "elapsed_seconds": round(time.monotonic() - stage_started, 2),
                "before_free_percent": before.get("free_percent"),
                "after_free_percent": after.get("free_percent"),
                "before_headroom_gb": before.get("headroom_gb"),
                "after_headroom_gb": after.get("headroom_gb"),
                "before_swap_gb": before.get("swap_used_gb"),
                "after_swap_gb": after.get("swap_used_gb"),
                "after_pressure": after.get("pressure"),
            }
            # A stage which exhausted available memory must never be declared
            # successful merely because FFmpeg managed to write an output.
            runtime_coordinator.ensure_active_memory_safe(after)
            entry = {"index": index, "info": info, "sha256": video_long.digest(prepared),
                     "seconds": stage["seconds"], "memory": memory,
                     "validated_at": time.time()}
            with gate.barrier():
                _check(cancel_event)
                os.replace(prepared, part)
                manifest["stages"].append(entry)
                video_long.atomic_json(manifest_file, manifest)
            stage_memory.append(memory)
            update(checkpoint_count=len(manifest["stages"]), resumable=True,
                   confirmed_duration=stage["confirmed_duration"],
                   rolling_stage_memory=list(stage_memory),
                   last_activity_at=time.time())
        finally:
            shutdown_warm_runtime()
            raw.unlink(missing_ok=True)
            context.unlink(missing_ok=True)
            prepared.unlink(missing_ok=True)

    _check(cancel_event)
    phase_callback("muxing")
    update(phase="muxing", status="muxing", last_activity_at=time.time())
    output_info = _concat(
        [directory / f"part-{index}.mp4" for index in range(len(SEGMENT_SECONDS))],
        output, params, cancel_event, owner)
    _check(cancel_event)
    return {**output_info, "duration": 10, "actual_duration": output_info["duration"],
            "automatic_continuation": True, "strategy": STRATEGY,
            "stage_count": len(SEGMENT_SECONDS), "rolling_window_frames": CONTEXT_FRAMES,
            "rolling_stage_memory": stage_memory,
            "rolling_identity_prompt_guidance": face_guidance,
            "rolling_face_guidance_mode": guidance_mode,
            "continuity_warning": WARNING}
