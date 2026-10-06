from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ltx_setup_supports_parallel_q4_q8_on_0160():
    source = (ROOT / "scripts/setup-ltx-video-mlx").read_text(encoding="utf-8")

    assert 'UPSTREAM_VERSION="0.16.0"' in source
    assert 'UPSTREAM_COMMIT="90f76c20864ea612071afbb4e714ceea99e38e34"' in source
    assert 'LTX_MLX_MODEL_VARIANT' in source
    assert 'q4|q8' in source
    assert 'dgrauet/ltx-2.5-mlx-$MODEL_VARIANT' in source


def test_mflux_setup_is_pinned_and_validates_new_clis():
    source = (ROOT / "scripts/setup-mflux-mlx").read_text(encoding="utf-8")

    assert 'MFLUX_VERSION="${MFLUX_VERSION:-0.20.0}"' in source
    assert 'uv tool install --force "mflux==$MFLUX_VERSION"' in source
    assert "mflux-generate-qwen-2.1" in source
    assert "mflux-generate-krea2" in source
    assert "mflux-generate-boogu" in source
    assert "mflux-upscale-seedvr2" in source
