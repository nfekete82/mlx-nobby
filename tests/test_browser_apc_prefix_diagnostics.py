"""Contract checks for opt-in browser APC diagnostics."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = (ROOT / "frontend/assets/chat/generation.js").read_text(encoding="utf-8")
DIAG = (ROOT / "frontend/assets/chat/apc-prefix-diagnostic.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend/chat.html").read_text(encoding="utf-8")


def test_diagnostic_loaded_before_generator():
    assert HTML.index("apc-prefix-diagnostic.js") < HTML.index("/assets/chat/generation.js")


def test_payload_unchanged_and_instrumented():
    assert "window.MLXHybridPrefixDiagnostics?.record?." in GEN
    assert "system_prompt:\n                        apcSystemPrompt" in GEN
    assert "context_sources:\n                        apcContextSources" in GEN
    assert "'\\nWhen the user asks" in GEN


def test_opt_in_and_no_serialized_prompt_or_hash():
    assert "sessionStorage?.getItem('mlx-apc-prefix-diagnostic') === '1'" in DIAG
    assert "if (!enabled()) { previous = null; return null; }" in DIAG
    assert "commonPrefix(" in DIAG
    assert "root.console?.info?.('[MLX APC prefix diagnostic]', data)" in DIAG
    assert "localStorage.setItem" not in DIAG
    assert "crypto.subtle" not in DIAG
