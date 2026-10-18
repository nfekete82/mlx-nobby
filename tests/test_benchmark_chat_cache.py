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
