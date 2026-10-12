"""Final prose repair never broadens malformed tool actions or logs content."""
import pytest
from agent import prompts


def test_final_unescaped_quotes_are_repaired_without_model_call():
    raw = '{"action":"final","answer":"Das Modell heißt "iPhone 18" und ist angekündigt."}'
    assert prompts.parse_agent_json(raw) == {
        "action": "final", "answer": 'Das Modell heißt "iPhone 18" und ist angekündigt.'}


def test_final_repair_preserves_valid_unicode_escapes_and_newlines():
    raw = '{"action":"final","answer":"Größe: "groß".\\nPfad: C:\\\\tmp"}'
    assert prompts.parse_agent_json(raw)["answer"] == 'Größe: "groß".\nPfad: C:\\tmp'


def test_malformed_tool_arguments_are_not_leniently_interpreted():
    with pytest.raises(ValueError):
        prompts.parse_agent_json('{"action":"fetch_url","query":"https://example.org/"bad""}')


def test_extra_fields_in_malformed_final_are_not_leniently_accepted():
    with pytest.raises(ValueError):
        prompts.parse_agent_json('{"action":"final","answer":""bad"", "query":"private"}')


def test_parse_repair_logs_only_metadata(caplog, capsys):
    secret = 'private-token-1234'
    calls = []

    def llm(purpose, *args, **kwargs):
        calls.append(purpose)
        return secret

    with pytest.raises(ValueError):
        prompts.agent_choose_next_step_v2("inspect", [], observed_agent_llm=llm,
            agent_tool_description=lambda **kwargs: "tools",
            _looks_like_disk_usage_request=lambda goal: False)
    assert calls == ["agent.plan", "agent.plan_repair"]
    assert "chars=" in caplog.text
    assert secret not in caplog.text
    assert secret not in capsys.readouterr().out
