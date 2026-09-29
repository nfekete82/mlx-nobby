from backend.media_routing_ui import MEDIA_ROUTING_SCRIPT, inject_media_routing_script


def test_media_routing_script_is_injected_once():
    body = b"<html><body><main>chat</main></body></html>"

    injected = inject_media_routing_script(body)

    assert MEDIA_ROUTING_SCRIPT in injected
    assert injected.count(MEDIA_ROUTING_SCRIPT) == 1
    assert inject_media_routing_script(injected) == injected


def test_media_routing_script_requires_body_marker():
    body = b"plain response"

    assert inject_media_routing_script(body) == body
