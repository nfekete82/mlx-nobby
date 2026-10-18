from unittest import mock

from agent import profile
from backend.clock_context_routing import include_live_clock


def test_timeless_followups_do_not_inject_changing_clock(monkeypatch):
    monkeypatch.delenv("NOBBY_CLOCK_CONTEXT_ALWAYS", raising=False)
    messages = [{"role": "user", "content": "Wie funktioniert Apple Silicon?"}]
    assert include_live_clock(messages) is False
    messages.append({"role": "assistant", "content": "Unified Memory."})
    messages.append({"role": "user", "content": "Welche Vorteile bietet dieser gemeinsame Arbeitsspeicher für KI-Modelle?"})
    assert include_live_clock(messages) is False


def test_temporal_questions_keep_fresh_clock(monkeypatch):
    monkeypatch.delenv("NOBBY_CLOCK_CONTEXT_ALWAYS", raising=False)
    for query in ("Wie spät ist es jetzt?", "Welches Datum haben wir heute?",
                  "Wie alt werde ich morgen?", "Wann läuft meine Frist ab?",
                  "What time is it?", "What year is it?"):
        assert include_live_clock([{"role": "user", "content": query}]) is True


def test_ambiguous_or_multimodal_inputs_keep_clock():
    assert include_live_clock([]) is True
    assert include_live_clock([{"role": "user", "content": [{"type": "text", "text": "hi"}]}]) is True


def test_rollback_and_temporal_system_prompt(monkeypatch):
    monkeypatch.setenv("NOBBY_CLOCK_CONTEXT_ALWAYS", "1")
    assert include_live_clock([{"role": "user", "content": "Hi"}]) is True
    monkeypatch.delenv("NOBBY_CLOCK_CONTEXT_ALWAYS", raising=False)
    assert include_live_clock([{"role": "user", "content": "Hi"}], "Use the current host time for all responses") is True
    assert include_live_clock([{"role": "user", "content": "Hi"}], "For questions about today, dates or years, answer carefully") is False


def test_profile_can_skip_time_without_losing_profile_instructions():
    with mock.patch.object(profile, "load", return_value={
        "enabled": True,
        "custom_fields": [{"label": "Profession", "value": "Engineer", "enabled": True}],
        "fields": {"style_enabled": True, "personality_preset": "standard",
                   "style_brevity": 70, "style_humor": 50,
                   "style_directness": 50, "style_formality": 50,
                   "style_explanation": 50},
    }), mock.patch.object(profile.system_clock, "context", return_value="FRESH_CLOCK") as clock:
        stable = profile.context(include_clock=False)
        assert "FRESH_CLOCK" not in stable
        assert "Profession: Engineer" in stable
        assert "Prefer concise answers" in stable
        clock.assert_not_called()
        timed = profile.context()
        assert timed.startswith("FRESH_CLOCK")
