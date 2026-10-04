from pathlib import Path


def test_musetalk_setup_uses_pinned_virtualenv_for_weight_download():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "setup-musetalk-mac").read_text(encoding="utf-8")

    assert 'PATH="$INSTALL_DIR/.venv/bin:$PATH" ./download_weights_mac.sh' in script
