from pathlib import Path
from tests.test_benchmark_chat_cache import module


def test_read_only_new_diagnostic_lines(tmp_path):
    m = module()
    log = tmp_path / "server-error.log"
    log.write_text("old HYBRID_APC_DIAG reason=old stored=False\n")
    offset = log.stat().st_size
    with log.open("a") as stream:
        stream.write("HYBRID_APC_DIAG reason=exact_hit matched_tokens=324 stored=False\n")
        stream.write("HYBRID_APC_DIAG reason=exact_hit matched_tokens=324 stored=True\n")
    next_offset, lines = m.read_diagnostic_lines(str(log), offset)
    assert next_offset == log.stat().st_size
    assert len(lines) == 2
    assert "reason=exact_hit" in m.summarize_diagnostics(lines)
    assert "stored=False" in m.summarize_diagnostics(lines)
    assert m.read_diagnostic_lines(str(log), next_offset)[1] == []


def test_no_diagnostic_message_reports_unknown():
    m = module()
    assert m.summarize_diagnostics([]) is None
    assert m.summarize_diagnostics(["unrelated"]) is None
