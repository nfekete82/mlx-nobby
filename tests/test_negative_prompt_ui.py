from backend.negative_prompt_ui import (
    NEGATIVE_PROMPT_EDITOR_ASSETS,
    inject_negative_prompt_editor,
)


def test_negative_prompt_editor_assets_are_injected_once():
    body = b"<html><body><main>chat</main></body></html>"

    injected = inject_negative_prompt_editor(body)

    assert NEGATIVE_PROMPT_EDITOR_ASSETS in injected
    assert injected.count(NEGATIVE_PROMPT_EDITOR_ASSETS) == 1
    assert inject_negative_prompt_editor(injected) == injected


def test_negative_prompt_editor_requires_body_marker():
    body = b"plain response"

    assert inject_negative_prompt_editor(body) == body


def test_negative_prompt_editor_loads_script_and_stylesheet():
    assert b"negative-prompt-editor.js" in NEGATIVE_PROMPT_EDITOR_ASSETS
    assert b"negative-prompt-editor.css" in NEGATIVE_PROMPT_EDITOR_ASSETS
