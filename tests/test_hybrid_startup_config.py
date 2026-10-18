"""Exercise startup parsing without sourcing config or starting any service."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(value):
    text = (ROOT / 'scripts/mlx-server-start').read_text()
    function = text.split('adaptive_prefill_step_size() {', 1)[1].split(
        '\nmodel_reference_available()', 1)[0]
    script = 'adaptive_prefill_step_size() {' + function + '\nadaptive_prefill_step_size\n'
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                          env={**os.environ, 'MLX_PREFILL_STEP_SIZE': value}, timeout=2)


@pytest.mark.parametrize('value', ['128', '256', '1024', '4096'])
def test_valid_startup_step(value):
    result = invoke(value)
    assert result.returncode == 0
    assert result.stdout.strip() == value


@pytest.mark.parametrize('value', ['127', '4097', '9' * 100, '２５６', 'bad'])
def test_invalid_step_rejected_before_shell_arithmetic(value):
    result = invoke(value)
    assert result.returncode != 0
    assert result.stdout == ''
    assert 'integer expression expected' not in result.stderr
