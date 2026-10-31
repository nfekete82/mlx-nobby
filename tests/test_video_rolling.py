"""CPU-only rolling LTX time-window tests; small FFmpeg smoke if installed."""
import json
import shutil
import subprocess
import threading
from pathlib import Path
from fractions import Fraction
from unittest import mock

import pytest

import video_rolling
import video_providers
import video_service


def test_opt_in_is_strict_and_existing_segment_mode_is_unchanged():
    assert not video_rolling.needed({"duration": 10, "resolution": "540p"})
    assert video_rolling.needed({"continuation_mode": "rolling"})
    planner = video_rolling.plan(10, "540p")
    assert planner["strategy"] == video_rolling.STRATEGY
    assert [stage["frames"] for stage in planner["stages"]] == [145, 48, 48]
    assert [stage["confirmed_duration"] for stage in planner["stages"]] == [6, 8, 10]
    assert planner["context_frames"] == 25
    assert planner["frames"] == 241
    hd = video_rolling.plan(10, "720p")
    assert hd["resolution"] == "720p"
    assert hd["context_frames"] == 25
    assert [stage["frames"] for stage in hd["stages"]] == [145, 48, 48]
    for resolution, expected in (
        ("540p", ((1024, 576), (576, 1024))),
        ("720p", ((1280, 704), (704, 1280))),
    ):
        for width, height in expected:
            video_rolling._validate_canvas({
                "resolution": resolution, "width": width, "height": height,
            })
    with pytest.raises(ValueError, match="Profilauflösung"):
        video_rolling._validate_canvas({
            "resolution": "720p", "width": 1024, "height": 576,
        })
    with pytest.raises(ValueError):
        video_rolling.plan(10, "1080p")
    with pytest.raises(ValueError):
        video_rolling.plan(20, "540p")
    with pytest.raises(ValueError):
        video_rolling.plan(10, "540p", 8)


def test_service_strict_mode_requires_540p_ten_seconds_and_single_video(monkeypatch):
    request = video_service.JobCreate(
        operation="t2v", chat_id="test", chat_revision=0,
        payload={"prompt": "The woman smiles naturally", "quality": "fast",
                 "duration": 10, "continuation_mode": "rolling"})
    assert request.payload.resolution == "540p"
    assert request.payload.width == 1024 and request.payload.height == 576
    assert request.payload.frames == 241
    assert request.payload.continuation_mode == "rolling"
    hd_request = video_service.JobCreate(
        operation="t2v", chat_id="test", chat_revision=0,
        payload={"prompt": "The woman smiles", "quality": "standard",
                 "duration": 10, "continuation_mode": "rolling",
                 "aspect_ratio": "9:16"})
    assert hd_request.payload.resolution == "720p"
    assert (hd_request.payload.width, hd_request.payload.height) == (704, 1280)
    with mock.patch.object(video_service, "validate_first_frame",
                           return_value=Path("/managed/portrait.png")), \
         mock.patch.object(video_service, "i2v_source_size",
                           return_value=(720, 1200)):
        portrait = video_service.JobCreate(
            operation="i2v", chat_id="test", chat_revision=0,
            payload={"prompt": "A portrait animation", "quality": "standard",
                     "duration": 10, "first_frame": "/managed/portrait.png",
                     "continuation_mode": "rolling", "aspect_ratio": "9:16"})
    assert (portrait.payload.width, portrait.payload.height) == (704, 1280)
    assert portrait.payload.resize_mode == "contain"
    with pytest.raises(ValueError):
        video_service.JobCreate(
            operation="t2v", chat_id="test", chat_revision=0,
            payload={"prompt": "The woman smiles", "quality": "quality",
                     "duration": 10, "continuation_mode": "rolling"})
    with pytest.raises(ValueError):
        video_service.JobCreate(
            operation="t2v", chat_id="test", chat_revision=0,
            payload={"prompt": "The woman smiles", "quality": "fast",
                     "duration": 20, "continuation_mode": "rolling"})


def test_chat_video_options_reach_native_rolling_request():
    from agent import app as agent_app
    from backend.media_intent import decide_media_intent
    prompt = ("Erstelle ein 10-Sekunden-Video mit Rolling-Window-Test: "
              "The person slowly turns their head and smiles naturally.")
    assert decide_media_intent(prompt, has_image=True).target == "video"
    request = agent_app.ChatActionRequest(
        prompt=prompt, quality="fast", video_options={
            "duration": 10, "continuation_mode": "rolling",
            "identity_lock": False, "identity_strength": 0.2,
        },
    )
    with mock.patch.object(agent_app, "compile_video_prompt",
                           return_value="The person slowly turns their head and smiles naturally."):
        payload = agent_app._video_payload(request, "t2v")
    assert payload["continuation_mode"] == "rolling"
    assert payload["duration"] == 10
    assert payload["quality"] == "fast"
    assert payload["identity_lock"] is False
    assert payload["identity_strength"] == 0.2


def test_tail_refuses_short_source_before_ffmpeg(tmp_path):
    clip = tmp_path / "short.mp4"
    clip.write_bytes(b"small")
    with mock.patch.object(video_rolling, "_probe_video", return_value={
        "frames": 24, "fps": 24, "width": 128, "height": 64,
        "duration": 1, "audio": True,
    }), mock.patch.object(video_rolling, "_ffmpeg") as f:
        with pytest.raises(ValueError, match="Zu wenig"):
            video_rolling._clip_frames(
                clip, tmp_path / "context.mp4", start=0, count=25,
                cancel=threading.Event(), owner="test")
        f.assert_not_called()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required for executable rolling smoke")
@pytest.mark.parametrize("with_photo", [False, True])
def test_rolling_extend_uses_only_25_context_frames_and_outputs_241(tmp_path, monkeypatch, with_photo):
    monkeypatch.setattr(video_providers, "FFPROBE", shutil.which("ffprobe"))
    monkeypatch.setattr(video_rolling, "FFMPEG", shutil.which("ffmpeg"))

    root = tmp_path / "model"
    root.mkdir()
    (root / "embedded_config.json").write_text("{}")
    monkeypatch.setattr(video_rolling.video_registry, "model_path", lambda _: root)
    monkeypatch.setattr(video_rolling.video_long, "runtime_version", lambda: "known-runtime")
    # The FFmpeg integration test uses 128x64 for speed; separate tests above
    # verify all four real 540p/720p landscape and portrait dimensions.
    monkeypatch.setattr(video_rolling, "_validate_canvas", lambda _: None)
    monkeypatch.setattr(video_rolling.gate, "blocked", lambda: False)
    monkeypatch.setattr(video_rolling, "shutdown_warm_runtime", lambda: None)
    monkeypatch.setattr(video_rolling.runtime_coordinator, "memory_budget_snapshot",
                        lambda: {"free_percent": 75, "swap_used_gb": 0})
    monkeypatch.setattr(video_rolling.runtime_coordinator, "ensure_active_memory_safe",
                        lambda _: None)

    def ffmpeg(command, _cancel, _owner, timeout=600):
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    monkeypatch.setattr(video_rolling, "_ffmpeg", ffmpeg)

    def synthetic(destination, frames, color):
        subprocess.run([
            shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=128x64:r=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-frames:v", str(frames), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-t", f"{frames / 24:.9f}", str(destination),
        ], check=True, capture_output=True, timeout=45)

    calls = []
    def generate(_model, params, output, **kwargs):
        assert params["duration"] == 6 and params["frames"] == 145
        assert params["_active_memory_guard"] is True
        assert params["prompt"].startswith(video_rolling.INITIAL_FACE_GUIDANCE) == with_photo
        assert params["prompt"].endswith("A still portrait gently moving")
        synthetic(output, 145, "red")
        calls.append(("generate", 145))

    def extend(source, output, amount, params, cancel, update, owner):
        info = video_rolling._probe_video(source)
        assert info["frames"] == 25, "must not feed full accumulated movie"
        assert amount == 6
        assert params["prompt"].startswith(video_rolling.EXTEND_FACE_GUIDANCE) == with_photo
        assert params["prompt"].endswith("A still portrait gently moving")
        synthetic(output, 73, "blue")
        calls.append(("extend", info["frames"], amount))

    monkeypatch.setattr(video_rolling.video_long, "extend", extend)
    photo = tmp_path / "test-portrait.png"
    if with_photo:
        photo.write_bytes(b"synthetic reference source, no image decoder used")
    params = {
        "duration": 10, "resolution": "540p", "fps": 24,
        "width": 128, "height": 64, "seed": 7,
        "prompt": "A still portrait gently moving", "profile": "standard",
        "quality": "fast", "first_frame": str(photo) if with_photo else None,
        "identity_lock": True, "continuation_mode": "rolling",
    }
    model = {"id": "ltx-test", "provider": "ltx-mlx"}
    checkpoints = tmp_path / "checkpoints"
    status = {}
    def update(**fields):
        status.update(fields)
    output = tmp_path / "result.mp4"
    with monkeypatch.context() as p:
        result = video_rolling.run(
            model, params, output, job_id="a" * 24, checkpoints=checkpoints,
            resume_job=None, generate=generate,
            cancel_event=threading.Event(), response_callback=lambda _: None,
            progress_callback=lambda _: None, phase_callback=lambda _: None,
            update=update,
        )
    assert calls == [("generate", 145), ("extend", 25, 6), ("extend", 25, 6)]
    assert result["frames"] == 241
    assert result["strategy"] == video_rolling.STRATEGY
    assert result["rolling_window_frames"] == 25
    assert result["rolling_identity_prompt_guidance"] is with_photo
    assert status["rolling_identity_prompt_guidance"] is with_photo
    assert result["audio"] is True
    assert len(result["rolling_stage_memory"]) == 3
    assert [m["stage"] for m in result["rolling_stage_memory"]] == [1, 2, 3]
    assert all(m["after_free_percent"] == 75 and m["after_swap_gb"] == 0
               for m in result["rolling_stage_memory"])
    assert status["rolling_stage_memory"] == result["rolling_stage_memory"]
    assert status["checkpoint_count"] == 3
    assert status["confirmed_duration"] == 10
    manifest = json.loads((checkpoints / ("a" * 24) / "checkpoint.json").read_text())
    assert [entry["seconds"] for entry in manifest["stages"]] == [6, 2, 2]
    assert all(not (checkpoints / ("a" * 24) / f"raw-{i}.partial.mp4").exists()
               for i in range(3))


def test_rolling_face_guidance_uses_source_only_when_enabled():
    original = "The person gently turns their head, smiles and blinks."
    for first_frame, lock in ((None, True), ("/managed/portrait.png", False)):
        params = {"prompt": original, "first_frame": first_frame,
                  "identity_lock": lock}
        assert video_rolling._face_prompt(params, extension=False) == original
        assert video_rolling._face_prompt(params, extension=True) == original
    params = {"prompt": original, "first_frame": "/managed/portrait.png",
              "identity_lock": True}
    initial = video_rolling._face_prompt(params, extension=False)
    extended = video_rolling._face_prompt(params, extension=True)
    assert initial.startswith(video_rolling.INITIAL_FACE_GUIDANCE)
    assert extended.startswith(video_rolling.EXTEND_FACE_GUIDANCE)
    assert initial.endswith(original) and extended.endswith(original)
    assert "eye shape" in initial and "iris placement" in extended
    assert "natural" in initial and "natural" in extended
    assert params["prompt"] == original, "must not mutate the user prompt"


def test_rolling_trim_uses_lossless_transport_without_spatial_filters(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic source")
    info = {"frames": 145, "fps": 24, "width": 128, "height": 64,
            "duration": 145 / 24, "audio": True}
    commands = []
    monkeypatch.setattr(video_rolling, "_probe_video", lambda _: info)
    monkeypatch.setattr(video_rolling, "_validate_part",
                        lambda path, count, params: info)
    monkeypatch.setattr(video_rolling, "_ffmpeg",
                        lambda command, *a, **kw: commands.append(command))
    monkeypatch.setattr(video_rolling.gate, "blocked", lambda: False)
    video_rolling._clip_frames(source, tmp_path / "context.mp4",
                               start=120, count=25,
                               cancel=threading.Event(), owner="test")
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("-crf") + 1] == str(video_rolling.CLIP_CRF) == "0"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    # Only a frame-selection and timestamp transform: do not smooth away
    # blinks, irises or facial expressions in the transport layer.
    assert command[command.index("-vf") + 1].startswith("select=")
    assert "scale=" not in command[command.index("-vf") + 1]


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
                    reason='FFmpeg and FFprobe required')
def test_lossless_tail_keeps_decoded_pixels_and_concat_has_exact_av_clocks(tmp_path, monkeypatch):
    # Provider defaults point to Homebrew on macOS; resolve tools from the
    # active test runner so the smoke test also works on Ubuntu Actions.
    monkeypatch.setattr(video_providers, 'FFPROBE', shutil.which('ffprobe'))
    monkeypatch.setattr(video_rolling.gate, 'blocked', lambda: False)
    monkeypatch.setattr(video_rolling, 'FFMPEG', shutil.which('ffmpeg'))
    monkeypatch.setattr(video_rolling, '_ffmpeg',
        lambda cmd, *args, **kw: subprocess.run(cmd, check=True, capture_output=True, timeout=45))
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=128x64:r=24',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
        '-t',str(145/24),'-c:v','libx264','-crf','18','-c:a','aac',str(source)],check=True)
    cancel=threading.Event()
    tail=tmp_path/'tail.mp4'
    video_rolling._clip_frames(source,tail,start=120,count=25,cancel=cancel,owner='test')
    def pixels(path, selection):
        return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0',
            '-vf',selection,'-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','-'])
    assert pixels(source,"select='between(n,120,144)'") == pixels(tail,'null')
    parts=[]
    for index,count in enumerate((145,48,48)):
        p=tmp_path/f'part-{index}.mp4'
        video_rolling._clip_frames(source,p,start=0,count=count,cancel=cancel,owner='test')
        parts.append(p)
    output=tmp_path/'result.mp4'
    video_rolling._concat(parts,output,{'width':128,'height':64},cancel,'test')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
        '-show_frames','-select_streams','v:0','-of','json',str(output)]))
    pts=[float(f['best_effort_timestamp_time']) for f in probe['frames']]
    assert len(pts)==241 and pts[0]==0
    assert all(abs(t-i/24)<.00001 for i,t in enumerate(pts))
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
        '-of','json',str(output)]))['streams']
    audio=next(s for s in streams if s['codec_type']=='audio')
    assert float(audio['start_time'])==0
    # AAC has 1024-sample access units and FFmpeg muxers may report a
    # sub-millisecond duration rounding difference across platforms.
    # Use exact stream ticks and a strict 1 ms end alignment requirement;
    # do not confuse container duration with individual PCM sample accuracy.
    audio_end = int(audio['duration_ts']) * Fraction(audio['time_base'])
    assert abs(audio_end - Fraction(241, 24)) < Fraction(1, 1000)
    assert audio['codec_name']=='aac'
    assert probe['streams'][0]['pix_fmt']=='yuv420p'
    assert probe['streams'][0]['profile']!='High 4:4:4 Predictive'


@pytest.fixture
def rolling_checkpoints(tmp_path, monkeypatch):
    root=tmp_path/'model'
    root.mkdir()
    (root/'embedded_config.json').write_text('{}')
    monkeypatch.setattr(video_rolling.video_registry,'model_path',lambda _:root)
    monkeypatch.setattr(video_rolling.video_long,'runtime_version',lambda:'pinned-runtime')
    monkeypatch.setattr(video_rolling,'_validate_canvas',lambda _:None)
    monkeypatch.setattr(video_rolling,'shutdown_warm_runtime',lambda:None)
    info={'width':64,'height':128,'fps':24,'frames':145,'duration':145/24,'audio':False}
    def validate(path,frames,params):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('invalid checkpoint')
        return dict(info,frames=frames,duration=frames/24)
    monkeypatch.setattr(video_rolling,'_validate_part',validate)
    def clip(source,dest,**kwargs):
        dest.write_bytes(source.read_bytes())
        return validate(dest,kwargs['count'],{})
    monkeypatch.setattr(video_rolling,'_clip_frames',clip)
    monkeypatch.setattr(video_rolling,'_concat',lambda *a:dict(info,frames=241,duration=241/24))
    calls=[]
    def generate(model,params,output,**kw):
        calls.append('initial');output.write_bytes(b'initial')
    def extend(source,output,*args):
        calls.append('extend');output.write_bytes(b'extension')
    monkeypatch.setattr(video_rolling.video_long,'extend',extend)
    cancel=threading.Event()
    params={'duration':10,'resolution':'720p','fps':24,'width':64,'height':128,
            'seed':0,'prompt':'Natural movement','first_frame':None}
    directory=tmp_path/'checkpoints'
    def run(job='a'*24,resume=None,update=lambda **kw:None):
        return video_rolling.run({'id':'test','provider':'ltx-mlx'},params,tmp_path/'output.mp4',
            job_id=job,checkpoints=directory,resume_job=resume,generate=generate,cancel_event=cancel,
            response_callback=lambda _:None,progress_callback=lambda _:None,
            phase_callback=lambda _:None,update=update)
    return run,calls,cancel,directory


def test_rolling_cancel_then_explicit_resume_is_rejected(rolling_checkpoints):
    run,calls,cancel,directory=rolling_checkpoints
    def stop(**fields):
        if fields.get('checkpoint_count')==1:cancel.set()
    with pytest.raises(video_rolling.ProviderCancelled):run(update=stop)
    assert calls==['initial']
    assert len(json.loads((directory/('a'*24)/'checkpoint.json').read_text())['stages'])==1
    cancel.clear()
    with pytest.raises(ValueError,match='abgebrochene'):
        run('b'*24,{'id':'a'*24,'status':'cancelled'})


def test_rolling_resume_reuses_verified_stages_and_rejects_tampering(rolling_checkpoints):
    run,calls,cancel,directory=rolling_checkpoints
    def stop(**fields):
        if fields.get('checkpoint_count')==1:cancel.set()
    with pytest.raises(video_rolling.ProviderCancelled):run(update=stop)
    cancel.clear()
    result=run('b'*24,{'id':'a'*24,'status':'failed'})
    assert result['frames']==241 and calls==['initial','extend','extend']
    (directory/('a'*24)/'part-0.mp4').write_bytes(b'tampered')
    with pytest.raises(RuntimeError,match='verändert'):
        run('c'*24,{'id':'a'*24,'status':'failed'})
    assert calls==['initial','extend','extend']


def test_rolling_transport_change_invalidates_old_checkpoint(rolling_checkpoints,monkeypatch):
    run,calls,cancel,directory=rolling_checkpoints
    run()
    monkeypatch.setattr(video_rolling,'CONDITIONING_VERSION',2)
    with pytest.raises(ValueError,match='anderen Konfiguration'):
        run('b'*24,{'id':'a'*24,'status':'failed'})


@pytest.mark.parametrize(
    "explicit,legacy_lock,expected",
    [(None, True, "full"), (None, False, "off"),
     ("off", True, "off"), ("off", False, "off"),
     ("minimal", True, "minimal"), ("minimal", False, "minimal"),
     ("full", True, "full"), ("full", False, "full")],
)
def test_rolling_guidance_modes_are_independent_of_legacy_identity_lock(
        explicit, legacy_lock, expected):
    params = {"prompt": "Person smiles and naturally blinks",
              "first_frame": "/managed/original.png",
              "identity_lock": legacy_lock, "face_guidance": explicit}
    assert video_rolling._face_guidance_mode(params) == expected
    initial = video_rolling._face_prompt(params, extension=False)
    continued = video_rolling._face_prompt(params, extension=True)
    if expected == "off":
        assert initial == continued == params["prompt"]
    elif expected == "minimal":
        assert initial.startswith(video_rolling.MINIMAL_INITIAL_FACE_GUIDANCE)
        assert continued.startswith(video_rolling.MINIMAL_EXTEND_FACE_GUIDANCE)
    else:
        assert initial.startswith(video_rolling.INITIAL_FACE_GUIDANCE)
        assert continued.startswith(video_rolling.EXTEND_FACE_GUIDANCE)
    assert initial.endswith(params["prompt"])
    assert continued.endswith(params["prompt"])
    assert params["prompt"] == "Person smiles and naturally blinks"


def test_rolling_guidance_never_affects_text_to_video():
    params = {"prompt": "A beach with waves", "face_guidance": "full",
              "first_frame": None}
    assert video_rolling._face_prompt(params, extension=False) == params["prompt"]
    assert video_rolling._face_prompt(params, extension=True) == params["prompt"]


def test_face_guidance_api_accepts_only_rolling_i2v_or_6s_720p_pilot(monkeypatch):
    monkeypatch.setattr(video_service, "validate_first_frame",
                        lambda _: Path("/managed/source.png"))
    monkeypatch.setattr(video_service, "i2v_source_size", lambda _: (704, 1280))

    def req(duration=10, quality="standard", continuation="rolling", **options):
        return video_service.JobCreate(
            operation="i2v", chat_id="probe", chat_revision=0,
            payload={"prompt": "A person smiles and naturally blinks",
                     "quality": quality, "duration": duration,
                     "continuation_mode": continuation,
                     "first_frame": "/managed/source.png",
                     "aspect_ratio": "9:16", **options},
        )

    assert req(face_guidance="off").payload.face_guidance == "off"
    assert req(face_guidance="minimal").payload.face_guidance == "minimal"
    assert req(face_guidance="full").payload.face_guidance == "full"
    assert req().payload.face_guidance is None
    assert req(duration=6, continuation="segmented", face_guidance="minimal").payload.duration == 6
    with pytest.raises(ValueError):
        req(duration=10, continuation="segmented", face_guidance="minimal")
    with pytest.raises(ValueError):
        req(duration=6, quality="fast", continuation="segmented", face_guidance="minimal")
    with pytest.raises(ValueError):
        req(duration=5, continuation="segmented", face_guidance="minimal")
    for invalid in ["auto", "", "MINIMAL", False, 0, "none"]:
        with pytest.raises(ValueError):
            req(face_guidance=invalid)
    with pytest.raises(ValueError):
        video_service.JobCreate(
            operation="t2v", chat_id="probe", chat_revision=0,
            payload={"prompt": "A beach scene", "quality": "standard",
                     "duration": 10, "continuation_mode": "rolling",
                     "face_guidance": "minimal"},
        )


def test_6s_720p_guidance_changes_prompt_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(video_service, "validate_first_frame",
                        lambda _: Path("/managed/source.png"))
    monkeypatch.setattr(video_service, "i2v_source_size", lambda _: (704, 1280))
    original = "The person blinks naturally while smiling."

    def make(mode=None):
        options = {"face_guidance": mode} if mode is not None else {}
        return video_service.JobCreate(
            operation="i2v", chat_id="probe", chat_revision=0,
            payload={"prompt": original, "quality": "standard", "duration": 6,
                     "first_frame": "/managed/source.png",
                     "aspect_ratio": "9:16", **options},
        )
    default_request = make()
    default_params = video_service._direct_generation_params(default_request)
    assert default_params["prompt"] == original
    assert default_request.payload.prompt == original

    no_guidance = make("off")
    assert video_service._direct_generation_params(no_guidance)["prompt"] == original

    minimal = make("minimal")
    minimal_params = video_service._direct_generation_params(minimal)
    assert minimal_params["prompt"].startswith(video_rolling.MINIMAL_INITIAL_FACE_GUIDANCE)
    assert minimal_params["prompt"].endswith(original)
    assert minimal.payload.prompt == original
    assert minimal_params["first_frame"] == default_params["first_frame"]
    for key in ("seed", "frames", "fps", "width", "height", "steps",
                "aspect_ratio", "resolution", "quality", "resize_mode"):
        assert minimal_params[key] == default_params[key]

    full = make("full")
    assert video_service._direct_generation_params(full)["prompt"].startswith(
        video_rolling.INITIAL_FACE_GUIDANCE)
