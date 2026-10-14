"""Validate independent video/tracing switches in the E2E fixture source."""
from pathlib import Path


def test_e2e_diagnostic_flags_are_independent():
    src = (Path(__file__).parent / 'e2e' / 'conftest.py').read_text()
    assert "os.environ.get('MLX_E2E_VIDEO', '1')" in src
    assert "os.environ.get('MLX_E2E_TRACING', '1')" in src
    assert "if video_enabled:" in src
    assert "if tracing_enabled:" in src
    assert "context_options['record_video_dir'] = str(artifact)" in src
