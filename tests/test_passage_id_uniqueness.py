"""A short dated article must never create duplicate evidence passage IDs."""
import pytest

from agent.structured_evidence import build_evidence
from agent.semantic_evidence import _anchored_passages


@pytest.mark.parametrize("goal, text", [
    (
        "What is the current deposit rate and when did it take effect?",
        "At its 10 September 2026 meeting, the council decided to raise the "
        "deposit facility rate to 2.50%. The new rate takes effect from "
        "16 September 2026. The announcement was published on 10 September 2026.",
    ),
    (
        "When are sales starting?",
        "Nova Board sales begin in France on 2026-09-01. "
        "In Belgium sales begin on 2026-12-01. "
        "The release article describes regional sales dates for Nova Board.",
    ),
])
def test_exact_temporal_window_matches_complete_paragraph_only_once(goal, text):
    observations = [{
        "action": "fetch_url", "status": "completed",
        "query": "https://example.org/articles/history",
        "result": {
            "ok": True,
            "url": "https://example.org/articles/history",
            "text": text,
        },
    }]
    bundle = build_evidence(observations, goal=goal)
    assert bundle.facts
    ids = [fact.id for fact in bundle.facts]
    assert len(ids) == len(set(ids))
    passages = _anchored_passages(bundle)
    assert len(passages) == len(bundle.facts)
    assert any(f.evidence_excerpt == text for f in passages.values())


def test_different_source_spans_are_not_collapsed():
    text = (
        "June 1, 2026: The research team presented its preliminary findings.\n"
        "July 20, 2026: The spacecraft landed on the Moon as confirmed by mission control.\n"
    )
    bundle = build_evidence([{
        "action": "fetch_url", "status": "completed",
        "result": {"ok": True, "url": "https://example.org/mission/report",
                   "text": text},
    }], goal="When did the spacecraft land on the Moon?")
    assert len(bundle.facts) >= 2
    assert len({f.id for f in bundle.facts}) == len(bundle.facts)
