from backend.weather_context import weather_context_query


def test_location_answer_continues_weather_question():
    history = [
        {"role": "user", "content": "Wie wird das Wetter heute?"},
        {"role": "assistant", "content": "Für welchen Ort möchtest du das Wetter wissen? Nenne mir bitte eine Stadt oder Postleitzahl."},
    ]
    assert weather_context_query("Göppingen", history) == "Wie wird das Wetter heute in Göppingen?"
    assert weather_context_query("ja", history) is None


def test_tomorrow_uses_explicit_preceding_city():
    history = [
        {"role": "user", "content": "Wie wird das Wetter heute in Göppingen?"},
        {"role": "assistant", "content": "Wetter für Göppingen, Baden-Württemberg, Deutschland heute (15.10.2026): neblig."},
    ]
    assert weather_context_query("Und morgen?", history) == "Wie wird das Wetter morgen in Göppingen?"
    assert weather_context_query("Und NVIDIA?", history) is None


def test_unrelated_conversation_cannot_supply_location():
    history = [
        {"role": "user", "content": "Ich war heute in Göppingen"},
        {"role": "assistant", "content": "Alles klar."},
    ]
    assert weather_context_query("Und morgen?", history) is None
    assert weather_context_query("Stuttgart", history) is None
