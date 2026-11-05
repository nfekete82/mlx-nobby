"""Dedicated loopback memory inference: no cloud, no live user data, no model swaps."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent import dedicated_memory_model as mm, personal_memory as pm
from agent import semantic_personal_memory as smart


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "memory.sqlite3")


@pytest.fixture
def local_server():
    requests = []
    behavior = {"redirect": False, "finish_reason": "stop"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != "/v1/models":
                self.send_error(404)
                return
            self._json({"data": [{"id": "Qwen-local-memory-4B"}]})

        def do_POST(self):
            if behavior["redirect"]:
                self.send_response(302)
                self.send_header("Location", "https://example.org/collect")
                self.end_headers()
                return
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(body)
            self._json({"choices": [{
                "message": {"content": '{"facts":[],"episodes":[]}'},
                "finish_reason": behavior["finish_reason"],
            }]})

        def _json(self, value):
            data = json.dumps(value).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address[1], requests, behavior
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_existing_chat_role_is_default_without_creating_database():
    assert mm.settings() == {"mode": "chat", "port": 8011, "model": ""}
    assert not pm.DB_PATH.exists()
    with pytest.raises(mm.MemoryModelError):
        mm.complete([{"role": "user", "content": "Hello"}])


def test_local_dedicated_model_is_persisted_and_serves_strict_extraction(local_server):
    port, received, behavior = local_server
    config = mm.configure({
        "mode": "dedicated", "port": port, "model": "Qwen-local-memory-4B",
    })
    assert config == mm.settings()
    assert pm.DB_PATH.exists()
    messages = [
        {"role": "system", "content": "Return exactly one JSON object."},
        {"role": "user", "content": "Ich arbeite mit PHP."},
    ]
    assert mm.complete(messages) == '{"facts":[],"episodes":[]}'
    assert len(received) == 1
    assert received[0]["model"] == "Qwen-local-memory-4B"
    assert received[0]["messages"] == messages
    assert received[0]["temperature"] == 0
    assert received[0]["stream"] is False
    # A foreground chat-model change does not touch the independently persisted model.
    assert mm.settings()["model"] == "Qwen-local-memory-4B"
    assert mm.configure({"mode": "chat"})["mode"] == "chat"
    assert mm.settings()["mode"] == "chat"
    assert mm.configure({"mode": "dedicated"})["mode"] == "dedicated"
    assert mm.complete(messages) == '{"facts":[],"episodes":[]}'


def test_dedicated_model_not_enabled_if_offline_or_model_mismatch(local_server):
    port, _received, _behavior = local_server
    with pytest.raises(mm.MemoryModelError, match="not served"):
        mm.configure({"mode": "dedicated", "port": port, "model": "wrong-model"})
    assert mm.settings()["mode"] == "chat"


@pytest.mark.parametrize("payload", [
    {"mode": "cloud"},
    {"mode": "dedicated", "port": 8000, "model": "Qwen-local-memory-4B"},
    {"mode": "dedicated", "port": 8010, "model": "Qwen-local-memory-4B"},
    {"mode": "dedicated", "port": 0, "model": "Qwen-local-memory-4B"},
    {"mode": "dedicated", "port": "8011", "model": "Qwen-local-memory-4B"},
    {"mode": "dedicated", "model": ""},
    {"mode": "dedicated", "model": "bad\nheader"},
    {"mode": "chat", "url": "https://example.org"},
])
def test_invalid_config_never_becomes_active(payload):
    with pytest.raises(ValueError):
        mm.configure(payload)
    assert mm.settings()["mode"] == "chat"


def test_response_redirect_is_blocked_even_from_loopback(local_server):
    port, received, behavior = local_server
    mm.configure({"mode": "dedicated", "port": port, "model": "Qwen-local-memory-4B"})
    behavior["redirect"] = True
    with pytest.raises(mm.MemoryModelError, match="unavailable"):
        mm.complete([{"role": "user", "content": "private fictional statement"}])
    assert received == []


def test_truncated_result_is_retryable_not_saved(local_server):
    port, _received, behavior = local_server
    mm.configure({"mode": "dedicated", "port": port, "model": "Qwen-local-memory-4B"})
    behavior["finish_reason"] = "length"
    with pytest.raises(mm.MemoryModelError, match="truncated"):
        mm.complete([{"role": "user", "content": "private fictional statement"}])


def test_adult_preference_is_eligible_for_grounded_fact_extraction():
    phrase = "Meine sexuelle Vorliebe sind offene Gespräche über Sex."
    output = json.dumps({"facts": [{
        "subject": "ich",
        "field": "vorliebe",
        "value": "offene Gespräche über Sex",
        "evidence": phrase,
        "confidence": 0.99,
        "correction": False,
    }], "episodes": []}, ensure_ascii=False)
    facts = smart.parse_facts(output, phrase)
    assert len(facts) == 1
    assert facts[0]["value"] == "offene Gespräche über Sex"
    assert facts[0]["sensitive"] is True
    assert "Adult intimate" in smart._SYSTEM


def test_dispatch_uses_chat_role_only_until_explicit_opt_in(local_server):
    port, received, behavior = local_server
    messages = [{"role": "user", "content": "synthetic preference"}]
    calls = []

    def chat_backend(incoming):
        calls.append(incoming)
        return '{"facts":[],"episodes":[]}'

    assert mm.extract(messages, chat_backend) == '{"facts":[],"episodes":[]}'
    assert calls == [messages]
    assert received == []

    mm.configure({"mode": "dedicated", "port": port,
                  "model": "Qwen-local-memory-4B"})
    assert mm.extract(messages, chat_backend) == '{"facts":[],"episodes":[]}'
    assert calls == [messages]
    assert len(received) == 1

    behavior["finish_reason"] = "length"
    with pytest.raises(mm.MemoryModelError):
        mm.extract(messages, chat_backend)
    # Fail closed; never silently send private extraction to a different model.
    assert calls == [messages]

    mm.configure({"mode": "chat"})
    assert mm.extract(messages, chat_backend) == '{"facts":[],"episodes":[]}'
    assert calls == [messages, messages]


def test_compact_profile_targets_small_model_with_shared_claim_rules():
    payload = json.dumps({"message": "Ich entwickle beruflich mit PHP.",
                          "context": ""}, ensure_ascii=False)
    standard = smart.extraction_messages(payload)
    assert standard == smart.extraction_messages(payload, profile="standard")
    assert standard[0]["content"] == smart._SYSTEM + smart._CLAIM_RULES
    dedicated = smart.extraction_messages(payload, profile="compact")
    assert dedicated[0]["content"] == smart._SYSTEM_COMPACT + smart._CLAIM_RULES
    assert dedicated[1] == standard[1]
    assert 'VERBOTEN als subject' in dedicated[0]["content"]
    assert 'value ein EXAKTER' in dedicated[0]["content"]
    assert 'intime/sexuelle Vorlieben' in dedicated[0]["content"]
    assert dedicated[0]["content"] != standard[0]["content"]
    with pytest.raises(ValueError, match="Unknown memory"):
        smart.extraction_messages(payload, profile="untrusted")


@pytest.mark.parametrize(("message", "subject", "field", "value"), [
    ("Ich arbeite als Fachinformatiker.", "ich", "beruf", "Fachinformatiker"),
    ("Ich bin in Wien geboren.", "ich", "geburtsort", "Wien"),
    ("Ich trainiere mit Kettlebells.", "ich", "hobby", "Kettlebells"),
    ("Meine sexuelle Vorliebe ist offene Kommunikation über Wünsche.",
     "ich", "vorliebe", "offene Kommunikation über Wünsche"),
    ("Mein Projekt NebulaBoard verwendet PostgreSQL.",
     "projekte.nebulaboard", "technologie", "PostgreSQL"),
])
def test_small_model_schema_examples_pass_existing_grounding(message, subject, field, value):
    output = json.dumps({"facts": [{
        "subject": subject, "field": field, "value": value,
        "evidence": message, "confidence": .99, "correction": False,
    }], "episodes": []}, ensure_ascii=False)
    facts = smart.parse_facts(output, message)
    assert len(facts) == 1
    assert facts[0]["value"] == value


def test_invalid_model_placeholders_and_invented_paraphrases_still_rejected():
    message = "Ich entwickle beruflich mit PHP und JavaScript."
    for subject, value in [
        ("personen.slug", "PHP"),
        ("geburtsort", "PHP"),
        ("ich", "PHP und JavaScript Entwickler"),
    ]:
        output = json.dumps({"facts": [{
            "subject": subject, "field": "technologie", "value": value,
            "evidence": message, "confidence": 1.0, "correction": False,
        }], "episodes": []}, ensure_ascii=False)
        assert smart.parse_facts(output, message) == []
