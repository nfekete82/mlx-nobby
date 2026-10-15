"""Unit regression for bounded Qwen rewrites of verified daily news previews."""
import json
from unittest.mock import Mock

from agent.news_briefing import enhance_grounded_news, rewrite_is_supported


HEADLINE = "Sorge vor Spionage: Slowakei erneuert Militärkontakte mit Russland"
EXCERPT = (
    "Die Slowakei hat neue Militärkontakte mit Russland angekündigt, nachdem "
    "beide Seiten mehrere Monate lang Gespräche vorbereitet hatten."
)
REWRITE = (
    "Die Slowakei nimmt ihre Militärkontakte mit Russland wieder auf. "
    "Beide Seiten hatten dazu über mehrere Monate Gespräche geführt."
)


def digest():
    return {
        "status": "available",
        "items": [{"title": HEADLINE, "summary": EXCERPT,
                   "publisher": "tagesschau", "url": "https://www.tagesschau.de/"}],
        "answer": (
            "**Nachrichtenüberblick vom 15.10.2026**\n\n"
            "- **[Titel](https://www.tagesschau.de/)** — tagesschau · 09:24 Uhr  \n"
            "  " + EXCERPT + "\n\n"
            "*Kurzüberblicke sind wörtliche, gekürzte Auszüge aus lesbaren "
            "Artikeln – keine unabhängige Faktenprüfung.*"
        )
    }


def test_single_bounded_model_call_rewrites_verified_excerpt():
    llm = Mock(return_value=json.dumps({
        "summaries": [{"id": 0, "text": REWRITE}]
    }))
    result = enhance_grounded_news(digest(), llm, enabled=True)
    assert result["items"][0]["summary"] == REWRITE
    assert result["items"][0]["summary_method"] == "local_ai_rewrite"
    assert result["ai_rewritten_count"] == 1
    assert REWRITE in result["answer"]
    assert "wörtliche, gekürzte" not in result["answer"]
    assert "https://www.tagesschau.de/" in result["answer"]
    llm.assert_called_once()
    args, kwargs = llm.call_args
    assert kwargs == {"max_tokens": 850, "temperature": 0.0}
    assert args[0][1]["role"] == "user"
    assert HEADLINE in args[0][1]["content"]
    assert EXCERPT in args[0][1]["content"]


def test_invented_year_and_source_unrelated_story_are_rejected():
    fabricated = (
        "Die Slowakei nimmt 2027 neue Militärkontakte mit Russland auf. "
        "Beide Seiten hatten dazu lange Gespräche geführt."
    )
    assert not rewrite_is_supported(fabricated, EXCERPT, HEADLINE)
    ungrounded = (
        "Die Vereinigten Staaten kündigen eine internationale Konferenz an, "
        "um die Handelsbeziehungen mit Australien gemeinsam zu fördern."
    )
    assert not rewrite_is_supported(ungrounded, EXCERPT, HEADLINE)
    llm = Mock(return_value=json.dumps({
        "summaries": [{"id": 0, "text": fabricated}]
    }))
    result = enhance_grounded_news(digest(), llm, enabled=True)
    assert result["items"][0]["summary"] == EXCERPT
    assert result.get("ai_rewritten_count") is None


def test_model_failure_malformed_json_and_disabled_option_fall_back():
    bad = Mock(return_value="{not valid json")
    unchanged = enhance_grounded_news(digest(), bad, enabled=True)
    assert unchanged["items"][0]["summary"] == EXCERPT

    offline = Mock(side_effect=OSError("model not reachable"))
    unchanged = enhance_grounded_news(digest(), offline, enabled=True)
    assert unchanged["items"][0]["summary"] == EXCERPT

    disabled = Mock(side_effect=AssertionError("must not call Qwen"))
    unchanged = enhance_grounded_news(digest(), disabled, enabled=False)
    assert unchanged["items"][0]["summary"] == EXCERPT


def test_does_not_call_model_for_unverified_or_missing_excerpts():
    llm = Mock(side_effect=AssertionError("must not call Qwen"))
    empty = enhance_grounded_news({"status": "no_readable_articles", "items": []},
                                  llm, enabled=True)
    assert empty["items"] == []
    item = digest()
    item["items"][0]["summary"] = ""
    unchanged = enhance_grounded_news(item, llm, enabled=True)
    assert unchanged["items"][0]["summary"] == ""


def test_rewrite_many_items_uses_one_call_and_index_restriction():
    batch = digest()
    batch["items"] = batch["items"] * 8
    llm = Mock(return_value=json.dumps({"summaries": [
        {"id": 100, "text": REWRITE},
        {"id": 0, "text": REWRITE},
    ]}))
    enhanced = enhance_grounded_news(batch, llm, enabled=True)
    assert enhanced["ai_rewritten_count"] == 1
    assert enhanced["items"][0]["summary"] == REWRITE
    assert enhanced["items"][6]["summary"] == EXCERPT
    llm.assert_called_once()
