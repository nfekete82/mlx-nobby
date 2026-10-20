"""CPU-only regression tests for cached HF LM/VLM backend selection."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "runtime-model-backend.py"
SPEC = importlib.util.spec_from_file_location("runtime_model_backend", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def write_config(path: Path, architecture: str, model_type: str = "qwen3_5"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"architectures": [architecture],
                                "model_type": model_type}), encoding="utf-8")


def test_cached_hf_qwen_vlm_is_not_misclassified_as_lm(tmp_path):
    hub = tmp_path / "hf" / "hub"
    commit = "3" * 40
    base = hub / "models--jancirnodziewiaty--Dark-Scarlett-27B-v2.0-oQ4e-mtp"
    (base / "refs").mkdir(parents=True)
    (base / "refs" / "main").write_text(commit + "\n")
    path = base / "snapshots" / commit / "config.json"
    write_config(path, "Qwen3_5ForConditionalGeneration")
    env = {"HF_HUB_CACHE": str(hub)}
    assert mod.cached_config("jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp", env) == path
    assert mod.detect("jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp", env) == "vlm"
    assert mod.detect(str(path.parent), env) == "vlm"
    done = subprocess.run([sys.executable, str(SCRIPT),
                           "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp"],
                          env={"HF_HUB_CACHE": str(hub)}, capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.strip() == "vlm"


def test_local_lm_and_uncached_ids_keep_existing_classification(tmp_path):
    local = tmp_path / "local-lm"
    write_config(local / "config.json", "LlamaForCausalLM", "llama")
    assert mod.detect(str(local)) == "lm"
    assert mod.detect("org/not-yet-cached", {"HF_HUB_CACHE": str(tmp_path)}) == "lm"
    assert mod.detect("mlx-community/typical-text-model", {"HF_HUB_CACHE": str(tmp_path)}) == "lm"


def test_cached_standard_lm_is_lm_and_hf_home_fallback(tmp_path):
    hub = tmp_path / "alt-hf" / "hub"
    commit = "b" * 40
    path = hub / "models--example--llm" / "snapshots" / commit / "config.json"
    write_config(path, "LlamaForCausalLM", "llama")
    assert mod.detect("example/llm", {"HF_HOME": str(tmp_path / "alt-hf")}) == "lm"


def test_ambiguous_or_invalid_hf_cache_does_not_load_untrusted_guess(tmp_path):
    hub = tmp_path / "hub"
    snapshots = hub / "models--owner--model" / "snapshots"
    for c in ("a" * 40, "b" * 40):
        write_config(snapshots / c / "config.json", "Qwen3_5ForConditionalGeneration")
    assert mod.detect("owner/model", {"HF_HUB_CACHE": str(hub)}) == "lm"  # no main ref
    (snapshots.parent / "refs").mkdir()
    (snapshots.parent / "refs" / "main").write_text("../" + "a" * 40)
    assert mod.detect("owner/model", {"HF_HUB_CACHE": str(hub)}) == "lm"
    (snapshots.parent / "refs" / "main").write_text("b" * 40)
    assert mod.detect("owner/model", {"HF_HUB_CACHE": str(hub)}) == "vlm"
    assert mod.cached_config("../../bad/path", {"HF_HUB_CACHE": str(hub)}) is None


def test_corrupt_cached_config_fails_closed(tmp_path):
    hub = tmp_path / "hub"
    commit = "a" * 40
    path = hub / "models--owner--broken" / "snapshots" / commit / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    with pytest.raises(ValueError):
        mod.detect("owner/broken", {"HF_HUB_CACHE": str(hub)})
    result = subprocess.run([sys.executable, str(SCRIPT), "owner/broken"],
                            env={"HF_HUB_CACHE": str(hub)}, capture_output=True, text=True)
    assert result.returncode == 1
    assert "refusing" in result.stderr
    assert result.stdout == ""


def test_launch_script_uses_helper_without_changing_memory_or_model_settings():
    launcher = (ROOT / "scripts" / "mlx-server-start").read_text(encoding="utf-8")
    assert '"$PYTHON" "$PROJECT_DIR/scripts/runtime-model-backend.py" "$1"' in launcher
    assert 'BACKEND="$(detect_backend "$MODEL")" || exit 1' in launcher
    assert '--model "$MODEL"' in launcher
    assert '"$PROJECT_DIR/scripts/runtime-model-guard.py"' in launcher
    assert 'case "$CHAT_PERFORMANCE_PROFILE" in' in launcher
