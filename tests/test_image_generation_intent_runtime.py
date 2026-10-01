from types import SimpleNamespace
import sys

from agent import image_generation_intent_runtime as runtime


def test_portrait_generation_intent_matches_natural_prompts():
    assert runtime.is_portrait_generation_request(
        "Erstelle ein fotorealistisches Porträt einer Frau bei natürlichem Fensterlicht"
    )
    assert runtime.is_portrait_generation_request(
        "Create a photorealistic portrait of a woman in natural window light"
    )
    assert runtime.is_portrait_generation_request(
        "Generiere einen Headshot mit weichem Studiolicht"
    )


def test_portrait_reference_without_generation_verb_stays_chat():
    assert not runtime.is_portrait_generation_request(
        "Wie findest du dieses Porträt?"
    )


def test_install_runtime_extends_existing_detector(monkeypatch):
    fake_agent_app = SimpleNamespace(
        _looks_like_image_generation_request=lambda prompt: prompt == "existing image request"
    )
    monkeypatch.setitem(sys.modules, "agent.app", fake_agent_app)

    installed = runtime.install_runtime()

    assert installed("existing image request")
    assert installed(
        "Erstelle ein fotorealistisches Porträt einer Frau bei natürlichem Fensterlicht"
    )
    assert not installed("Erkläre mir Porträtfotografie")
    assert runtime.install_runtime() is installed


def test_production_entrypoint_installs_runtime():
    source = open("agent/entrypoint.py", encoding="utf-8").read()
    assert "install_image_generation_intent_runtime()" in source
