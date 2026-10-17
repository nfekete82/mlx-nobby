"""CPU-only contract tests for the opt-in *in-memory* MLX-VLM hybrid prototype.

No MLX/GPU imports or live models. This suite verifies the pinned patch
anchors, refusal of unsupported sources, CLI modes, and unchanged defaults.
Apple Silicon integration/quality tests must be done separately.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hybrid = load("nobby_hybrid_adapter", "hybrid_apc_dflash_runtime.py")
profiles = load("nobby_hybrid_profiles", "chat-performance-profile.py")


# Minimal v0.6.17-shaped method (indentation is intentional; inspect.getsource
# returns methods with their class-level indentation).
SPECULATIVE_FIXTURE = """
    def _run_speculative(self):
        for pending in []:
                prompt_started = time.perf_counter()
                out, input_mx = _run_chunked_speculative_prefill(
                    lm, input_mx, inputs_embeds_mx, prompt_cache,
                    prompt_kwargs, prefill_kwargs,
                    prefill_step_size=prefill_step_size,
                    generation_stream=generation_stream,
                )
                for uid in []:
                    prompt_tokens = prompt_tokens_map[uid]
                    prompt_tps_map[uid] = (
                        prompt_tokens / prompt_elapsed
                        if prompt_tokens > 0 and prompt_elapsed > 0
                        else None
                    )
                    logger.info(
                        "Prefill completed: request=%s prompt_tokens=%d "
                        "cached_tokens=0 elapsed=%.3fs rate=%.1f tok/s",
                        stream_infos[uid].get("request_id", uid),
                        prompt_tokens,
                        prompt_elapsed,
                        float(prompt_tps_map[uid] or 0.0),
                    )
                run_speculative_server_rounds(
                    self.model,
                )
"""


def test_compiles_in_memory_and_keeps_decoding_path():
    patched = hybrid.transform_speculative_method(SPECULATIVE_FIXTURE)
    assert hybrid.MARKER in patched
    assert patched.lstrip().startswith("def _run_speculative(self):")
    assert "run_speculative_server_rounds(" in patched
    assert "hybrid_apc_manager.lookup_exact_cache(" in patched
    assert "hybrid_apc_manager.store_exact_cache(" in patched
    assert "remaining_to_checkpoint" in patched
    assert "B == 1" in patched
    assert 'draft_kind == "dflash"' in patched
    assert 'self.apc_mode == "exact"' in patched
    assert "and not pending[0].images" in patched
    assert "and not pending[0].audio" in patched
    assert "and not pending[0].videos" in patched
    assert "hybrid_matched_tokens" in patched
    compile(patched, "<nobby-hybrid-test>", "exec")


def test_refuses_nonmatching_or_already_patched_sources():
    for source in (
        "    def _run_speculative(self):\n        return 3\n",
        SPECULATIVE_FIXTURE.replace("cached_tokens=0", "cached_tokens=%d"),
        SPECULATIVE_FIXTURE.replace("prompt_started = time.perf_counter()", "prompt_started=time.perf_counter()"),
    ):
        with pytest.raises(RuntimeError, match="differs"):
            hybrid.transform_speculative_method(source)
    patched = hybrid.transform_speculative_method(SPECULATIVE_FIXTURE)
    with pytest.raises(RuntimeError, match="already installed"):
        hybrid.transform_speculative_method(patched)


def test_profile_config_unchanged_unless_hybrid_explicit():
    original = 'MODEL="/Users/example/Models/Qwen3.8"\nSPECULATIVE_DRAFT_KIND="dflash"\n'
    assert profiles.configured_profile(original) == "default"
    assert profiles.updated_config(original, "default") == original
    combined = profiles.updated_config(original, "hybrid")
    assert profiles.configured_profile(combined) == "hybrid"
    assert combined.count(profiles.KEY) == 1
    assert profiles.updated_config(combined, "default") == original


def test_launcher_contains_single_server_no_venv_patch():
    script = (ROOT / "scripts" / "mlx-server-start").read_text()
    assert 'export NOBBY_EXPERIMENTAL_HYBRID=1' in script
    assert '"$PROJECT_DIR/scripts/hybrid_apc_dflash_runtime.py" --check-only' in script
    assert 'exec "$PYTHON" "$PROJECT_DIR/scripts/hybrid_apc_dflash_runtime.py"' in script
    assert "mlx_vlm server" in script
    assert 'export APC_DISK_PATH=""' in script
    assert "runtime-model-guard.py" in script
    assert "pip install" not in script
    assert "site-packages" not in script
    for file in ("mlx-server-start", "mlx"):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "scripts" / file)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_switch_mode_validates_live_hybrid_adapter(monkeypatch):
    monkeypatch.setattr(profiles, "json_get", lambda _: {
        "status": "healthy", "loaded_model": "test", "apc_enabled": True
    })
    monkeypatch.setattr(
        profiles, "current_server_args",
        lambda: (
            "python scripts/hybrid_apc_dflash_runtime.py mlx_vlm server "
            "--port 8000 --draft-model draft --draft-kind dflash"
        ),
    )
    profiles.confirm_profile("hybrid")
    monkeypatch.setattr(
        profiles, "current_server_args", lambda: (
            "python -m mlx_vlm server --port 8000 --draft-model draft --draft-kind dflash"
        )
    )
    with pytest.raises(RuntimeError, match="hybrid adapter"):
        profiles.confirm_profile("hybrid")
    with pytest.raises(RuntimeError, match="APC still enabled"):
        profiles.confirm_profile("dflash")


def test_hybrid_only_added_when_explicitly_requested(monkeypatch):
    # Stubs avoid runtime/model queries but exercise the actual compare loop.
    original_cfg = 'MODEL="test"\n'
    values = {"config": original_cfg}
    monkeypatch.setattr(profiles, "CONFIG", SimpleNamespace(
        read_text=lambda **kw: values["config"],
    ))
    monkeypatch.setattr(profiles, "ensure_idle", lambda: None)
    monkeypatch.setattr(profiles, "preflight", lambda mode: None)
    order = []
    def fake_switch(mode):
        order.append(mode)
        values["config"] = profiles.updated_config(values["config"], mode)
    monkeypatch.setattr(profiles, "switch_profile", fake_switch)
    monkeypatch.setattr(profiles, "cache_snapshot", lambda: {"enabled": True})
    monkeypatch.setattr(profiles, "memory_snapshot", lambda: {"free_percent": 40})
    fake_report = {
        "short": {
            "first_content_ms": {"p50": 120},
            "total_ms": {"p50": 9000},
            "samples": [{"output_characters": 1600}],
        },
        "contexts": [],
    }
    monkeypatch.setattr(
        profiles, "load_benchmark",
        lambda: SimpleNamespace(run=lambda *a, **kw: fake_report),
    )
    args = SimpleNamespace(
        context_sizes=[4000], samples=1, max_tokens=384, timeout=300,
        include_hybrid=True,
    )
    report = profiles.compare(args)
    assert order == ["dflash", "apc", "hybrid", "default"]
    assert set(report["results"]) == {"dflash", "apc", "hybrid"}
    assert report["starting_profile_restored"] == "default"
    assert report["experimental_hybrid_included"] is True
    assert profiles.configured_profile(values["config"]) == "default"


def test_mlx_memory_finds_vlm_hybrid_and_legacy_server_processes():
    """The MLX RAM view must not claim a live mlx_vlm server is stopped."""
    source = (ROOT / "scripts" / "mlx").read_text()
    anchor = 'pgrep -f "'
    line = next(line.strip() for line in source.splitlines()
                if line.strip().startswith(anchor) and "mlx_vlm" in line)
    expression = line.split(anchor, 1)[1].split('"', 1)[0].replace("$PORT", "8000")
    true_examples = (
        "python3 -m mlx_vlm server --model local --port 8000 --max-num-seqs 2",
        "python3 scripts/hybrid_apc_dflash_runtime.py mlx_vlm server --model local --port 8000 --draft-kind dflash",
        "python3 -m mlx_lm.server --model local --port 8000",
    )
    false_examples = (
        "python3 -m mlx_vlm server --model local --port 8001",
        "python3 -m mlx_lm.server --model local --port 18000",
        "python3 -m mlx_vlm server --model local --port 80001",
    )
    for command in true_examples:
        probe = subprocess.run(["grep", "-E", expression], input=command,
                               capture_output=True, text=True)
        assert probe.returncode == 0, (expression, command, probe.stderr)
    for command in false_examples:
        probe = subprocess.run(["grep", "-E", expression], input=command,
                               capture_output=True, text=True)
        assert probe.returncode == 1, (expression, command, probe.stderr)
