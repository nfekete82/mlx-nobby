"""Regression tests for private fact extraction, provenance and corrections."""
import sqlite3

import pytest

from agent import personal_memory as pm


@pytest.fixture(autouse=True)
def isolated_private_db(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "private" / "memory.sqlite3")


def user_chat(chat_id, *turns):
    return {"id": chat_id, "updated": 100, "messages": [
        {"role": "user", "content": turn} for turn in turns,
    ]}


def test_default_off_never_creates_file():
    assert pm.status()["enabled"] is False
    assert pm.observe("Meine Freundin heißt Alex") == []
    assert pm.index_chat(user_chat("a", "Meine Freundin heißt Alex"))["processed"] == 0
    assert not pm.DB_PATH.exists()


def test_partner_and_family_details_are_local_and_source_linked():
    pm.set_enabled(True)
    assert pm.index_chat(user_chat("conversation-1",
        "Meine Freundin heißt Alex",
        "Meine Freundin ist Psychologin",
        "Meine Freundin hat Lichen sclerosus",
        "Mein Sohn heißt Finn",
        "Meine Tochter heißt Mia",
    ))["processed"] == 5
    facts = pm.list_facts(limit=50)
    assert any(f["subject"] == "partner" and f["field"] == "name"
               and f["value"] == "Alex" for f in facts)
    assert any(f["subject"] == "partner" and f["field"] == "beruf"
               and f["value"].lower() == "psychologin" for f in facts)
    assert any(f["sensitive"] and f["field"] == "gesundheit" for f in facts)
    assert any(f["subject"] == "familie.sohn" for f in facts)
    assert any(f["subject"] == "familie.tochter" for f in facts)
    assert all(f["source_chat_id"] == "conversation-1" for f in facts)
    assert pm.DB_PATH.stat().st_mode & 0o777 == 0o600


def test_date_conflict_asks_before_changing_and_supports_yes_answer():
    pm.set_enabled(True)
    pm.index_chat(user_chat("chat1", "Mein Termin ist am 16. November"))
    pm.index_chat(user_chat("chat2", "Mein Termin ist am 18. November"))
    facts = pm.list_facts()
    assert len(facts) == 1
    assert "16" in facts[0]["value"]
    questions = pm.list_conflicts()
    assert len(questions) == 1
    assert "18" in questions[0]["proposed_value"]
    prompt = pm.question_for("Mein Termin ist am 18. November")
    assert "Ask which information is current" in prompt
    assert "16" in prompt and "18" in prompt
    pm.question_for("Ja, das neue Datum stimmt")
    assert pm.list_conflicts() == []
    assert "18" in pm.list_facts()[0]["value"]
    history = pm.list_facts(history=True)
    assert len(history) == 2
    assert any(f["status"] == "superseded" for f in history)


def test_old_fact_stays_on_explicit_rejection():
    pm.set_enabled(True)
    pm.observe("Mein Termin ist am 16. November")
    pm.observe("Mein Termin ist am 18. November")
    pm.question_for("Nein, das alte Datum stimmt")
    assert pm.list_conflicts() == []
    assert "16" in pm.list_facts()[0]["value"]


def test_explicit_date_move_updates_without_conflict():
    pm.set_enabled(True)
    pm.observe("Mein Termin ist am 16. November")
    pm.observe("Mein Termin wurde auf 18. November verschoben")
    assert "18" in pm.list_facts()[0]["value"]
    assert pm.list_conflicts() == []


def test_duplicate_messages_do_not_create_duplicate_facts_or_questions():
    pm.set_enabled(True)
    chat = user_chat("ch", "Meine Freundin heißt Kim")
    pm.index_chat(chat)
    pm.index_chat(chat)
    pm.observe("Meine Freundin heißt Kim")
    assert len(pm.list_facts()) == 1
    assert pm.list_conflicts() == []
    pm.index_chat(user_chat("ch2", "Meine Freundin heißt Lee"))
    pm.index_chat(user_chat("ch2", "Meine Freundin heißt Lee"))
    assert len(pm.list_conflicts()) == 1


def test_edits_and_deletion_remove_source_facts_and_conflicts():
    pm.set_enabled(True)
    pm.index_chat(user_chat("a", "Meine Freundin heißt Anna"))
    pm.index_chat(user_chat("b", "Meine Freundin heißt Beth"))
    assert len(pm.list_conflicts()) == 1
    pm.remove_chat("b", exclude=True)
    assert pm.list_conflicts() == []
    pm.index_chat(user_chat("b", "Meine Freundin heißt Beth"))
    assert pm.list_conflicts() == []
    pm.index_chat(user_chat("a", ""))
    assert pm.list_facts() == []
    assert pm.list_conflicts() == []


def test_manual_fact_edit_delete_and_history():
    pm.set_enabled(True)
    r = pm.create_fact("partner", "hobby", "Padel", sensitive=True)
    fid = r["fact_id"]
    updated = pm.edit_fact(fid, value="Tennis")
    assert updated["action"] == "added"  # superseded old fact, new active
    assert len(pm.list_facts(history=True)) == 2
    assert len(pm.list_facts()) == 1
    assert pm.delete_fact(updated["fact_id"])
    assert pm.list_facts() == []
    assert not pm.delete_fact("unknown")


def test_unambiguous_manual_conflict_resolution():
    pm.set_enabled(True)
    pm.observe("Meine Freundin heißt Marie")
    pm.observe("Meine Freundin heißt Julia")
    issue = pm.list_conflicts()[0]
    result = pm.resolve(issue["id"], "custom", custom_value="Elena")
    assert result["action"] == "updated"
    assert pm.list_conflicts() == []
    assert pm.list_facts()[0]["value"] == "Elena"


def test_search_and_disabled_privacy_purge():
    pm.set_enabled(True)
    pm.observe("Meine Freundin heißt Lisa")
    assert pm.list_facts(query="Lisa")
    assert "Lisa" in pm.context("meine Freundin")
    pm.set_enabled(False)
    assert pm.status()["active_facts"] == 0
    assert pm.list_facts() == []
    pm.set_enabled(True)
    assert pm.list_facts() == []
    assert not pm.context("Freundin")


def test_explicit_private_note_and_credential_exclusion():
    pm.set_enabled(True)
    pm.observe("Merke dir: Unsere gemeinsame Urlaubsplanung beginnt im Dezember")
    assert any(f["field"].startswith("notiz.") for f in pm.list_facts())
    pm.observe("Merke dir: mein Passwort lautet ABC123")
    assert not any("Passwort" in f["value"] for f in pm.list_facts())


def test_question_and_conditional_statements_not_asserted_as_facts():
    pm.set_enabled(True)
    pm.observe("Meine Freundin heißt Anna?")
    pm.observe("Wenn meine Freundin heißt Anna")
    assert pm.list_facts() == []


def test_rebuild_only_reads_source_text_and_obeys_exclusions():
    pm.set_enabled(True)
    pm.rebuild([user_chat("a", "Meine Freundin heißt Tina")])
    assert pm.list_facts()[0]["source_chat_id"] == "a"
    pm.remove_chat("a", exclude=True)
    pm.rebuild([user_chat("a", "Meine Freundin heißt Tina")])
    assert pm.list_facts() == []
    pm.include_chat("a")
    pm.rebuild([user_chat("a", "Meine Freundin heißt Tina")])
    assert pm.list_facts()
