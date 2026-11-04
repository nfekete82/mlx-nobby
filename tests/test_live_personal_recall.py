"""Live-chat personal recall: broad overview, safe identity and topic continuity.

Synthetic records only. Tests never access the user's profile, real chats or
live private memory. A normal model request is not needed to validate prompt
construction; the existing middleware integration covers runtime delivery.
"""
import pytest

from agent import memory, memory_lifecycle, memory_dashboard, personal_memory as pm


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "personal.sqlite3")
    monkeypatch.setattr(memory, "ROOT", tmp_path / "nobby")
    monkeypatch.setattr(memory, "MEMORY_DB", tmp_path / "nobby" / "memory.db")
    monkeypatch.setattr(memory_dashboard, "STATE_PATH", tmp_path / "pause.json")


def _put(subject, field, value):
    return pm.create_fact(subject, field, value, sensitive=True)


def test_off_does_not_create_private_database_or_inject_facts():
    assert not pm.DB_PATH.exists()
    assert pm.context("Was weißt du über mich?") == ""
    assert pm.context("Erkläre CSS") == ""
    assert not pm.DB_PATH.exists()


def test_regular_chat_gets_small_stable_identity_but_no_unrelated_private_data():
    pm.set_enabled(True)
    _put("ich", "beruf", "Informatiker")
    _put("ich", "technologie", "PHP")
    _put("ich", "wohnort", "Musterstadt")
    _put("ich", "gesundheit", "Erfundener Gesundheitszustand")
    _put("partner", "gesundheit", "Erfundene Partnerdiagnose")
    regular = pm.context("Wie optimiere ich mein CSS?")
    assert "Informatiker" in regular
    assert "PHP" in regular
    assert "Musterstadt" not in regular
    assert "Erfundener Gesundheitszustand" not in regular
    assert "Erfundene Partnerdiagnose" not in regular


def test_project_and_family_recall_is_topic_aware():
    pm.set_enabled(True)
    _put("ich", "beruf", "Informatiker")
    _put("projekte.sandforge", "entscheidung", "Sandforge-KI soll Gelände umgehen")
    _put("familie.sohn", "name", "Emil")
    neutral = pm.context("Was ist bei CSS Grid sinnvoll?")
    assert "Sandforge-KI" not in neutral and "Emil" not in neutral
    project = pm.context("Wie verbessern wir Sandforge?")
    assert "Sandforge-KI" in project and "Emil" not in project
    family = pm.context("Wie heißt mein Sohn?")
    assert "Emil" in family and "Sandforge-KI" not in family


def test_explicit_user_overview_includes_facts_across_life_areas():
    pm.set_enabled(True)
    _put("ich", "beruf", "Informatiker")
    _put("partner", "beruf", "Architektin")
    _put("familie.tochter", "name", "Leni")
    _put("projekte.sandforge", "ziel", "Bessere Spiel-KI")
    for question in (
        "Was weißt du alles über mich?",
        "Fass zusammen, was du über mich weißt.",
        "What do you know about me?",
    ):
        context = pm.context(question)
        for item in ("Informatiker", "Architektin", "Leni", "Bessere Spiel-KI"):
            assert item in context, question
        assert "EXPLICIT USER REQUEST" in context


def test_superseded_value_does_not_appear_as_active_fact():
    pm.set_enabled(True)
    old = _put("partner", "beruf", "Architektin")
    pm.edit_fact(old["fact_id"], value="Lehrerin")
    context = pm.context("Was weißt du über mich?")
    assert "Lehrerin" in context
    assert "Architektin" not in context


def test_long_term_stored_memories_are_included_in_explicit_overview():
    memory.add("Für neue Webprojekte nutze ich Vue", pinned=True)
    text = memory.context("Was weißt du über mich?")
    assert "Vue" in text
    assert "OVERVIEW OF STORED LONG-TERM MEMORY" in text


def test_short_followup_reuses_previous_user_topic_only_for_retrieval():
    history = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Welche Strategie hilft Sandforge bei Klippen?"},
        {"role": "assistant", "content": "Pathfinding mit Kostenfeldern."},
        {"role": "user", "content": "und jetzt?"},
    ]
    query = memory.recall_query(history)
    assert "Sandforge" in query
    assert query.endswith("und jetzt?")
    assert history[-1]["content"] == "und jetzt?"
    assert memory.recall_query(history[:-1]) == history[1]["content"]


def test_live_chat_pipeline_includes_private_context_and_follows_pause(monkeypatch):
    pm.set_enabled(True)
    _put("ich", "beruf", "Informatiker")
    _put("projekte.sandforge", "ziel", "Bessere Spiel-KI")
    # Replace only the optional older lexical/semantic store. This tests the
    # real current personal-memory integration without external embeddings.
    monkeypatch.setattr(memory, "enrich_messages", lambda messages, **kw: messages)
    messages = [{"role": "user", "content": "Was weißt du über mich?"}]
    enriched = memory_lifecycle.enrich_messages(messages, observe=False)
    context = enriched[0]["content"]
    assert "Informatiker" in context
    assert "Bessere Spiel-KI" in context
    assert enriched[-1] == messages[-1]
    memory_dashboard.set_paused(True)
    assert memory_lifecycle.enrich_messages(messages, observe=False) == messages


def test_bounded_overview_and_no_injection_of_removed_fact():
    pm.set_enabled(True)
    for i in range(75):
        _put("projekte.projekt"+str(i), "ziel", "Ziel "+str(i))
    overview = pm.context("Was weißt du über mich?")
    assert len(overview) < 10000
    assert "additional stored facts" in overview
    fact = pm.list_facts()[0]
    pm.delete_fact(fact["id"])
    assert fact["value"] not in pm.context("Was weißt du über mich?")
