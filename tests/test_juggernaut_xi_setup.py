from pathlib import Path

import image_registry


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup-juggernaut-xi"


def test_juggernaut_xi_registry_identity_and_defaults():
    model = next(
        item
        for item in image_registry.builtin_models()
        if item["id"] == image_registry.JUGGERNAUT_XL_ID
    )

    assert image_registry.JUGGERNAUT_XI_REPOSITORY == (
        "RunDiffusion/Juggernaut-XI-v11"
    )
    assert image_registry.JUGGERNAUT_XI_CHECKPOINT == (
        "Juggernaut-XI-byRunDiffusion.safetensors"
    )
    assert model["name"] == "Juggernaut XI v11"
    assert model["local_path"] == str(
        Path.home() / "Models" / "JuggernautXL"
    )
    assert model["default_steps"] == 30
    assert model["default_guidance"] == 5.0


def test_juggernaut_xi_setup_is_gated_safe_and_can_remove_krea():
    source = SETUP.read_text(encoding="utf-8")

    assert 'hf auth whoami' in source
    assert 'RunDiffusion/Juggernaut-XI-v11' in source
    assert 'Juggernaut-XI-byRunDiffusion.safetensors' in source
    assert '--remove-krea' in source
    assert 'models--krea--Krea-2-Turbo' in source
    assert 'models--gokaygokay--Krea-2-Realism-LoRA' in source

    stage = source.index('staged="$TARGET_DIR/.$CHECKPOINT.new"')
    delete_old = source.index(
        'find "$TARGET_DIR" -maxdepth 1 -type f -name \'*.safetensors\' -delete'
    )
    activate = source.index(
        '"$IMAGE_URL/models/juggernaut-xl/activate"'
    )

    assert stage < delete_old < activate


def test_old_ragnarok_doc_is_retired():
    assert (ROOT / "docs" / "JUGGERNAUT_XI.md").is_file()
    assert not (ROOT / "docs" / "JUGGERNAUT_RAGNAROK.md").exists()
