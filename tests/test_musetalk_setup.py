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


def test_musetalk_setup_creates_optional_demo_media_directory():
    script = _script_text()

    mkdir = 'mkdir -p "$DEMO_MEDIA_DIR"'
    launch = 'launchctl bootstrap "$DOMAIN" "$PLIST"'
    assert 'DEMO_MEDIA_DIR="$INSTALL_DIR/upstream/data/demo_five"' in script
    assert mkdir in script
    assert launch in script
    assert script.index(mkdir) < script.index(launch)


def test_musetalk_setup_preflights_imports_before_launching_service():
    script = _script_text()

    source_import_check = 'from musetalk.models.vae import VAE'
    server_import_check = 'import server'
    launch = 'launchctl bootstrap "$DOMAIN" "$PLIST"'
    assert source_import_check in script
    assert server_import_check in script
    assert launch in script
    assert script.index(source_import_check) < script.index(server_import_check)
    assert script.index(server_import_check) < script.index(launch)


def test_musetalk_setup_fully_unloads_stale_launch_agent_before_bootstrap():
    script = _script_text()

    assert 'launchctl bootout "$DOMAIN/$LABEL"' in script
    assert 'launchctl bootout "$DOMAIN" "$PLIST"' in script
    assert 'for _wait in $(seq 1 20); do' in script
    assert 'launchctl print "$DOMAIN/$LABEL"' in script


def test_musetalk_setup_retries_launchctl_bootstrap_and_has_direct_fallback():
    script = _script_text()

    assert 'for _bootstrap_attempt in 1 2 3; do' in script
    assert 'launchctl bootstrap "$DOMAIN" "$PLIST"' in script
    assert 'start_fallback_process' in script
    assert 'nohup env' in script
    assert 'echo $! > "$PID_FILE"' in script
    assert 'MuseTalk is running in fallback background mode' in script


def test_musetalk_setup_keeps_health_check_after_launch_recovery():
    script = _script_text()

    fallback = 'start_fallback_process'
    health = '"http://127.0.0.1:${PORT}/health"'
    assert fallback in script
    assert health in script
    assert script.index(fallback) < script.rindex(health)
