"""Read-only structured media/activity recall from fictional saved chats."""
from __future__ import annotations

import pytest

from agent import chat_archive
from agent import archive_activity_context
from agent import media_memory_context
from agent import media_library_routes
from agent import personal_memory as pm


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_archive, "DB_PATH", tmp_path / "private-fts.sqlite3")
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "private-facts.sqlite3")
    monkeypatch.setattr(media_library_routes, "list_assets", lambda kind="all", limit=80: {
        "assets": [], "total": 0, "limit": limit,
    })


def creative_chat(status="completed", prompt="Eine fliegende Sandforge-Bastion"):
    return {
        "id": "creative-project", "title": "Sandforge Media",
        "updated": 200,
        "messages": [
            {"role": "user", "content": "Erstelle ein Video: " + prompt},
            {"role": "assistant", "content": "",
             "video_job": {
                 "id": "fictional-job", "status": status,
                 "payload": {"prompt": prompt, "model": "LTX-2.5"},
                 "result": {"video_id": "123456abcdef"},
             },
             "tool_result": {
                 "tool": "video_generate", "status": status,
                 "data": {"job": {
                     "status": status,
                     "payload": {"prompt": prompt, "model": "LTX-2.5"},
                 }},
                 "artifacts": [{"video_id": "123456abcdef"}],
             }},
        ],
    }


def test_disabled_does_not_index_or_leak_activity():
    assert not chat_archive.enabled()
    assert not chat_archive.DB_PATH.exists()
    assert chat_archive.index_chat(creative_chat()) is False
    assert archive_activity_context.context("Welche Videos erstelle ich?") == ""
    assert not chat_archive.DB_PATH.exists()


def test_video_metadata_and_source_are_structured_and_deduplicated():
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat())
    result = archive_activity_context.inventory(kind="video")
    assert result["total"] == 1
    record = result["activities"][0]
    assert record["chat_id"] == "creative-project"
    assert record["ordinal"] == 1
    assert record["kind"] == "video"
    assert record["operation"] == "video_generate"
    assert record["status"] == "completed"
    assert record["model"] == "LTX-2.5"
    assert "Sandforge-Bastion" in record["prompt"]
    assert record["project"] == "Sandforge Media"
    assert record["artifact_ref"] == "123456abcdef"
    chat_archive.index_chat(creative_chat())
    assert archive_activity_context.inventory()["total"] == 1
    summary = chat_archive.context("Welche Videos erstelle ich?")
    assert "LTX-2.5" in summary
    assert "creative-project" in summary


def test_status_changes_do_not_create_second_activity():
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat(status="running"))
    assert archive_activity_context.inventory(kind="video")["activities"][0]["status"] == "running"
    chat_archive.index_chat(creative_chat(status="completed"))
    result = archive_activity_context.inventory(kind="video")
    assert result["total"] == 1
    assert result["activities"][0]["status"] == "completed"
    assert "video/completed=1" in archive_activity_context.context("Video")


def test_removed_chat_purges_derived_activity_and_search():
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat())
    assert archive_activity_context.inventory()["total"] == 1
    chat_archive.remove_chat("creative-project", exclude=True)
    assert archive_activity_context.inventory()["total"] == 0
    assert chat_archive.search("Sandforge") == []
    chat_archive.rebuild([creative_chat()])
    assert archive_activity_context.inventory()["total"] == 0


def test_rebuild_prunes_old_activity_when_chat_deleted():
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat())
    chat_archive.rebuild([])
    assert archive_activity_context.inventory()["total"] == 0


def test_media_library_verified_results_are_separate_from_job_history(monkeypatch):
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat(status="failed"))
    monkeypatch.setattr(media_library_routes, "list_assets", lambda kind="all", limit=80: {
        "assets": [{
            "id": "ab123456cdef", "kind": "video", "model": "LTX-2.5",
            "prompt": "Ein kleiner Roboter über Sanddünen",
            "operation": "t2v",
        }], "total": 1, "limit": limit,
    })
    result = chat_archive.context("Welche Videos habe ich erstellt?")
    assert "video/failed=1" in result
    assert "VERIFIED LOCAL GENERATED MEDIA LIBRARY" in result
    assert "Ein kleiner Roboter" in result
    assert "Currently present media assets (kind=video): 1" in result


def test_duplicate_prompts_fold_in_summary_not_activity_ledger():
    chat_archive.set_enabled(True)
    a = creative_chat()
    b = creative_chat()
    b["id"] = "other"
    chat_archive.index_chat(a)
    chat_archive.index_chat(b)
    result = archive_activity_context.inventory(kind="video")
    assert result["total"] == 2
    summary = archive_activity_context.context("Welche Videos erstelle ich?")
    assert "Recorded actions: 2" in summary
    assert summary.count("brief=Eine fliegende Sandforge-Bastion") == 1


def test_unrelated_chat_does_not_receive_media_details():
    chat_archive.set_enabled(True)
    chat_archive.index_chat(creative_chat())
    assert archive_activity_context.context("Erkläre CSS Grid") == ""


def test_tool_payload_is_not_indexed_as_raw_text():
    chat_archive.set_enabled(True)
    c = creative_chat()
    c["messages"][1]["tool_result"]["data"]["private"] = "SENTINEL_SECRET_PAYLOAD"
    chat_archive.index_chat(c)
    assert chat_archive.search("SENTINEL_SECRET_PAYLOAD") == []
    assert "SENTINEL_SECRET_PAYLOAD" not in str(archive_activity_context.inventory())
