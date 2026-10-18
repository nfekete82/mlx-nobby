import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location("nobby_prefill256_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_1024_cannot_store_naturally_while_256_can(monkeypatch):
    m = load(ROOT / "scripts/hybrid_checkpoint_policy.py")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT", "1")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE", "1")

    assert m.early_checkpoint(986, 324, 16, prefill_step_size=1024) is None
    assert m.early_checkpoint(986, 324, 16, prefill_step_size=256) == 580
    assert m.early_checkpoint(324, 0, 16, prefill_step_size=1024) is None
    assert m.early_checkpoint(324, 0, 16, prefill_step_size=256) is None


def test_prefill_override_is_bounded_and_default_off():
    m = load(ROOT / "scripts/benchmark-chat-cache-causal.py")
    assert m.PREFILL == "MLX_PREFILL_STEP_SIZE"
    assert m.valid_existing_prefill_setting("")
    assert m.valid_existing_prefill_setting("1024")
    assert m.valid_existing_prefill_setting("256")
    assert not m.valid_existing_prefill_setting("0")
    assert not m.valid_existing_prefill_setting("42")
    assert not m.valid_existing_prefill_setting("4097")
    assert not m.valid_existing_prefill_setting("nonsense")
    assert not m.valid_existing_prefill_setting("256; exit")
    assert not m.valid_existing_prefill_setting("２５６")
    assert not m.valid_existing_prefill_setting("0" * 50 + "256")


def test_same_prefill_setting_applies_before_every_restart():
    code = (ROOT / "scripts/benchmark-chat-cache-causal.py").read_text()
    assert "if args.prefill_step is not None:\n                set_launch(PREFILL, str(args.prefill_step))" in code
    assert "flag_names = (*flag_names, PREFILL)" in code
    assert "for name, value in initial.items():" in code
    assert '"prefill_step_override": args.prefill_step' in code


def test_launcher_really_accepts_override():
    code = (ROOT / "scripts/mlx-server-start").read_text()
    assert 'if [ -n "${MLX_PREFILL_STEP_SIZE:-}" ]; then' in code
    assert '"$MLX_PREFILL_STEP_SIZE" -lt 128' in code
    assert 'PREFILL_STEP_SIZE="$(adaptive_prefill_step_size)"' in code


def test_process_verification_requires_correct_hybrid_runtime_step():
    m = load(ROOT / "scripts/benchmark-chat-cache-causal.py")
    valid = (
        "python3 /repo/scripts/hybrid_apc_dflash_runtime.py mlx_vlm server "
        "--model x --port 8000 --prefill-step-size 256 --max-num-seqs 2"
    )
    with patch.object(m.subprocess, "run",
                      return_value=SimpleNamespace(stdout=valid, returncode=0)):
        assert m.verify_prefill_in_server_process(256) is None
        with pytest.raises(RuntimeError, match="did not advertise"):
            m.verify_prefill_in_server_process(1024)


def test_process_verification_rejects_unrelated_processes():
    m = load(ROOT / "scripts/benchmark-chat-cache-causal.py")
    unrelated = "python3 scripts/benchmark-chat-cache-causal.py --prefill-step 256"
    with patch.object(m.subprocess, "run",
                      return_value=SimpleNamespace(stdout=unrelated, returncode=0)):
        with pytest.raises(RuntimeError, match="did not advertise"):
            m.verify_prefill_in_server_process(256)
