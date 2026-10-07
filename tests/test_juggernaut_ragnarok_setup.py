from pathlib import Path

import image_registry


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup-juggernaut-ragnarok"
LEGACY_SETUP = ROOT / "scripts" / "setup-juggernaut-xi"


def test_juggernaut_ragnarok_registry_identity_and_defaults():
    model = next(
        item
        for item in image_registry.builtin_models()
        if item["id"] == image_registry.JUGGERNAUT_XL_ID
    )

    assert image_registry.JUGGERNAUT_RAGNAROK_NAME == (
        "Juggernaut XL Ragnarok"
    )
    assert image_registry.JUGGERNAUT_RAGNAROK_MODEL_VERSION == "1759168"
    assert image_registry.JUGGERNAUT_RAGNAROK_CHECKPOINT == (
        "juggernautXL_ragnarok.safetensors"
    )
    assert image_registry.JUGGERNAUT_RAGNAROK_SHA256 == (
        "dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a"
    )
    assert model["name"] == "Juggernaut XL Ragnarok"
    assert model["local_path"] == str(
        Path.home() / "Models" / "JuggernautXL"
    )
    assert model["default_steps"] == 30
    assert model["default_guidance"] == 5.0


def test_juggernaut_ragnarok_setup_verifies_download_before_replacement():
    source = SETUP.read_text(encoding="utf-8")

    assert 'MODEL_VERSION="1759168"' in source
    assert 'https://civitai.com/api/download/models/$MODEL_VERSION' in source
    assert (
        'MODEL_SHA256="dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a"'
        in source
    )
    assert 'shasum -a 256 "$downloaded"' in source
    assert '--remove-juggernaut-z' in source
    assert 'models--RunDiffusion--Juggernaut-Z-Image' in source

    verify = source.index('downloaded_hash="$(shasum -a 256 "$downloaded"')
    stage = source.index('staged="$TARGET_DIR/.$CHECKPOINT.new"')
    delete_old = source.index(
        'find "$TARGET_DIR" -maxdepth 1 -type f -name \'*.safetensors\' -delete'
    )
    activate = source.index(
        '"$IMAGE_URL/models/juggernaut-xl/activate"'
    )

    assert verify < stage < delete_old < activate


def test_legacy_xi_setup_redirects_to_ragnarok():
    source = LEGACY_SETUP.read_text(encoding="utf-8")

    assert "setup-juggernaut-ragnarok" in source
    assert 'exec bash "' in source


def test_ragnarok_doc_replaces_xi_doc():
    assert (ROOT / "docs" / "JUGGERNAUT_RAGNAROK.md").is_file()
    assert not (ROOT / "docs" / "JUGGERNAUT_XI.md").exists()
