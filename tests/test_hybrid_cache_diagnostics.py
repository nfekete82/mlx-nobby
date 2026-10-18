from pathlib import Path
import importlib.util
import logging

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hybrid_cache_diagnostics", ROOT / "scripts/hybrid_cache_diagnostics.py"
)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def test_disabled_is_noop(monkeypatch):
    monkeypatch.delenv(diag.ENV, raising=False)
    diag._previous = None
    assert diag.classify([1, 2, 3], 9, matched_tokens=0,
                         minimum_tokens=1, guard_tokens=1, stored=True) is None
    assert diag._previous is None


def test_classifies_changes_without_content_logging(monkeypatch, caplog):
    monkeypatch.setenv(diag.ENV, "1")
    diag._previous = None
    with caplog.at_level(logging.INFO, logger="nobby.hybrid.apc"):
        diag.classify([42, 43, 44, 45], 7, matched_tokens=0,
                      minimum_tokens=2, guard_tokens=1, stored=True)
        assert diag.classify([42, 43, 44, 45, 46], 8, matched_tokens=0,
                             minimum_tokens=2, guard_tokens=1) == "semantic_hash_changed"
        assert diag.classify([90, 91, 92], 7, matched_tokens=0,
                             minimum_tokens=2, guard_tokens=1) == "token_prefix_changed"
        assert diag.classify([42, 43, 44, 45, 46], 7, matched_tokens=3,
                             minimum_tokens=2, guard_tokens=1) == "exact_hit"
    assert "HYBRID_APC_DIAG" in caplog.text
    assert "42," not in caplog.text


def test_patch_instruments_both_cache_operations():
    src = (ROOT / "scripts/hybrid_apc_dflash_runtime.py").read_text()
    assert src.count("nobby_hybrid_diag.classify(") == 2
    # A failed cache store must not be logged as a successful snapshot.
    assert "hybrid_final_saved = hybrid_apc_manager.store_exact_cache(" in src
    assert "stored=hybrid_final_saved," in src
    assert "stored=True" not in src
    assert 'vars(module)["nobby_hybrid_diag"]' in src
