"""Memory-bounded 9/30/60 second LTX videos on Apple unified memory.

Unlike native LTX Extend, no stage ever loads the entire accumulated clip.
Each short, independent I2V segment is rendered inside the same video-runtime
lease; the heavy MLX worker is terminated between segments. A verified last
frame conditions the next segment. This preserves appearance, not mathematically
perfect motion or audio continuity.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import ai_lifecycle_gate as gate
import managed_process
import runtime_coordinator
import video_long
import video_registry
from video_providers import FFMPEG, ProviderCancelled, _probe_video
from video_providers_mlx import shutdown_warm_runtime


DURATIONS = frozenset({9, 30, 60})
SEGMENT_SECONDS = {"1080p": 3, "720p": 5, "540p": 6}
CONTINUITY_WARNING = (
    "RAM-sichere LTX-Segmente verwenden das vorherige Schlussbild. "
    "Identity Lock nutzt das vorige Schlussbild als festen Start und das "
    "Originalfoto als weiche Identitätsreferenz am Anfang. "
    "Doppelte Randframes werden beim Stitching entfernt; unabhängige "
    "Bewegungen, Audio und Farbabweichungen bleiben möglich."
)
IDENTITY_PROMPT = (
    " Preserve the identity of the person in the original reference image: "
    "the same facial features, facial proportions, hairstyle, age, and clothing. "
    "Continue natural movement without a new person or costume."
)


def needed(params):
    return int(params["duration"]) in DURATIONS


def plan(duration, resolution, fps=24):
    if (int(duration) not in DURATIONS or resolution not in SEGMENT_SECONDS or fps != 24
            or (int(duration) == 9 and resolution != "1080p")):
        raise ValueError("RAM-sichere Videos benötigen 9s/1080p oder 30/60s, 24 fps und 540p/720p/1080p")
    seconds = SEGMENT_SECONDS[resolution]
    if int(duration) % seconds:
        raise ValueError("Segmentlänge muss die gewünschte Dauer exakt teilen")
    chunks = int(duration) // seconds
    return {
        "strategy": "segmented-low-ram-v1", "duration": int(duration),
        "resolution": resolution, "fps": fps, "frames": int(duration) * fps + 1,
        "initial_seconds": seconds, "segment_seconds": seconds,
        "stages": [{"index": i, "seconds": seconds, "frames": seconds * fps + 1}
                   for i in range(chunks)],
    }


def _check(cancel):
    if cancel.is_set() or gate.blocked():
        raise ProviderCancelled("Long-Video durch Abbruch oder Lifecycle-Stopp unterbrochen")


def _ffmpeg(command, cancel, owner, timeout=600):
    """Cancellable, tracked ffmpeg process with bounded log growth."""
    with tempfile.TemporaryFile(mode="w+b") as log:
        process = managed_process.spawn(
            command, owner=owner, stdout=subprocess.DEVNULL,
            stderr=log,
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                _check(cancel)
                if time.monotonic() >= deadline:
                    raise RuntimeError("FFmpeg-Zeitlimit erreicht")
                cancel.wait(0.2)
            if process.returncode != 0:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - 1200))
                raise RuntimeError("FFmpeg-Verarbeitung fehlgeschlagen: "
                                   + log.read().decode(errors="replace"))
        finally:
            managed_process.terminate(process)


def _last_frame(clip, destination, cancel, owner):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # image2 -update=1 overwrites the target for every decoded frame. The last
    # decoded frame from the last 0.5 seconds is therefore retained.
    _ffmpeg([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-sseof", "-0.5", "-i", str(clip), "-an", "-update", "1",
             str(destination)], cancel, owner, timeout=120)
    if not destination.is_file() or not destination.stat().st_size:
        raise RuntimeError("Letztes Segmentbild fehlt")


def _validate_segment(path, stage, params):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Verifizierter Video-Checkpoint fehlt")
    info = _probe_video(path)
    if ((info["width"], info["height"]) != (params["width"], params["height"])
            or abs(float(info["fps"]) - params["fps"]) > 0.01
            or abs(float(info["duration"]) - stage["seconds"]) > 0.2
            or int(info["frames"]) != stage["frames"]):
        raise RuntimeError("Long-Video-Checkpoint besitzt unerwartete Bildparameter")
    return info


def _compose(paths, output, params, cancel, owner):
    """Join 8k+1 LTX segments without repeating the shared boundary frame.

    Each 3-second 24-fps segment has 73 frames: the first frame of a later
    segment describes the *same instant* as the last frame of the preceding
    segment. Plain demuxer concatenation introduces one redundant frame per
    join and a small but visible motion hold. Decode and encode one stream
    sequentially (not N concurrent 1080p decoders), dropping precisely those
    duplicated frames and rebuilding a CFR timeline.

    This repairs only the repeated-boundary-frame artifact, not the underlying
    motion/identity or color-grade mismatch between independent generations.
    """
    if not paths:
        raise ValueError("Keine LTX-Segmente zum Zusammenfügen")

    first = None
    segment_frames = SEGMENT_SECONDS[params["resolution"]] * int(params["fps"]) + 1
    for clip in paths:
        info = _probe_video(clip)
        signature = (info["width"], info["height"], round(info["fps"], 2), bool(info["audio"]))
        if first is None:
            first = signature
        if first != signature:
            raise RuntimeError("Segmentformate stimmen beim Zusammenfügen nicht überein")
        if int(info["frames"]) != segment_frames:
            raise RuntimeError("Segment besitzt nicht die erwartete Anzahl Randframes")

    fps = int(params["fps"])
    expected_frames = int(params["duration"]) * fps + 1
    if len(paths) * (segment_frames - 1) + 1 != expected_frames:
        raise RuntimeError("Die Video-Teilstücke ergeben keine lückenlose Zeitleiste")

    # FFmpeg filter expressions need quoting for commas between function args.
    # The initial n=0 frame must survive; n=segment_frames, 2*segment_frames,
    # ... are shared starts and should be dropped.
    selection = (
        f"select='eq(n,0)+not(eq(mod(n,{segment_frames}),0))',"
        f"setpts=N/({fps}*TB)"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ltx-segmented-") as root:
        listing = Path(root) / "parts.ffconcat"
        lines = ["ffconcat version 1.0"]
        for clip in paths:
            lines.append("file '" + str(clip.resolve()).replace("'", "'\\''") + "'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")

        command = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-map", "0:v:0", "-vf", selection, "-r", str(fps),
            "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "17", "-pix_fmt", "yuv420p",
        ]
        if first[3]:
            # Compress audio by the same cumulative boundary-frame correction.
            # This keeps A/V drift from increasing on 30/60-second renders.
            original_frames = len(paths) * segment_frames
            tempo = original_frames / expected_frames
            command += [
                "-map", "0:a:0",
                "-af", f"atempo={tempo:.9f},aresample=async=1:first_pts=0,"
                       f"apad,atrim=duration={params['duration']}",
                "-c:a", "aac", "-b:a", "192k",
            ]
        command += ["-movflags", "+faststart", str(output)]
        _ffmpeg(command, cancel, owner, timeout=900)

    info = _probe_video(output)
    if int(info["frames"]) != expected_frames or abs(float(info["fps"]) - fps) > 0.01:
        raise RuntimeError("Segment-Assembly hat unerwartete Frameanzahl oder FPS")
    if abs(float(info["duration"]) - params["duration"]) > 0.2:
        raise RuntimeError("Gesamtdauer der kombinierten Videosegmente ist inkonsistent")
    return info

def _fingerprint(model, params):
    model_path = video_registry.model_path(model).resolve()
    config = model_path / "embedded_config.json"
    if not config.is_file():
        raise RuntimeError("LTX-MLX-Modellkonfiguration fehlt")
    original = Path(params["first_frame"]) if params.get("first_frame") else None
    signature = {
        "model": model["id"], "conditioning_version": 2,
        "params": {k: v for k, v in params.items() if k != "resume_from"},
        "model_config_sha256": video_long.digest(config),
        "weights": [
            (str(p.relative_to(model_path)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(model_path.rglob("*.safetensors"))
        ],
        "original_sha256": video_long.digest(original) if original else None,
        "plan": plan(params["duration"], params["resolution"], params["fps"]),
    }
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()


def run(model, params, output, *, job_id, checkpoints, resume_job,
        generate, cancel_event, response_callback, progress_callback,
        phase_callback, update):
    if model.get("provider") != "ltx-mlx" or params.get("profile", "standard") != "standard":
        raise ValueError("Segmentierte Langvideos benötigen natives Standard-LTX-MLX")
    planner = plan(params["duration"], params["resolution"], params["fps"])
    identity_lock = bool(params.get("first_frame")) and bool(params.get("identity_lock", True))
    identity_strength = float(params.get("identity_strength", 0.30))
    if identity_lock:
        from video_multi_image import keyframe_capabilities
        from video_providers_mlx import LTX_MLX_RUNTIME_ROOT
        if not keyframe_capabilities(LTX_MLX_RUNTIME_ROOT)["native_keyframes"]:
            raise ValueError("Identity Lock benötigt native LTX-MLX-Keyframes (v0.18)")
    fingerprint = _fingerprint(model, params)
    directory = checkpoints / job_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "checkpoint.json"
    manifest = {"version": 1, "fingerprint": fingerprint,
                "plan": planner, "stages": []}
    owner = "video:segmented:" + job_id
    # No user-controlled checkpoint paths. Only previously persisted job IDs
    # selected by the existing authenticated resume preflight may be used.
    if resume_job:
        if (resume_job.get("status") == "cancelled"
                or (resume_job.get("cancel_requested")
                    and resume_job.get("cancel_reason") != "lifecycle")):
            raise ValueError("Explizit abgebrochene Langvideos werden nicht automatisch fortgesetzt")
        previous = checkpoints / resume_job["id"]
        saved = json.loads((previous / "checkpoint.json").read_text())
        if saved.get("fingerprint") != fingerprint or saved.get("plan") != planner:
            raise ValueError("Checkpoint stammt aus einer anderen Modell-/Video-Konfiguration")
        for index, entry in enumerate(saved.get("stages") or []):
            if index >= len(planner["stages"]) or entry.get("index") != index:
                raise RuntimeError("Checkpoint-Reihenfolge ist beschädigt")
            src = previous / f"segment-{index}.mp4"
            _validate_segment(src, planner["stages"][index], params)
            if video_long.digest(src) != entry.get("sha256"):
                raise RuntimeError("Checkpoint wurde verändert")
            shutil.copy2(src, directory / src.name)
            manifest["stages"].append(entry)
    video_long.atomic_json(manifest_path, manifest)
    completed = len(manifest["stages"])
    update(automatic_continuation=True, long_plan=planner,
           stage_count=len(planner["stages"]), target_duration=params["duration"],
           identity_lock=identity_lock, identity_strength=(identity_strength if identity_lock else None),
           continuity_warning=CONTINUITY_WARNING,
           checkpoint_count=completed, resumable=bool(completed),
           confirmed_duration=completed * planner["segment_seconds"])

    for index, stage in enumerate(planner["stages"]):
        _check(cancel_event)
        update(stage_number=index + 1, phase="generating", status="generating",
               progress=None, phase_progress=None, current_step=None,
               total_steps=None, last_activity_at=time.time(),
               progress_message="RAM-sicheres LTX-Segment wird vorbereitet")
        if index < completed:
            continue
        clip = directory / f"segment-{index}.mp4"
        temporary = directory / f"segment-{index}.partial.mp4"
        previous_frame = directory / f"last-frame-{index-1}.png"
        if index:
            _last_frame(directory / f"segment-{index-1}.mp4",
                        previous_frame, cancel_event, owner)
        # The first frame must be a hard continuity anchor even when images are
        # present. The provider prepends it explicitly before these soft guides.
        # Identity guidance at the clip midpoint made the person snap backward
        # toward the original pose. Guide at frame 0 instead, with no later reset.
        anchors = ([{"path": str(params["first_frame"]),
                     "frame_index": 0, "binding": "guide",
                     "strength": identity_strength}]
                   if identity_lock and index else [])
        segment = dict(params, duration=stage["seconds"], frames=stage["frames"],
                       seed=(int(params["seed"]) if identity_lock else
                             (int(params["seed"]) + index) % (2 ** 31)),
                       prompt=(params["prompt"] + IDENTITY_PROMPT if identity_lock and index
                               else params["prompt"]),
                       images=anchors, multi_image_mode=None, resume_from=None,
                       _active_memory_guard=True,
                       first_frame=(str(previous_frame) if index else params.get("first_frame")))
        if index:
            segment["resize_mode"] = "contain"
        try:
            runtime_coordinator.ensure_active_memory_safe(
                runtime_coordinator.memory_budget_snapshot()
            )
            generate(model, segment, temporary, cancel_event=cancel_event,
                     response_callback=response_callback,
                     progress_callback=progress_callback,
                     phase_callback=phase_callback)
            _check(cancel_event)
            info = _validate_segment(temporary, stage, params)
            entry = {"index": index, "info": info,
                     "sha256": video_long.digest(temporary),
                     "validated_at": time.time()}
            with gate.barrier():
                _check(cancel_event)
                os.replace(temporary, clip)
                manifest["stages"].append(entry)
                video_long.atomic_json(manifest_path, manifest)
            update(checkpoint_count=len(manifest["stages"]), resumable=True,
                   confirmed_duration=(index + 1) * stage["seconds"],
                   last_activity_at=time.time())
        finally:
            # Unlike normal short videos, never reuse warmed Python/Metal state.
            shutdown_warm_runtime()
            temporary.unlink(missing_ok=True)

    _check(cancel_event)
    phase_callback("muxing")
    update(phase="muxing", status="muxing", last_activity_at=time.time())
    output_info = _compose(
        [directory / f"segment-{i}.mp4" for i in range(len(planner["stages"]))],
        output, params, cancel_event, owner)
    _check(cancel_event)
    return {
        **output_info, "duration": params["duration"], "actual_duration": output_info["duration"],
        "automatic_continuation": True, "strategy": planner["strategy"],
        "stage_count": len(planner["stages"]),
        "continuity_warning": CONTINUITY_WARNING,
        "identity_lock": identity_lock,
        "identity_strength": identity_strength if identity_lock else None,
    }
