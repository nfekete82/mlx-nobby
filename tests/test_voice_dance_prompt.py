"""Test the production prompt builder without loading any MLX / Metal weights."""
import ast
from pathlib import Path


def _builder():
    source = Path("agent/talking_photo_ltx.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "speaker_prompt")
    sandbox = {
        "TALKING_PROMPT": "STABLE-PORTRAIT",
        "validate_focus": lambda coords: (coords["x"], coords["y"]),
    }
    module = ast.Module(body=[func], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "talking_photo_ltx.py", "exec"), sandbox)
    return sandbox["speaker_prompt"]


def test_dance_with_speech_preserves_person_and_voice():
    prompt = _builder()(None, "dance")
    assert "dances naturally" in prompt
    assert "synchronized to the voice" in prompt
    assert "face recognizable" in prompt
    assert "do not invent a different body" in prompt


def test_default_talking_photo_prompt_unchanged():
    assert _builder()(None) == "STABLE-PORTRAIT"


def test_two_person_dance_only_one_speaker():
    prompt = _builder()({"x": 0.75, "y": 0.5}, "dance")
    assert "right side is the ONLY speaker and dancer" in prompt
    assert "left side remains a silent listener" in prompt


def test_unknown_scene_motion_rejected():
    try:
        _builder()(None, "backflip")
    except ValueError:
        return
    raise AssertionError("Unsupported motion must not silently pass")
