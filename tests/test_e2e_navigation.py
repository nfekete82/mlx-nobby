"""Safety regressions for deterministic browser chat navigation."""

from unittest import mock

import pytest

from tests.e2e.conftest import navigate_chat_page


def test_navigate_chat_requires_real_input_and_production_libraries():
    page = mock.Mock()
    navigate_chat_page(page, "http://127.0.0.1:12345")

    page.goto.assert_called_once_with(
        "http://127.0.0.1:12345/chat",
        wait_until="commit",
        timeout=15000,
    )
    page.locator.assert_called_once_with("#input")
    page.locator.return_value.wait_for.assert_called_once_with(timeout=10000)

    script = page.wait_for_function.call_args.args[0]
    for symbol in ("window.marked?.parse", "window.DOMPurify?.sanitize",
                   "window.hljs?.highlightElement"):
        assert symbol in script
    assert page.wait_for_function.call_args.kwargs == {"timeout": 10000}


def test_navigate_chat_fails_on_missing_external_libraries():
    page = mock.Mock()
    page.wait_for_function.side_effect = TimeoutError("vendor resource unavailable")
    with pytest.raises(TimeoutError, match="vendor resource unavailable"):
        navigate_chat_page(page, "http://127.0.0.1:12345")


def test_navigate_chat_fails_when_composer_never_appears():
    page = mock.Mock()
    page.locator.return_value.wait_for.side_effect = TimeoutError("no composer")
    with pytest.raises(TimeoutError, match="no composer"):
        navigate_chat_page(page, "http://127.0.0.1:12345")
    page.wait_for_function.assert_not_called()
