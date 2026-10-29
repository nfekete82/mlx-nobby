"""Public video validation messages. Never echo validator inputs or diagnostics."""

INVALID_VIDEO = "Die Videoanfrage ist ungültig. Bitte Dauer, Qualität, Profil und Startbild prüfen."
UNCENSORED_CONTINUATION = (
    "Das Profil „Uncensored“ unterstützt keine automatische Fortsetzung. "
    "Wähle Standard für längere Videos oder verkürze die Dauer "
    "(maximale Qualität: 5 s, Standard: 10 s, Schnell: 20 s)."
)
MESSAGES = {
    "uncensored_video_continuation_unsupported": UNCENSORED_CONTINUATION,
    "video_profile_unavailable": "Das Profil „Uncensored“ ist nicht eingerichtet. Bitte Standard wählen.",
}


def video_validation_message(detail):
    """Allow only public codes and our own fixed messages across service hops."""
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("type")
        return MESSAGES.get(code, INVALID_VIDEO) if isinstance(code, str) else INVALID_VIDEO
    if isinstance(detail, list):
        for item in detail:
            message = video_validation_message(item)
            if message != INVALID_VIDEO:
                return message
    if isinstance(detail, str) and detail in (INVALID_VIDEO, *MESSAGES.values()):
        return detail
    return INVALID_VIDEO
