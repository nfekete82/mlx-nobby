"""Contract checks for non-search chat routing and safe empty-search fallback."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] /
          "frontend/assets/chat/generation.js").read_text(encoding="utf-8")


def test_explicit_no_web_bypasses_action_router():
    anchor = SOURCE.index("const bypassSearchRouter =")
    route = SOURCE.index("const actionResponse = await fetch('/api/mlx/chat/actions'", anchor)
    section = SOURCE[anchor:route]
    assert "noWebRequested" in section
    assert "resolvedTarget === 'chat'" in section
    assert "!imageFiles.length" in section
    assert "!documentFiles.length" in section
    assert "await generateAssistant(session);" in section
    assert "return;" in section


def test_contextual_followups_respect_live_search():
    assert "refersToEarlierExplanation && !liveInformationRequested" in SOURCE
    assert "const liveInformationRequested =" in SOURCE


def test_empty_web_search_can_fallback_but_not_live_facts():
    start = SOURCE.index("if (!results.length) {")
    end = SOURCE.index("const providerStatus = toolResult.data?.provider_status;", start)
    section = SOURCE[start:end]
    assert "currentSourceNeeded" in section
    assert "!forecast?.answer" in section
    assert "await generateAssistant(session);" in section
    assert "heute" in section and "wetter" in section


def test_model_request_path_not_modified():
    assert "const response = await fetch(\n            '/api/chat/stream'" in SOURCE
