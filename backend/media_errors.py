"""Fixed public image validation text; never echo validator inputs into chat."""

INVALID_IMAGE_REQUEST = "Die Bildanfrage ist ungültig. Bitte Modell, Bildgröße, Parameter und Referenzbild prüfen."

PUBLIC_IMAGE_VALIDATION_MESSAGES = frozenset({
    INVALID_IMAGE_REQUEST, "Ungültige Image-Job-ID", "Ungültige Image-Modell-ID",
})


def image_validation_message(detail):
    return detail if isinstance(detail, str) and detail in PUBLIC_IMAGE_VALIDATION_MESSAGES else INVALID_IMAGE_REQUEST
