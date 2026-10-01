from agent.image_prompt_quality_runtime import (
    enhance_juggernaut_payload,
    repair_translation_semantics,
)


def test_female_police_officer_is_preserved():
    repaired = repair_translation_semantics(
        "Erstelle ein fotorealistisches Porträt einer Polizistin.",
        "Create a photorealistic portrait of a police officer.",
    )

    assert repaired == "Create a photorealistic portrait of a female police officer."


def test_existing_gender_translation_is_not_duplicated():
    repaired = repair_translation_semantics(
        "Erstelle ein Porträt einer Polizistin.",
        "Create a portrait of a female police officer.",
    )

    assert repaired == "Create a portrait of a female police officer."


def test_untranslated_fallback_is_left_unchanged():
    source = "Erstelle ein fotorealistisches Porträt einer Polizistin."

    assert repair_translation_semantics(source, source) == source


def test_lost_negation_falls_back_to_source_prompt():
    source = "Erstelle ein Porträt einer Frau ohne Brille."
    repaired = repair_translation_semantics(
        source,
        "Create a portrait of a woman wearing glasses.",
    )

    assert repaired == source


def test_lost_number_falls_back_to_source_prompt():
    source = "Erstelle ein Bild mit 2 Personen."
    repaired = repair_translation_semantics(
        source,
        "Create an image with people.",
    )

    assert repaired == source


def test_juggernaut_photorealistic_person_gets_restrained_realism_hints():
    payload = {
        "prompt": "Create a photorealistic portrait of a female police officer.",
        "model": "auto",
    }

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert "natural skin texture" in enhanced["prompt"]
    assert "visible pores" in enhanced["prompt"]
    assert "waxy skin" in enhanced["negative_prompt"]
    assert "3D render" in enhanced["negative_prompt"]


def test_german_fallback_prompt_can_still_receive_juggernaut_realism_hints():
    payload = {"prompt": "Fotorealistisches Porträt einer Frau."}

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert "natural skin texture" in enhanced["prompt"]


def test_user_negative_prompt_is_never_overridden():
    payload = {
        "prompt": "Create a photorealistic portrait of a woman.",
        "negative_prompt": "glasses",
    }

    enhanced = enhance_juggernaut_payload(
        payload,
        model="juggernaut-xl",
        explicit_negative_prompt=True,
    )

    assert enhanced["negative_prompt"] == "glasses"


def test_non_juggernaut_payload_is_unchanged():
    payload = {"prompt": "Create a photorealistic portrait of a woman."}

    enhanced = enhance_juggernaut_payload(payload, model="qwen-image")

    assert enhanced == {"prompt": "Create a photorealistic portrait of a woman."}


def test_non_human_juggernaut_photo_is_not_enriched():
    payload = {"prompt": "Create a photorealistic photo of a red sports car."}

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert enhanced == {"prompt": "Create a photorealistic photo of a red sports car."}
