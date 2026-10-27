"""Repeated classification is reusable; route authorization is never cached."""

import json
from unittest import mock

import pytest

from agent import app
from agent.router_turn_cache import RouterTurnCache
from backend import observability


def test_reuse_is_bound_to_trace_and_exact_inputs_and_expires():
    now = [0.0]
    cache = RouterTurnCache(ttl=5, capacity=2, clock=lambda: now[0])
    generate = mock.Mock(return_value='{"intent":"normal_chat"}')
    first = {"model": "router-a", "messages": ["question"]}
    assert cache.classify("turn-one", first, generate) == generate.return_value
    cache.classify("turn-one", first, generate)
    assert generate.call_count == 1
    cache.classify("turn-two", first, generate)
    cache.classify("turn-one", {**first, "model": "router-b"}, generate)
    assert len(cache.entries) == 2
    assert generate.call_count == 3
    now[0] = 6
    cache.classify("turn-one", first, generate)
    assert generate.call_count == 4
    assert len(cache.entries) == 1


def test_failures_invalid_json_and_oversized_results_are_not_cached():
    cache = RouterTurnCache()
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.classify("turn", {}, lambda: "invalid", validate=json.loads)
    assert not cache.entries
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cache.classify("turn", {}, lambda: (_ for _ in ()).throw(RuntimeError()))
    cache.classify("turn", {}, lambda: "x" * 8193)
    assert not cache.entries


def test_missing_trace_and_opt_out_do_not_reuse(monkeypatch):
    cache = RouterTurnCache()
    generate = mock.Mock(return_value="safe")
    cache.classify(None, {}, generate)
    cache.classify(None, {}, generate)
    monkeypatch.setenv("MLX_ROUTER_TURN_REUSE", "off")
    cache.classify("turn", {}, generate)
    cache.classify("turn", {}, generate)
    assert generate.call_count == 4 and not cache.entries


def test_classifier_only_reuses_identical_model_payloads(monkeypatch):
    cache = RouterTurnCache()
    monkeypatch.setattr(app, "turn_classifier_cache", cache)
    router = mock.Mock(return_value=json.dumps({
        "intent": "normal_chat", "confidence": 0.99, "requires_tools": False, "reason": "Knowledge question",
    }))
    monkeypatch.setattr(app, "router_llm", router)
    workspace = mock.Mock(return_value=None)
    monkeypatch.setattr(app.code_workspaces, "active_workspace", workspace)
    with observability.trace_context("classification-reuse-test"):
        original = app.semantic_intent_classifier("Zähle von eins bis zwölf.")
        assert app.semantic_intent_classifier("Zähle von eins bis zwölf.") == original
        assert router.call_count == 1
        app.semantic_intent_classifier("Eine andere Frage.")
        app.semantic_intent_classifier("Zähle von eins bis zwölf.", file_context={"kind": "text"})
        app.semantic_intent_classifier("Zähle von eins bis zwölf.", conversation_context=[{"role": "user", "content": "history"}])
        workspace.return_value = {"id": "new-workspace"}
        app.semantic_intent_classifier("Zähle von eins bis zwölf.")
    assert router.call_count == 5


def test_direct_workspace_and_execution_gates_still_run_after_reuse(monkeypatch):
    monkeypatch.setattr(app, "turn_classifier_cache", RouterTurnCache())
    monkeypatch.setattr(app.code_workspaces, "active_workspace", lambda **kw: None)
    router = mock.Mock(return_value=json.dumps({
        "intent": "normal_chat", "confidence": 0.99, "requires_tools": False, "reason": "Chat",
    }))
    monkeypatch.setattr(app, "router_llm", router)
    request = app.ChatActionRequest(prompt="Zähle von eins bis zwölf.", trace_id="route-and-execution-test")
    before = app.preflight_chat_action(request)
    after = app.run_chat_action(request)
    assert before["intent"] == after["data"]["routing"]["intent"] == "normal_chat"
    assert router.call_count == 1
    # Fresh workspace/media decisions take precedence over any cached classifier.
    monkeypatch.setattr(app, "_trusted_workspace_chat_action", lambda *a, **kw: "coding_agent")
    route = app.route_chat_action(request)
    assert route["intent"] == "coding_agent"
    assert router.call_count == 1


def test_injected_classifier_is_not_replaced_by_reuse(monkeypatch):
    monkeypatch.setattr(app.code_workspaces, "active_workspace", lambda **kw: None)
    classify = mock.Mock(return_value={"intent": "normal_chat", "confidence": 1, "requires_tools": False})
    with observability.trace_context("injected-classifier-test"):
        for _ in range(2):
            app.classify_chat_action_details("Zähle von eins bis zwölf.", classifier=classify)
    assert classify.call_count == 2


def test_cached_agent_classification_cannot_skip_execution_safety_gate(monkeypatch):
    monkeypatch.setattr(app, "turn_classifier_cache", RouterTurnCache())
    monkeypatch.setattr(app.code_workspaces, "active_workspace", lambda **kw: None)
    monkeypatch.setattr(app, "_manager_route_trigger_reasons", lambda *a, **kw: [])
    router = mock.Mock(return_value=json.dumps({
        "intent": "coding_agent", "confidence": 0.99, "requires_tools": True, "reason": "Code change",
    }))
    monkeypatch.setattr(app, "router_llm", router)
    gate = mock.Mock(return_value=False)
    monkeypatch.setattr(app, "_semantic_agent_route_allowed", gate)
    request = app.ChatActionRequest(prompt="Implementiere eine Python-Funktion.", trace_id="fresh-agent-gate-test")
    assert app.preflight_chat_action(request)["intent"] == "coding_agent"
    result = app.run_chat_action(request)
    assert router.call_count == 1
    gate.assert_called_once()
    assert result["tool"] == "normal_chat"
    assert result["data"]["routing"]["agent_gate"] == "rejected"
