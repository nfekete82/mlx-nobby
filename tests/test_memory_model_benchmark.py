"""The synthetic memory benchmark must score validated episodes as memories."""
from pathlib import Path
import runpy

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-memory-model-local.py"


def _grounded(structure, original):
    return runpy.run_path(str(SCRIPT), run_name="benchmark_fixture")[
        "grounded_episode_texts"
    ](structure, original)


def test_literal_work_episode_is_retrievable_memory():
    source = "2018 habe ich für sechs Monate in Berlin gearbeitet."
    item = {
        "theme": "work", "description": source,
        "evidence": source, "status": "statement", "title": "Arbeit in Berlin",
    }
    assert _grounded({"episodes": [item]}, source) == [source]


def test_hallucinated_episode_is_rejected():
    source = "Ich arbeite in Hamburg."
    item = {
        "theme": "work",
        "description": "2018 habe ich in Berlin gearbeitet.",
        "evidence": "2018 habe ich in Berlin gearbeitet.",
        "status": "statement",
    }
    assert _grounded({"episodes": [item]}, source) == []


def test_hypothetical_episode_is_rejected():
    source = "Wenn ich in Berlin arbeiten würde, wäre es schöner."
    item = {"theme": "work", "description": source, "evidence": source}
    assert _grounded({"episodes": [item]}, source) == []


def test_speaker_attribution_remains_an_explicit_manual_review_limit():
    source = 'Meine Kollegin sagte: "Ich wohne in Prag."'
    item = {"theme": "work", "description": "Ich wohne in Prag.",
            "evidence": "Ich wohne in Prag."}
    # Literal grounding alone does not verify speaker identity. Do not claim
    # the benchmark rules out all false-positive quoted-source episodes.
    assert _grounded({"episodes": [item]}, source) == ["Ich wohne in Prag."]
