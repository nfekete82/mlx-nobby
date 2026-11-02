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
    assert "physically plausible light" in enhanced["prompt"]
    assert "unretouched photographic look" in enhanced["prompt"]
    assert "negative_prompt" not in enhanced


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


def test_negative_prompt_is_empty_by_default_for_ragnarok():
    payload = {"prompt": "Photorealistic portrait of a woman."}

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert "negative_prompt" not in enhanced


def test_explicit_retouched_style_wins_over_automatic_hints():
    payload = {"prompt": "Glossy glamour photorealistic portrait of a woman."}

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert enhanced == {"prompt": "Glossy glamour photorealistic portrait of a woman."}


def test_long_user_prompt_is_not_extended_with_default_suffix():
    prompt = "A photorealistic portrait of a woman, " + " ".join(
        ["specific visual direction"] * 30
    )
    payload = {"prompt": prompt}

    enhanced = enhance_juggernaut_payload(payload, model="juggernaut-xl")

    assert enhanced["prompt"] == prompt
    assert "negative_prompt" not in enhanced


def test_ragnarok_short_hint_is_not_applied_twice():
    payload = {"prompt": "A photorealistic portrait of a woman."}

    first = enhance_juggernaut_payload(payload, model="juggernaut-xl")
    second = enhance_juggernaut_payload(first, model="juggernaut-xl")

    assert second["prompt"].count("natural skin texture") == 1


def test_nonphotographic_user_negative_is_untouched():
    payload = {"prompt": "A watercolor painting of a cat", "negative_prompt": "photograph"}
    assert enhance_juggernaut_payload(payload, model="juggernaut-xl") == payload
