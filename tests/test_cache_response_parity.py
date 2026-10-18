import importlib.util
import json
import os
from pathlib import Path


def load_script(filename):
    path = Path(__file__).resolve().parents[1] / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_raw_capture_is_user_private(tmp_path):
    m = load_script("benchmark-chat-cache.py")
    path = tmp_path / "answers.json"
    m.secure_write_json(str(path), '{"answers": []}\n')
    assert json.loads(path.read_text()) == {"answers": []}
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    m.secure_write_json(str(path), '{"answers": [1]}\n')
    assert path.stat().st_mode & 0o777 == 0o600


def test_answer_parity_flags_unexpected_first_turn_difference(tmp_path):
    m = load_script("benchmark-chat-cache-ab.py")
    def write(mode, a1, a2="same", a3="same"):
        path = tmp_path / f"{mode}.json"
        path.write_text(json.dumps({"answers": [
            {"turn": i, "question": f"q{i}", "answer": answer}
            for i, answer in enumerate([a1, a2, a3], 1)]}))
        return {"mode": mode, "answers_file": str(path)}
    result = m.compare_captured_answers([write("off", "long answer"), write("on", "short")])
    assert len(result) == 1
    assert result[0]["turns"][0]["exact_equal"] is False
    assert result[0]["turns"][0]["off_chars"] == len("long answer")
    assert result[0]["turns"][1]["exact_equal"] is True


def test_answer_parity_rejects_mismatched_questions(tmp_path):
    m = load_script("benchmark-chat-cache-ab.py")
    data = []
    for mode, question in (("off", "first"), ("on", "changed")):
        path = tmp_path / f"{mode}.json"
        path.write_text(json.dumps({"answers": [
            {"turn": i, "question": question if i == 1 else f"q{i}", "answer": "ok"}
            for i in range(1, 4)]}))
        data.append({"mode": mode, "answers_file": str(path)})
    try:
        m.compare_captured_answers(data)
    except ValueError as exc:
        assert "Question or turn changed" in str(exc)
    else:
        raise AssertionError("mismatched benchmark inputs must fail")
