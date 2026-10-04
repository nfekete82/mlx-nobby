"""Scene-aware audio and timeline-preserving FFmpeg composition for schema v2."""
import subprocess
import shutil
import math


from agent.shorts_planner import ShortProject, quality_capabilities


MAX_VOICEOVER_TIME_COMPRESSION = 1.15
# Preserve the existing allowance for MP3 encoder padding / duration probing.
VOICEOVER_DURATION_TOLERANCE_SECONDS = 0.05


class VoiceoverDurationError(ValueError):
    """Known user-correctable failure, with safe structured duration metadata."""

    def __init__(self, scene, scene_number, duration):
        super().__init__(
            f"voiceover for scene {scene_number} ({scene.id}) is too long "
            f"({duration:.2f}s for {scene.duration:.2f}s); "
            "shorten narration or increase voice speed"
        )
        self.diagnosis = {
            "error_code": "VOICEOVER_TOO_LONG",
            "error_scene_id": scene.id,
            "error_scene_number": scene_number,
            "error_audio_duration": duration,
            "error_scene_duration": scene.duration,
        }


def library_tracks(root):
    from agent import shorts_jobs
    root = root.expanduser().resolve()
    tracks = []
    if root.is_dir():
        for file in sorted(root.rglob("*")):
            resolved = file.resolve()
            if (file.is_file() and resolved.is_relative_to(root)
                    and file.suffix.lower() in shorts_jobs.MUSIC_EXTENSIONS):
                tracks.append({"track": str(file.relative_to(root)), "style": file.parent.name,
                               "name": file.stem})
    return tracks


def library_path(root, track):
    from agent import shorts_jobs
    root = root.expanduser().resolve()
    path = (root / str(track)).resolve()
    if (not path.is_relative_to(root) or not path.is_file()
            or path.suffix.lower() not in shorts_jobs.MUSIC_EXTENSIONS):
        raise ValueError("track must be an existing audio file inside the local library")
    return path


def scene_music(project, scene):
    from agent.shorts_planner import SceneMusic
    settings = SceneMusic(enabled=project.music_enabled and project.music_mode != "off",
                          style=project.music_style or "cinematic", track=project.music_track,
                          volume=project.music_volume)
    if project.music_mode == "scene" and scene.music:
        data = settings.model_dump()
        data.update({k: v for k, v in scene.music.model_dump(exclude_unset=True).items() if v is not None})
        settings = SceneMusic.model_validate(data)
    return settings


def select_track(root, settings):
    if not settings.enabled:
        return None
    if settings.track and settings.track != "auto":
        return library_path(root, settings.track)
    candidates = [t for t in library_tracks(root) if t["style"] == settings.style]
    return library_path(root, candidates[0]["track"]) if candidates else None


def compose_command(job, output_path):
    from agent import shorts_jobs
    project = ShortProject.model_validate(job["project"])
    width, height = quality_capabilities()[project.quality]["dimensions"]
    command = [shorts_jobs._ffmpeg_path(), "-y", "-nostdin", "-loglevel", "error",
               "-filter_complex_threads", "1"]
    filters, labels = [], []
    results = {r["scene_id"]: r for r in job.get("scene_results", []) if r.get("status") == "completed"}
    for i, scene in enumerate(project.scenes):
        result = results.get(scene.id)
        if not result or not result.get("path"):
            raise RuntimeError(f"completed video missing for scene {scene.id}")
        command += ["-i", str(result["path"])]
        chain = (f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,setsar=1,"
                 f"tpad=stop_mode=clone:stop_duration={scene.duration},trim=duration={scene.duration},setpts=PTS-STARTPTS")
        # Fade each half at its own boundary; no overlapping clips and no lost frames.
        if i:
            incoming = project.scenes[i - 1].transition
            if incoming.type != "cut":
                color = "white" if incoming.type in {"fadewhite", "flash"} else "black"
                chain += f",fade=t=in:st=0:d={incoming.duration / 2}:color={color}"
        if i < len(project.scenes) - 1 and scene.transition.type != "cut":
            color = "white" if scene.transition.type in {"fadewhite", "flash"} else "black"
            half = scene.transition.duration / 2
            chain += f",fade=t=out:st={scene.duration - half}:d={half}:color={color}"
        filters.append(chain + f"[v{i}]")
        labels.append(f"[v{i}]")
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[joined]")
    video = "joined"
    if project.subtitles_enabled:
        filters.append("[joined]ass=subtitles.ass[subtitled]")
        video = "subtitled"
    next_index = len(project.scenes)
    voice_index = next_index
    next_index += 1
    if job.get("tts_path") and project.voice_enabled:
        command += ["-i", str(job["tts_path"])]
    else:
        command += ["-f", "lavfi", "-t", str(project.duration), "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000"]
    filters.append(f"[{voice_index}:a]aresample=48000,apad,atrim=duration={project.duration},asetpts=PTS-STARTPTS[voice]")
    music_labels, duck_labels = [], []
    timeline = 0
    global_offset = 0
    for i, scene in enumerate(project.scenes):
        settings = scene_music(project, scene)
        path = select_track(shorts_jobs.MUSIC_DIRECTORY, settings)
        if path:
            command += ["-stream_loop", "-1", "-i", str(path)]
            offset = settings.start_offset + (global_offset if project.music_mode == "global" else 0)
            chain = (f"[{next_index}:a]aresample=48000,atrim=start={offset}:duration={scene.duration},"
                     f"asetpts=PTS-STARTPTS,volume={settings.volume}")
            next_index += 1
            if settings.fade_in:
                chain += f",afade=t=in:st=0:d={min(settings.fade_in, scene.duration)}"
            if settings.fade_out:
                fade = min(settings.fade_out, scene.duration)
                chain += f",afade=t=out:st={scene.duration-fade}:d={fade}"
            chain += f",adelay={round(timeline*1000)}:all=1,apad,atrim=duration={project.duration}"
            label = f"music{i}"
            filters.append(chain + f"[{label}]")
            (duck_labels if settings.duck_under_voice else music_labels).append(f"[{label}]")
        if scene.sfx.enabled:
            root = shorts_jobs.MUSIC_DIRECTORY.parent / "sfx"
            path = library_path(root, scene.sfx.track)
            if scene.sfx.offset >= scene.duration:
                raise ValueError("sound effect offset must be inside its scene")
            command += ["-i", str(path)]
            filters.append(f"[{next_index}:a]aresample=48000,atrim=duration={scene.duration-scene.sfx.offset},"
                           f"asetpts=PTS-STARTPTS,volume={scene.sfx.volume},"
                           f"adelay={round((timeline+scene.sfx.offset)*1000)}:all=1,apad,"
                           f"atrim=duration={project.duration}[sfx{i}]")
            next_index += 1
            music_labels.append(f"[sfx{i}]")
        global_offset += scene.duration
        timeline += scene.duration
    voice = "[voice]"
    if duck_labels:
        filters.append("".join(duck_labels) + f"amix=inputs={len(duck_labels)}:normalize=0[bed]")
        filters += ["[voice]asplit=2[voice_mix][voice_key]",
                    "[bed][voice_key]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[ducked]"]
        music_labels.append("[ducked]")
        voice = "[voice_mix]"
    filters.append(voice + "".join(music_labels) +
                   f"amix=inputs={len(music_labels)+1}:duration=first:normalize=0,alimiter=limit=0.95[audio]")
    command += ["-filter_complex", ";".join(filters), "-map", f"[{video}]", "-map", "[audio]",
                "-t", str(project.duration), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-f", "mp4", str(output_path)]
    return command


def scene_tts(job_id, project, request_fn):
    """Place speech inside its scene; silence stays in scenes without narration."""
    from agent import shorts_jobs, batch_state
    directory = shorts_jobs.SHORTS_DIRECTORY / job_id
    directory.mkdir(parents=True, exist_ok=True)
    command = [shorts_jobs._ffmpeg_path(), "-y", "-nostdin", "-loglevel", "error"]
    filters, labels = [], []
    elapsed = 0
    index = 0
    for scene_number, scene in enumerate(project.scenes, 1):
        if scene.voice_enabled and scene.narration:
            payload = {"input": scene.narration, "language": project.language}
            voice = project.voice_for_scene(scene)
            if voice:
                payload["voice"] = voice
            if project.voice_speed != 1:
                payload["speed"] = project.voice_speed
            audio = request_fn(payload)
            if not isinstance(audio, bytes) or not audio:
                raise RuntimeError("speech service returned invalid audio")
            if shorts_jobs.get_short_job(job_id).get("cancel_requested"):
                raise shorts_jobs._ComposeCancelled("TTS cancelled")
            path = directory / f"voice-{scene.id}.mp3"
            batch_state.atomic_write_with(path, lambda temporary: temporary.write_bytes(audio))
            probe = shutil.which("ffprobe") or "ffprobe"
            duration = float(subprocess.check_output(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                text=True, timeout=30,
            ).strip())
            if not math.isfinite(duration) or duration <= 0:
                raise RuntimeError("speech service returned invalid audio duration")
            tempo = ""
            mix_timestamps = ""
            if duration > scene.duration + VOICEOVER_DURATION_TOLERANCE_SECONDS:
                required_speed = duration / scene.duration
                if required_speed > MAX_VOICEOVER_TIME_COMPRESSION:
                    raise VoiceoverDurationError(scene, scene_number, duration)
                # Rebuild timestamps after tempo/delay/padding from sample counts.
                tempo = f"atempo={required_speed:.9f},asetpts=N/SR/TB,"
                mix_timestamps = "asetpts=N/SR/TB,"
            command += ["-i", str(path)]
            filters.append(f"[{index}:a]aresample=48000,{tempo}atrim=duration={scene.duration},asetpts=PTS-STARTPTS,"
                           f"adelay={elapsed*1000}:all=1,apad,{mix_timestamps}atrim=duration={project.duration}[a{index}]")
            labels.append(f"[a{index}]")
            index += 1
        elapsed += scene.duration
    output = directory / "voiceover-mix.mp3"
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0[audio]")
    command += ["-filter_complex", ";".join(filters), "-map", "[audio]", "-t", str(project.duration), str(output)]
    shorts_jobs._run_ffmpeg(command, cwd=directory,
                            cancel_check=lambda: shorts_jobs.get_short_job(job_id).get("cancel_requested"), timeout=300)
    return output.read_bytes()
