from backend import prompt_stage_diagnostics as diag


def test_off_by_default(monkeypatch, caplog):
    monkeypatch.delenv("MLX_PROMPT_STAGE_DIAG", raising=False)
    diag._LAST.clear()
    diag.compare("example", [{"role": "system", "content": "private"}])
    assert not diag._LAST
    assert "PROMPT_STAGE_DIAG" not in caplog.text


def test_metadata_only(monkeypatch, caplog):
    monkeypatch.setenv("MLX_PROMPT_STAGE_DIAG", "1")
    diag._LAST.clear()
    with caplog.at_level("WARNING", logger="nobby.prompt_stages"):
        diag.compare("example", [{"role": "system", "content": "SECRET_CONTEXT_A"}])
        diag.compare("example", [{"role": "system", "content": "SECRET_CONTEXT_B"}])
    assert "common_prefix_chars=15" in caplog.text
    assert "system_unchanged=False" in caplog.text
    assert "SECRET_CONTEXT" not in caplog.text


def test_web_route_has_all_checkpoints():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "backend/app.py").read_text()
    for stage in ("base_system", "with_profile", "with_rag",
                  "with_live_context", "final"):
        assert f'prompt_stage_compare("{stage}"' in source
