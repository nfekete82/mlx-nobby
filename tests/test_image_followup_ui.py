from pathlib import Path

from backend.image_followup_ui import patch_generation_source


ROOT = Path(__file__).resolve().parents[1]


def _fixture_source() -> bytes:
    return (
        "const refersToExistingImage = imageComparisonRequest || "
        "/\\b(?:das|dieses|diesem|dieser|bild|foto|abbildung|es|davon|darauf)\\b|"
        "\\bist\\s+das\\b|\\bsieht\\s+(?:das|es)\\b/i.test(prompt);\n"
        "const userMessage = {\n"
        "        content: messageContent,\n"
        "        display_content: effectivePrompt,\n"
        "};"
    ).encode("utf-8")


def test_active_image_followup_detector_learns_portrait_vocabulary():
    patched = patch_generation_source(_fixture_source()).decode("utf-8")

    assert "porträtfotografie" in patched
    assert "portrait" in patched
    assert "fotografie" in patched
    assert "photography" in patched
    assert "aufnahme" in patched


def test_attached_active_image_gets_model_only_reference_hint():
    patched = patch_generation_source(_fixture_source()).decode("utf-8")

    assert "visionImages.length && refersToExistingImage" in patched
    assert "Refer to and analyze that image directly" in patched
    assert "display_content: effectivePrompt" in patched


def test_current_generation_module_is_actually_patchable():
    source = (ROOT / "frontend/assets/chat/generation.js").read_bytes()
    patched = patch_generation_source(source)

    assert patched != source
    decoded = patched.decode("utf-8")
    assert "porträtfotografie" in decoded
    assert "visionImages.length && refersToExistingImage" in decoded
    assert "Refer to and analyze that image directly" in decoded


def test_generation_source_patch_is_idempotent():
    once = patch_generation_source(_fixture_source())
    twice = patch_generation_source(once)

    assert twice == once


def test_unrelated_javascript_is_left_untouched():
    source = b"console.log('hello');"

    assert patch_generation_source(source) == source
