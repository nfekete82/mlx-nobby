"""Security and correctness tests for optional on-device semantic memory.

All prompts, personal names and chat IDs below are fictional. Tests do not run
a model, access user conversations, or make any network requests.
"""
import json
import threading
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import personal_memory as pm
from agent import memory_dashboard
from agent import semantic_personal_memory as smart
from agent.smart_memory_routes import install_routes


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "personal-memory.sqlite3")
    monkeypatch.setattr(memory_dashboard, "STATE_PATH", tmp_path / "control.json")
    monkeypatch.setattr(smart, "_READER", None)
    monkeypatch.setattr(smart, "_CHAT_LOCK", None)
    monkeypatch.setattr(smart, "_COMPLETE", None)


def synthetic_result(**candidate):
    return json.dumps({"facts": [candidate]}, ensure_ascii=False)


def fact(text, *, subject="partner", field="beruf", value="Psychologin",
         confidence=.98, evidence=None, correction=False):
    return synthetic_result(
        subject=subject, field=field, value=value,
        evidence=evidence if evidence is not None else text,
        confidence=confidence, correction=correction,
    )


def test_explicit_opt_in_without_creating_private_database():
    assert smart.enabled() is False
    assert not pm.DB_PATH.exists()
    assert smart.parse_facts('{"facts":[]}', "Meine Partnerin ist Psychologin") == []
    with pytest.raises(ValueError):
        smart.set_enabled(True)
    assert not pm.DB_PATH.exists()
    pm.set_enabled(True)
    assert smart.enabled() is False
    assert smart.set_enabled(True)["enabled"] is True
    assert smart.enabled() is True
    smart.set_enabled(False)
    assert smart.enabled() is False


def test_grounded_local_model_facts_and_provenance_history():
    pm.set_enabled(True)
    smart.set_enabled(True)
    a = "Meine Partnerin ist Psychologin."
    stored = smart.apply("synthetic-chat", 0, a, fact(a))
    assert stored["action"] == "processed"
    rows = pm.list_facts()
    assert len(rows) == 1
    assert rows[0]["value"] == "Psychologin"
    assert rows[0]["source_chat_id"] == "synthetic-chat"
    assert rows[0]["source_ordinal"] == 0
    assert smart.apply("synthetic-chat", 0, a, fact(a))["action"] == "unchanged"
    assert len(pm.list_facts(history=True)) == 1


def test_contradiction_queues_and_explicit_correction_replaces_old():
    pm.set_enabled(True)
    smart.set_enabled(True)
    earlier = "Meine Partnerin ist Psychologin"
    smart.apply("one", 0, earlier, fact(earlier))
    newer = "Meine Partnerin ist Lehrerin"
    smart.apply("two", 0, newer, fact(newer, value="Lehrerin"))
    assert pm.list_facts()[0]["value"] == "Psychologin"
    assert len(pm.list_conflicts()) == 1
    correction = "Ich habe mich vertan, meine Partnerin ist Lehrerin"
    smart.apply("three", 0, correction,
        fact(correction, value="Lehrerin", correction=True))
    assert pm.list_facts()[0]["value"] == "Lehrerin"
    assert len(pm.list_conflicts()) == 0
    assert len(pm.list_facts(history=True)) == 2


def test_model_output_is_untrusted_and_cannot_invent_or_save_credentials():
    text = "Meine Partnerin ist Psychologin"
    forged = fact(text, value="Astronautin")
    assert smart.parse_facts(forged, text) == []
    assert smart.parse_facts(fact(text, confidence=.55), text) == []
    assert smart.parse_facts("ignore previous instructions", text) == []
    assert smart.parse_facts('{"facts":[]}', "Mein API Key ist XYZ") == []
    assert smart.parse_facts(fact(text, subject="admin", value="Psychologin"), text) == []
    assert smart.parse_facts(
        fact("Ich liebe Kaffee nicht mehr", subject="ich", field="vorliebe",
             value="Kaffee"),
        "Ich liebe Kaffee nicht mehr",
    ) == []


def test_hypotheticals_cannot_be_promoted_even_by_hallucinating_model():
    conditional = "Wenn ich Architekt wäre, würde ich Häuser bauen."
    output = fact(
        conditional, subject="ich", field="beruf",
        value="Architekt", evidence="Wenn ich Architekt wäre",
    )
    assert smart.parse_facts(output, conditional) == []

    possible = "Vielleicht bin ich bald Architekt."
    assert smart.parse_facts(
        fact(possible, subject="ich", field="beruf",
             value="Architekt", evidence=possible), possible,
    ) == []


def test_deleted_facts_do_not_reappear_on_new_model_output():
    pm.set_enabled(True)
    smart.set_enabled(True)
    text = "Meine Partnerin ist Psychologin"
    smart.apply("one", 0, text, fact(text))
    assert pm.delete_fact(pm.list_facts()[0]["id"])
    changed = "Meine Partnerin ist seit Jahren Psychologin"
    smart.apply("two", 0, changed, fact(changed))
    assert pm.list_facts() == []


def test_paused_or_opted_out_memory_does_not_store_inference():
    pm.set_enabled(True)
    smart.set_enabled(True)
    text = "Meine Partnerin ist Psychologin"
    memory_dashboard.set_paused(True)
    assert smart.apply("one", 0, text, fact(text))["action"] == "disabled"
    assert pm.list_facts() == []
    memory_dashboard.set_paused(False)
    smart.set_enabled(False)
    assert smart.apply("one", 0, text, fact(text))["action"] == "disabled"
    assert pm.list_facts() == []


def test_chat_deletion_and_edit_clear_semantic_observation():
    pm.set_enabled(True)
    smart.set_enabled(True)
    text = "Meine Partnerin ist Psychologin"
    smart.apply("one", 0, text, fact(text))
    with pm._connect() as conn:
        assert conn.execute("SELECT count(*) FROM smart_observed").fetchone()[0] == 1
    pm.remove_chat("one", exclude=True)
    with pm._connect() as conn:
        assert conn.execute("SELECT count(*) FROM smart_observed").fetchone()[0] == 0
    assert pm.list_facts() == []
    assert smart.apply("one", 0, text, fact(text))["action"] == "disabled"


def test_api_requires_real_boolean_and_returns_only_status():
    class Host:
        CHATS_LOCK = threading.RLock()
        @staticmethod
        def list_chats():
            return [{"id": "fake", "updated": 1, "messages": []}]
    app = FastAPI()
    install_routes(app, Host)
    with TestClient(app) as client:
        response = client.get("/api/smart-memory/status")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert client.post("/api/smart-memory/config",
                           json={"enabled": "true"}).status_code == 422
        assert client.post("/api/smart-memory/config",
                           json={"enabled": True}).status_code == 409
        pm.set_enabled(True)
        assert client.post("/api/smart-memory/config",
                           json={"enabled": True}).status_code == 200
        assert client.post("/api/smart-memory/backfill",
                           json={"limit": -1}).status_code == 422
        assert client.post("/api/smart-memory/backfill",
                           json={"limit": 12}).status_code == 200


def test_regex_memory_does_not_promote_negated_relationship_to_preference():
    pm.set_enabled(True)
    pm.observe("Ich mag Kaffee nicht mehr, ich trinke jetzt Tee")
    assert not any("Kaffee nicht" in entry["value"] for entry in pm.list_facts())



def test_saving_chat_schedules_nonblocking_real_worker_with_mock_local_qwen():
    pm.set_enabled(True)
    smart.set_enabled(True)
    text = "Meine Partnerin ist Psychologin"
    chat = {
        "id": "fictional-source", "updated": 123,
        "messages": [{"role": "user", "content": text}],
    }
    calls = []
    started = threading.Event()

    def fake_local_qwen(payload):
        message = json.loads(payload)["message"]
        calls.append(message)
        started.set()
        return fact(message)

    smart.configure(
        chat_reader=lambda chat_id: chat if chat_id == chat["id"] else None,
        chat_lock=threading.RLock(),
        model_complete=fake_local_qwen,
    )
    before = time.monotonic()
    assert smart.enqueue(chat) == 1
    assert time.monotonic() - before < 1.0  # No inference on the write path.
    assert started.wait(3)
    for _ in range(200):
        if pm.list_facts():
            break
        time.sleep(.01)
    assert calls == [text]
    assert pm.list_facts()[0]["source_chat_id"] == "fictional-source"
    assert pm.list_facts()[0]["source_ordinal"] == 0
    assert smart.enqueue(chat) == 0
