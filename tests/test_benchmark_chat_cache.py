import importlib.util
from pathlib import Path
import io
import json
from unittest.mock import patch


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark-chat-cache.py"
    spec = importlib.util.spec_from_file_location("cache_bench", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_delta_and_questions():
    m = module()
    assert len(m.QUESTIONS) == 3
    assert m.delta({"exact_hits": 1}, {"exact_hits": 3}) == {"exact_hits": 2}


def test_multiline_sse_parsing():
    m = module()
    b = io.BytesIO(b'event: content\ndata: {"type":"content",\ndata: "text":"x"}\n\nevent: done\ndata: {}\n\n')
    items = list(m.iter_sse(b))
    assert items[0][0] == "content"
    assert json.loads(items[0][1]) == {"type": "content", "text": "x"}
    assert items[1][0] == "done"


def test_run_maintains_history_and_measures_per_turn():
    m = module()
    seen = []
    stats = iter([
        {"exact_hits": 5, "matched_tokens": 100, "exact_stores": 9},
        {"exact_hits": 5, "matched_tokens": 100, "exact_stores": 10},
        {"exact_hits": 6, "matched_tokens": 410, "exact_stores": 11},
        {"exact_hits": 7, "matched_tokens": 800, "exact_stores": 12},
    ])
    def fake_stream(url, payload, timeout):
        seen.append([x.copy() for x in payload["messages"]])
        return "Answer", 10, 20
    from argparse import Namespace
    args = Namespace(web_url="http://127.0.0.1:8090",
                     server_url="http://127.0.0.1:8000",
                     system_prompt="base", chart_suffix=False,
                     temperature=0.3, max_tokens=700,
                     timeout=2, json_out=None)
    with patch.object(m, "cache_stats", side_effect=lambda url: next(stats)), \
         patch.object(m, "stream_answer", side_effect=fake_stream):
        assert m.run(args) == 0
    assert [len(x) for x in seen] == [1, 3, 5]
    assert seen[1][1] == {"role": "assistant", "content": "Answer"}


def test_replay_requires_same_questions(tmp_path):
    m = module()
    data = {"answers": [
        {"turn": i, "question": question, "answer": "Reference " + str(i)}
        for i, question in enumerate(m.QUESTIONS, 1)
    ]}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert m.load_replay_answers(str(path)) == ("Reference 1", "Reference 2", "Reference 3")
    data["answers"][1]["question"] = "Other question"
    path.write_text(json.dumps(data), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="Replay turn 2"):
        m.load_replay_answers(str(path))


def test_replay_keeps_baseline_history_not_fresh_answers(tmp_path):
    m = module()
    reference = {"answers": [
        {"turn": i, "question": question, "answer": f"Fixed answer {i}"}
        for i, question in enumerate(m.QUESTIONS, 1)
    ]}
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
    from argparse import Namespace
    args = Namespace(web_url="http://127.0.0.1:8090",
                     server_url="http://127.0.0.1:8000",
                     system_prompt="base", chart_suffix=False,
                     temperature=0, max_tokens=700, timeout=2,
                     json_out=None, answers_out=None, replay_answers=str(path),
                     diagnose=False)
    stats = iter([
        {"exact_hits": 0, "matched_tokens": 0, "exact_stores": 0},
        {"exact_hits": 0, "matched_tokens": 0, "exact_stores": 1},
        {"exact_hits": 1, "matched_tokens": 324, "exact_stores": 2},
        {"exact_hits": 1, "matched_tokens": 324, "exact_stores": 3},
    ])
    sent = []
    def generate(url, payload, timeout):
        sent.append([entry.copy() for entry in payload["messages"]])
        return "Fresh generation", 10, 20
    with patch.object(m, "cache_stats", side_effect=lambda url: next(stats)), \
         patch.object(m, "stream_answer", side_effect=generate):
        assert m.run(args) == 0
    assert sent[1][1]["content"] == "Fixed answer 1"
    assert sent[2][3]["content"] == "Fixed answer 2"
    assert sent[2][1]["content"] != "Fresh generation"
