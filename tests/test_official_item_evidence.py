"""Official model rows require article-local matching evidence."""
from agent.official_item_evidence import filter_unsupported_official_items

GOAL = "Welche Modelle bietet Apple offiziell an?"


def article(text):
    return [{"action": "fetch_url", "status": "completed",
             "result": {"ok": True, "url": "https://www.apple.com/de/newsroom/test",
                        "text": text + " " * 90}}]


def test_unknown_model_removed_but_sourced_model_kept():
    answer = ("1. **iPhone Duo** – ab 23. Oktober 2026\n"
              "2. **iPhone 99 Pro** – ab 13. Oktober 2026")
    sources = article("Apple unveils iPhone Duo; erhältlich ab 23. Oktober 2026.")
    fixed = filter_unsupported_official_items(answer, GOAL, sources)
    assert "iPhone Duo" in fixed
    assert "iPhone 99" not in fixed


def test_unverified_date_removes_row():
    sources = article("Apple announces iPhone Duo in fall.")
    answer = "- **iPhone Duo** – erhältlich ab 23. Oktober 2026"
    fixed = filter_unsupported_official_items(answer, GOAL, sources)
    assert "erhältlich ab" not in fixed
    assert "keine unbestätigte" in fixed


def test_official_research_only():
    a = "- iPhone 99 Pro – völlig neu"
    assert filter_unsupported_official_items(a, "Schreibe eine Geschichte", article("Nothing")) == a


def test_without_loaded_articles_delegates_to_other_gate():
    a = "- iPhone 99 Pro – erhältlich"
    assert filter_unsupported_official_items(a, GOAL, []) == a


def test_multi_model_row_requires_each_model():
    answer = "- iPhone 16 Pro / iPhone 15 Pro / iPhone 14 Pro weiterhin verfügbar"
    sources = article("iPhone 16 Pro available now.")
    fixed = filter_unsupported_official_items(answer, GOAL, sources)
    assert "weiterhin verfügbar" not in fixed
