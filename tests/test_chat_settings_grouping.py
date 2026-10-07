from pathlib import Path


HTML = Path("frontend/chat.html").read_text(encoding="utf-8")


def _pane(name: str) -> str:
    start = HTML.index(f'data-settings-pane="{name}"')
    next_pane = HTML.find('data-settings-pane="', start + 1)
    return HTML[start:] if next_pane == -1 else HTML[start:next_pane]


def test_chat_specific_appearance_controls_live_in_chat_settings():
    chat = _pane("general")
    appearance = _pane("appearance")

    assert 'data-settings-tab="general"' in HTML
    assert 'data-i18n="ui.chat">Chat</button>' in HTML
    assert 'id="chatFontSize"' in chat
    assert 'id="userBubbleColor"' in chat
    assert 'id="userBubbleHex"' in chat
    assert 'id="resetAppearance"' in chat

    assert 'id="chatFontSize"' not in appearance
    assert 'id="userBubbleColor"' not in appearance


def test_appearance_keeps_interface_language_only():
    appearance = _pane("appearance")
    assert 'id="interfaceLanguage"' in appearance
