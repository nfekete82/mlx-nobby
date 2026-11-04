"""Regression tests for private fact extraction, provenance and corrections."""
import sqlite3

import pytest

from agent import personal_memory as pm


@pytest.fixture(autouse=True)
def isolated_private_db(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "private" / "memory.sqlite3")


def user_chat(chat_id, *turns):
    return {"id": chat_id, "updated": 100, "messages": [
        {"role": "user", "content": turn} for turn in turns
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
        "Meine Freundin hat die Diagnose Beispielerkrankung",
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
    pm.question_for("Ja, das neue Datum stimmt", source_chat_id="chat2")
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
    assert pm.list_facts(history=True) == []
    # Source chat changes and future rebuilds cannot silently recreate a
    # specifically forgotten attribute; manual addition is an explicit opt-in.
    pm.index_chat(user_chat("a", "Meine Freundin heißt Clara"))
    assert pm.delete_fact(pm.list_facts()[0]["id"])
    pm.rebuild([user_chat("a", "Meine Freundin heißt Clara")])
    assert not any(f["subject"] == "partner" for f in pm.list_facts())
    pm.create_fact("partner", "name", "Clara")
    assert any(f["value"] == "Clara" for f in pm.list_facts())
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


def test_clarification_available_before_chat_autosave_finishes():
    pm.set_enabled(True)
    pm.index_chat(user_chat("old", "Mein Termin ist am 16. November"))
    # The model starts responding before the new chat's PUT reaches the Agent.
    instruction = pm.question_for("Mein Termin ist am 18. November")
    assert "16" in instruction and "18" in instruction
    assert "Ask which value" in instruction
    assert "16" in pm.list_facts()[0]["value"]
    assert pm.list_conflicts() == []
    # A normal autosave later creates the durable question.
    pm.index_chat(user_chat("new", "Mein Termin ist am 18. November"))
    assert len(pm.list_conflicts()) == 1


def test_pre_save_check_skips_identical_fact_and_clear_reschedule():
    pm.set_enabled(True)
    pm.observe("Mein Termin ist am 16. November")
    assert pm.question_for("Mein Termin ist am 16. November") == ""
    assert pm.question_for("Mein Termin wurde auf 18. November verschoben") == ""
    assert "16" in pm.list_facts()[0]["value"]


def test_edit_keeps_source_and_delete_purges_renamed_history():
    pm.set_enabled(True)
    pm.index_chat(user_chat('source-a', 'Meine Freundin heißt Beispielname'))
    original = pm.list_facts()[0]
    edited = pm.edit_fact(original['id'], field='rufname', value='Korrigiertername')
    fact = pm.list_facts()[0]
    assert fact['source_chat_id'] == 'source-a'
    assert fact['source_ordinal'] == 0
    assert pm.delete_fact(edited['fact_id'])
    assert pm.list_facts(history=True) == []
    pm.rebuild([user_chat('source-a', 'Meine Freundin heißt Beispielname')])
    pm.index_chat(user_chat('source-b', 'Meine Freundin heißt Beispielname'))
    assert pm.list_facts(history=True) == []


def test_optout_during_extraction_cannot_restore_private_facts(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    pm.set_enabled(True)
    extracting, resume = threading.Event(), threading.Event()
    extract = pm._extract

    def delayed(text):
        extracting.set()
        assert resume.wait(5)
        return extract(text)

    monkeypatch.setattr(pm, '_extract', delayed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(pm.observe, 'Meine Freundin heißt Testperson')
        assert extracting.wait(5)
        pm.set_enabled(False)
        resume.set()
        assert pending.result(timeout=5) == []
    assert pm.status()['active_facts'] == 0


def test_confirmation_in_another_chat_cannot_resolve_a_private_conflict():
    pm.set_enabled(True)
    pm.index_chat(user_chat('previous', 'Mein Termin ist am 16. November'))
    pm.index_chat(user_chat('question-chat', 'Mein Termin ist am 18. November'))
    pm.question_for('Ja, das neue Datum stimmt', source_chat_id='unrelated-chat')
    assert len(pm.list_conflicts()) == 1
    pm.question_for('Ja, das neue Datum stimmt', source_chat_id='question-chat')
    assert pm.list_conflicts() == []
    assert '18' in pm.list_facts()[0]['value']


def test_private_database_connection_closes_after_context():
    pm.set_enabled(True)
    with pm._connect() as connection:
        assert connection.execute('SELECT 1').fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')


def test_backfill_handles_newest_first_chat_lists_in_chronological_order():
    pm.set_enabled(True)
    older = user_chat('older', 'Mein Termin ist am 16. November') | {'updated': 100}
    newer = user_chat('newer', 'Mein Termin ist am 18. November') | {'updated': 200}
    pm.rebuild([newer, older])
    assert '16' in pm.list_facts()[0]['value']
    assert '18' in pm.list_conflicts()[0]['proposed_value']


def test_forgetting_and_chat_exclusion_survive_optout_reenable():
    pm.set_enabled(True)
    source = user_chat('forgotten-source', 'Meine Freundin heißt Beispielperson')
    excluded = user_chat('excluded-source', 'Mein Sohn heißt Beispielkind')
    pm.index_chat(source)
    pm.delete_fact(pm.list_facts()[0]['id'])
    pm.remove_chat('excluded-source', exclude=True)
    pm.set_enabled(False)
    pm.set_enabled(True)
    pm.rebuild([source, excluded])
    assert pm.list_facts(history=True) == []


def test_pre_review_database_history_migrates_before_rename_and_delete():
    pm.set_enabled(True)
    pm.create_fact('synthetic', 'attribute', 'Original value')
    current = pm.create_fact('synthetic', 'attribute', 'Newer value')
    with sqlite3.connect(pm.DB_PATH) as connection:
        connection.execute('DROP TABLE fact_lineage')
    assert len(pm.list_facts(history=True)) == 2
    edited = pm.edit_fact(current['fact_id'], field='renamed', value='Corrected value')
    pm.delete_fact(edited['fact_id'])
    assert pm.list_facts(history=True) == []



def test_correct_birth_date_in_normal_chat_preserves_revision_history():
    pm.set_enabled(True)
    pm.index_chat(user_chat("old", "Mein Geburtstag ist am 11. Mai 1982"))
    before = pm.list_facts()
    assert len(before) == 1
    assert before[0]["field"] == "geburtstag"
    assert before[0]["value"] == "11.05.1982"

    pm.index_chat(user_chat("new",
        "Ich habe mich bei meinem Geburtsdatum vertan. Richtig ist der 12.05.1982."))
    current = pm.list_facts()
    assert len(current) == 1
    assert current[0]["value"] == "12.05.1982"
    assert current[0]["source_chat_id"] == "new"
    assert pm.list_conflicts() == []
    history = pm.list_facts(history=True)
    assert len(history) == 2
    assert {entry["value"] for entry in history} == {"11.05.1982", "12.05.1982"}


def test_direct_chat_birth_date_correction_and_repeated_save_do_not_duplicate():
    pm.set_enabled(True)
    pm.index_chat(user_chat("old", "Mein Geburtsdatum ist der 10.10.1980"))
    corrected = user_chat("updated",
        "Bitte korrigiere mein Geburtsdatum auf den 12.05.1982.")
    pm.index_chat(corrected)
    pm.index_chat(corrected)
    assert pm.list_facts()[0]["value"] == "12.05.1982"
    assert len(pm.list_facts(history=True)) == 2
    assert pm.list_conflicts() == []


def test_invalid_birth_dates_are_not_learned_or_overwrite_old_value():
    pm.set_enabled(True)
    pm.observe("Mein Geburtstag ist am 12.05.1982")
    for invalid in ("31.02.1982", "32.05.1982", "12.13.1982", "12.05.1882"):
        pm.observe(f"Bitte korrigiere mein Geburtsdatum auf den {invalid}.")
    assert len(pm.list_facts(history=True)) == 1
    assert pm.list_facts()[0]["value"] == "12.05.1982"


def test_ambiguous_birth_date_stays_pending_until_confirmed_in_same_chat():
    pm.set_enabled(True)
    pm.index_chat(user_chat("old", "Mein Geburtstag ist am 11.05.1982"))
    pm.index_chat(user_chat("different", "Mein Geburtstag ist am 12.05.1982"))
    assert pm.list_facts()[0]["value"] == "11.05.1982"
    assert len(pm.list_conflicts()) == 1
    assert "MEMORY CLARIFICATION REQUIRED" in pm.question_for(
        "Mein Geburtstag ist am 12.05.1982", source_chat_id="different")
    pm.question_for("Ja, das neue Datum stimmt", source_chat_id="different")
    assert pm.list_facts()[0]["value"] == "12.05.1982"
    assert pm.list_conflicts() == []


def test_explicit_birth_date_will_not_learn_when_personal_layer_opted_out():
    assert pm.enabled() is False
    assert pm.index_chat(user_chat("nooptin",
        "Korrigiere mein Geburtsdatum auf den 12.05.1982"))["processed"] == 0
    assert not pm.DB_PATH.exists()
