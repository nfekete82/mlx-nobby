import json
from pathlib import Path
from unittest import mock

from agent import shorts_caption_runtime, shorts_jobs
from agent.shorts_captions import (
    animated_subtitles_for_words,
    normalize_alignment_words,
    phrase_groups,
)
from agent.shorts_planner import ShortProject


def project():
    return ShortProject.model_validate({
        "title": "Berlin morgen",
        "duration": 10,
        "music_enabled": False,
        "scenes": [
            {
                "id": "scene-1",
                "duration": 5,
                "narration": "Berlin wird grüner und leiser.",
                "video_prompt": "Berlin skyline",
            },
            {
                "id": "scene-2",
                "duration": 5,
                "narration": "Autonome Bahnen verbinden die Stadt.",
                "video_prompt": "Autonomous tram",
            },
        ],
    })


def alignment():
    return {
        "words": [
            {"word": "Berlin", "start": 0.10, "end": 0.48, "probability": 0.99},
            {"word": "wird", "start": 0.50, "end": 0.74, "probability": 0.98},
            {"word": "grüner", "start": 0.76, "end": 1.12, "probability": 0.97},
            {"word": "und", "start": 1.14, "end": 1.31, "probability": 0.99},
            {"word": "leiser.", "start": 1.33, "end": 1.78, "probability": 0.99},
            {"word": "Autonome", "start": 5.20, "end": 5.72, "probability": 0.96},
            {"word": "Bahnen", "start": 5.74, "end": 6.10, "probability": 0.95},
        ],
    }


def test_alignment_words_are_sanitized_sorted_and_bounded():
    words = normalize_alignment_words({
        "words": [
            {"word": " later ", "start": 1.0, "end": 1.4, "probability": 1.5},
            {"word": "first", "start": -0.2, "end": 0.02},
            {"word": "outside", "start": 12.0, "end": 13.0},
            {"word": "bad", "start": "x", "end": 2.0},
        ],
    }, 10)

    assert [word["word"] for word in words] == ["first", "later"]
    assert words[0]["start"] == 0
    assert words[0]["end"] >= 0.06
    assert words[1]["probability"] == 1.0


def test_phrase_groups_break_on_sentence_and_large_silence():
    words = normalize_alignment_words(alignment(), 10)
    groups = phrase_groups(words)

    assert [[word["word"] for word in group] for group in groups] == [
        ["Berlin", "wird", "grüner", "und", "leiser."],
        ["Autonome", "Bahnen"],
    ]


def test_animated_ass_highlights_only_the_active_word():
    ass = animated_subtitles_for_words(project(), alignment())
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]

    assert len(dialogues) == 7
    assert dialogues[0].startswith("Dialogue: 0,0:00:00.10,0:00:00.50,Caption")
    assert "{\\c&H00D7FF&\\fs68\\b1}Berlin" in dialogues[0]
    assert "{\\c&H00D7FF&\\fs68\\b1}wird" in dialogues[1]
    assert "Berlin" in dialogues[1]
    assert "Style: Caption,Arial,60" in ass


def test_alignment_cache_is_reused_when_audio_and_text_match(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs, "SHORTS_DIRECTORY", tmp_path / "shorts")
    value = project()
    audio = tmp_path / "voiceover.mp3"
    audio.write_bytes(b"same voiceover")
    identity = shorts_caption_runtime._alignment_identity(value, audio)
    path = tmp_path / "alignment.json"
    path.write_text(json.dumps(identity | alignment()), encoding="utf-8")

    cached = shorts_caption_runtime._load_cached_alignment(path, identity)
    assert cached["words"][0]["word"] == "Berlin"

    audio.write_bytes(b"changed voiceover")
    changed = shorts_caption_runtime._alignment_identity(value, audio)
    assert shorts_caption_runtime._load_cached_alignment(path, changed) is None


def test_compose_wrapper_overwrites_scene_ass_with_word_timed_ass(tmp_path, monkeypatch):
    value = project()
    job = {
        "id": "a" * 24,
        "project": value.model_dump(mode="json"),
        "tts_path": str(tmp_path / "voiceover.mp3"),
    }
    Path(job["tts_path"]).write_bytes(b"voice")
    monkeypatch.setattr(shorts_caption_runtime.shorts_jobs, "get_short_job", lambda _job_id: job)
    monkeypatch.setattr(shorts_caption_runtime, "_alignment_for_job", lambda *_args: alignment())

    captured = {}

    def real_compose(command, *, cwd, cancel_check, timeout):
        captured["ass"] = (Path(cwd) / "subtitles.ass").read_text(encoding="utf-8")
        assert not cancel_check()

    def original(job_id, request_fn, compose_fn):
        (tmp_path / "subtitles.ass").write_text("scene fallback", encoding="utf-8")
        compose_fn(["ffmpeg"], cwd=tmp_path, cancel_check=lambda: False, timeout=10)
        return {"id": job_id, "status": "completed"}

    monkeypatch.setattr(shorts_caption_runtime, "_ORIGINAL_RUN_COMPOSE", original)
    result = shorts_caption_runtime._patched_run_compose(job["id"], mock.Mock(), real_compose)

    assert result["status"] == "completed"
    assert "Style: Caption" in captured["ass"]
    assert "{\\c&H00D7FF&" in captured["ass"]


def test_alignment_failure_keeps_existing_scene_caption_fallback(tmp_path, monkeypatch):
    value = project()
    job = {
        "id": "b" * 24,
        "project": value.model_dump(mode="json"),
        "tts_path": str(tmp_path / "voiceover.mp3"),
    }
    Path(job["tts_path"]).write_bytes(b"voice")
    monkeypatch.setattr(shorts_caption_runtime.shorts_jobs, "get_short_job", lambda _job_id: job)
    monkeypatch.setattr(
        shorts_caption_runtime,
        "_alignment_for_job",
        mock.Mock(side_effect=RuntimeError("speech offline")),
    )
    updates = []
    monkeypatch.setattr(
        shorts_caption_runtime.shorts_jobs,
        "_update_job",
        lambda job_id, **changes: updates.append((job_id, changes)) or job,
    )
    compose = mock.Mock()

    def original(job_id, request_fn, compose_fn):
        assert compose_fn is compose
        return {"id": job_id, "status": "completed"}

    monkeypatch.setattr(shorts_caption_runtime, "_ORIGINAL_RUN_COMPOSE", original)
    result = shorts_caption_runtime._patched_run_compose(job["id"], mock.Mock(), compose)

    assert result["status"] == "completed"
    assert updates[-1][1]["caption_alignment_status"] == "fallback"
    assert "speech offline" in updates[-1][1]["caption_alignment_error"]
