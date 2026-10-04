from pathlib import Path


def _script_text():
    root = Path(__file__).resolve().parents[1]
    return (root / "scripts" / "setup-musetalk-mac").read_text(encoding="utf-8")


def test_musetalk_setup_uses_pinned_virtualenv_for_weight_download():
    script = _script_text()

    assert 'PATH="$INSTALL_DIR/.venv/bin:$PATH" ./download_weights_mac.sh' in script


def test_musetalk_setup_restores_missing_model_source_from_pinned_official_revision():
    script = _script_text()

    assert 'OFFICIAL_SOURCE_REVISION="${MUSETALK_SOURCE_REVISION:-db204311a54a332843fea9b336e7649ad2322596}"' in script
    assert 'MODELS_SOURCE_DIR="$INSTALL_DIR/upstream/musetalk/models"' in script
    assert 'for source_file in vae.py unet.py; do' in script
    assert '"$OFFICIAL_MODELS_BASE/$source_file"' in script
    assert 'weights_only=False' in script


def test_musetalk_setup_preflights_imports_before_launching_service():
    script = _script_text()

    import_check = 'from musetalk.models.vae import VAE'
    launch = 'launchctl bootstrap "$DOMAIN" "$PLIST"'
    assert import_check in script
    assert launch in script
    assert script.index(import_check) < script.index(launch)
