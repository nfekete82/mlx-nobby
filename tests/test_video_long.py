"""No LTX/Metal is loaded. FFmpeg uses small synthetic CPU-only fixtures."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import sys
import time
from unittest import mock

import pytest

import ai_lifecycle_gate as gate
import video_long as long
import video_service as service
from video_providers import ProviderCancelled


@pytest.mark.parametrize("duration,frames,amounts", [(5,121,[0]), (10,241,[0,12,3]),
    (20,481,[0,12,12,12,9]), (30,721,[0,12,12,12,12,12,12,3])])
def test_exact_1080_timeline_plan(duration, frames, amounts):
    result = long.plan(duration, "1080p")
    assert result["frames"] == frames
    assert [stage["extend_latents"] for stage in result["stages"]] == amounts
    assert all(stage["frames"] % 8 == 1 for stage in result["stages"])
    assert (frames - 1)/24 == duration


@pytest.mark.parametrize("resolution,duration,count", [("540p",20,1),("720p",10,1),("720p",20,4),("540p",30,4)])
def test_existing_direct_limits_and_automatic_extension(resolution,duration,count):
    assert len(long.plan(duration,resolution)["stages"]) == count


def test_60_seconds_and_incompatible_fps_are_not_silently_accepted():
    with pytest.raises(ValueError): long.plan(60,"1080p")
    with pytest.raises(ValueError): long.plan(20,"1080p",8)


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    (root / "embedded_config.json").write_text("{}")
    monkeypatch.setattr(long, "runtime_version", lambda: long.EXPECTED_HEAD)
    monkeypatch.setattr(long.video_registry, "model_path", lambda model: root)
    # Synthetic media validates actual dimensions/rate/frame count; it is not
    # evidence of 1080p model quality or of the model's perceptual continuity.
    params = {"duration":20,"resolution":"1080p","fps":24,"width":64,"height":64,
              "seed":42,"prompt":"Continue the same camera flight", "quality":"quality","profile":"standard"}
    model = {"id":"ltx-2.5-mlx-q4","provider":"ltx-mlx"}
    checkpoints = tmp_path / "checkpoints"
    events, calls = [], []
    cancel = threading.Event()
    def make(path, frames):
        subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=blue:s=64x64:r=24",
                        "-f","lavfi","-i","sine=frequency=1000:sample_rate=48000",
                        "-frames:v",str(frames),"-t",str(frames/24),"-c:v","libx264","-preset","ultrafast",
                        "-c:a","aac",str(path)],check=True,timeout=20)
    def generate(model, options, output, **callbacks):
        calls.append(("initial",options["frames"]))
        make(output, options["frames"])
        callbacks["progress_callback"]({"phase":"generating","step":2,"total_steps":8})
        return {"duration":options["duration"]}
    def extend(source, destination, amount, options, cancelled, update, owner):
        previous = long.capture(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=nb_frames","-of","csv=p=0",str(source)])
        frames = int(previous.strip()) + amount*8
        calls.append(("extend",source.name,amount,frames))
        make(destination, frames)
    monkeypatch.setattr(long,"extend",extend)
    import video_providers_mlx
    monkeypatch.setattr(video_providers_mlx,"shutdown_warm_runtime",lambda: None)
    def run(job_id="a"*24, resume=None, duration=20, update=None):
        return long.run(model,{**params,"duration":duration},tmp_path/f"{job_id}.mp4",job_id=job_id,
            checkpoints=checkpoints,resume_job=resume,generate=generate,cancel_event=cancel,
            response_callback=lambda runtime:None,progress_callback=lambda event:None,
            phase_callback=lambda phase:None,update=update or (lambda **fields:events.append(fields)))
    return run, calls, events, cancel, checkpoints, make, params


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="existing FFmpeg required")
def test_full_cumulative_clip_no_concat_and_real_ffprobe_validation(pipeline):
    run,calls,events,cancel,checkpoints,make,params = pipeline
    result=run()
    assert result["frames"] == 481 and result["timeline_seconds"] == 20
    assert result["stage_count"] == 5 and result["audio"]
    assert calls[0] == ("initial",121)
    assert [call[1] for call in calls[1:]] == [f"stage-{i}.mp4" for i in range(4)]
    saved=json.loads((checkpoints/('a'*24)/"checkpoint.json").read_text())
    assert len(saved["stages"]) == 5
    assert saved["stages"][1]["info"]["boundary_frames_checked"] == 2
    assert saved["stages"][1]["info"]["identical_boundary_pixels"]  # Deliberately static fixture: advisory, not failure.
    assert not list(checkpoints.rglob("*.partial.mp4"))


def test_failure_then_retry_reuses_only_verified_checkpoints(pipeline, monkeypatch):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    real=long.extend
    def fail(source,*args):
        if source.name == "stage-1.mp4": raise RuntimeError("synthetic LTX failure")
        return real(source,*args)
    monkeypatch.setattr(long,"extend",fail)
    with pytest.raises(RuntimeError,match="synthetic"):run()
    saved=json.loads((checkpoints/('a'*24)/"checkpoint.json").read_text())
    assert len(saved["stages"]) == 2
    monkeypatch.setattr(long,"extend",real)
    result=run('b'*24,{"id":'a'*24,"status":"failed"})
    assert result["frames"] == 481
    assert sum(call[0]=="initial" for call in calls) == 1
    assert sum(call[0]=="extend" and call[1]=="stage-0.mp4" for call in calls) == 1


def test_cancel_between_stages_preserves_checkpoint_without_next_extend(pipeline):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    def update(**fields):
        if fields.get("checkpoint_count")==1: cancel.set()
    with pytest.raises(ProviderCancelled):run(update=update)
    assert calls == [("initial",121)]
    assert (checkpoints/('a'*24)/"stage-0.mp4").exists()
    cancel.clear()
    with pytest.raises(ValueError,match="Expliziter Abbruch"):
        run('b'*24,{"id":'a'*24,"status":"cancelled"})


def test_shutdown_between_stages_blocks_next_model_load(pipeline):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    def update(**fields):
        if fields.get("checkpoint_count")==1: gate.set_blocked(True)
    with pytest.raises(ProviderCancelled):run(update=update)
    assert calls == [("initial",121)]


def test_wrong_intermediate_frame_count_is_never_checkpointed(pipeline,monkeypatch):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    monkeypatch.setattr(long,"extend",lambda source,destination,*args:make(destination,121))
    with pytest.raises(RuntimeError,match="inkonsistent"):run()
    saved=json.loads((checkpoints/('a'*24)/"checkpoint.json").read_text())
    assert len(saved["stages"]) == 1


def test_checkpoint_tampering_and_changed_options_reject_resume(pipeline):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    def stop(**fields):
        if fields.get("checkpoint_count")==1:cancel.set()
    with pytest.raises(ProviderCancelled):run(update=stop)
    cancel.clear()
    with pytest.raises(ValueError,match="geändert"):
        run('b'*24,{"id":'a'*24,"status":"failed"},duration=10)
    (checkpoints/('a'*24)/"stage-0.mp4").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError):run('c'*24,{"id":'a'*24,"status":"failed"})


def test_native_request_accepts_1080_long_but_keeps_direct_defaults():
    for duration in (5,10,20,30):
        request=service.JobCreate(operation="t2v",chat_id="test",chat_revision=0,
            payload={"prompt":"A city camera flight","quality":"quality","duration":duration})
        assert request.payload.width==1920 and request.payload.height==1088
        assert request.payload.frames==duration*24+1
    assert service.VideoPayload(prompt="A city camera flight").duration==5


def test_service_recovery_discovers_manifest_after_job_status_write_interruption(pipeline,monkeypatch,tmp_path):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    def stop(**fields):
        if fields.get("checkpoint_count")==1:cancel.set()
    with pytest.raises(ProviderCancelled):run(update=stop)
    jobs=checkpoints.parent
    (jobs/"long").mkdir()
    shutil.copytree(checkpoints/('a'*24),jobs/"long"/('a'*24))
    (jobs/('a'*24+'.json')).write_text(json.dumps({"id":'a'*24,"status":"generating","payload":params}))
    monkeypatch.setattr(service,"JOBS",jobs)
    monkeypatch.setattr(service,"_jobs",{})
    service._load_jobs()
    job=service._jobs['a'*24]
    assert job["status"]=="failed" and job["resumable"] and job["checkpoint_count"]==1


def test_five_second_plan_needs_no_extend(pipeline):
    run,calls,*_=pipeline
    result=run(duration=5)
    assert result["frames"]==121 and calls==[("initial",121)]


def test_lifecycle_checkpoint_can_be_resumed_by_explicit_retry(pipeline):
    run,calls,events,cancel,checkpoints,make,params=pipeline
    def stop(**fields):
        if fields.get("checkpoint_count")==1:gate.set_blocked(True)
    with pytest.raises(ProviderCancelled):run(update=stop)
    gate.set_blocked(False,"isolated verified restart")
    result=run('b'*24,{"id":'a'*24,"status":"failed","cancel_requested":True,"cancel_reason":"lifecycle"})
    assert result["frames"]==481
    assert sum(call[0]=="initial" for call in calls)==1


def test_silent_extend_stdout_does_not_block_real_process_cancellation(tmp_path,monkeypatch):
    cli=tmp_path/".venv/bin/ltx-2-mlx"
    cli.parent.mkdir(parents=True)
    ready=tmp_path/"ready"
    cli.write_text(f"#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index('--output')+1]).write_bytes(b'partial')\nPath({str(ready)!r}).touch()\ntime.sleep(60)\n")
    cli.chmod(0o755)
    monkeypatch.setattr(long,"RUNTIME",tmp_path)
    cancel=threading.Event()
    destination=tmp_path/"partial.mp4"
    errors=[]
    def run():
        try:
            long.extend(tmp_path/"input.mp4",destination,3,{"model_path":tmp_path,"prompt":"Synthetic test","seed":42},cancel,lambda **kw:None,"video:long:test")
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=run)
    thread.start()
    deadline=time.monotonic()+5
    while not ready.exists() and time.monotonic()<deadline:time.sleep(.03)
    assert ready.exists()
    cancel.set()
    thread.join(6)
    assert not thread.is_alive() and len(errors)==1 and isinstance(errors[0],ProviderCancelled)
    assert not destination.exists() and not gate.blocked()


def test_ffprobe_phase_is_cancellable_without_waiting_for_output():
    cancel=threading.Event()
    timer=threading.Timer(.2,cancel.set)
    timer.start()
    started=time.monotonic()
    try:
        with pytest.raises(ProviderCancelled):
            long.capture([sys.executable,"-c","import time; time.sleep(60)"],cancel)
    finally:timer.join(2)
    assert time.monotonic()-started<5
