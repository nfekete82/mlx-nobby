#!/usr/bin/env python3

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

SCAN_FILES = [
    ROOT / "frontend/chat.html",
    *sorted((ROOT / "frontend/assets/chat").glob("*.js")),
    ROOT / "frontend/assets/chat.js",
]

# Bewusst deutsche Inhalte / technische Identifier.
ALLOWLIST = {
    "modelList",
    "imageModelList",
    "Antworte auf Deutsch, präzise, knapp und ohne unnötige Wiederholungen.",
}

GERMAN_PATTERN = re.compile(
    r"""
    \b(
        Allgemein|
        Aktuell(?:e|er|es|en)?|
        Antwort(?:en|informationen|präferenzen)?|
        Bearbeiten|
        Bereit|
        Bild(?:er|generierung)?|
        Datei(?:en)?|
        Darstellung|
        Einstellungen?|
        Entfernen|
        Fehler|
        Hinzufügen|
        Löschen|
        Modell(?:e|rollen|wechsel)?|
        Neue?r?|
        Notiz(?:en)?|
        Ordner|
        Persönlich(?:e|er|es|en)?|
        Quelle(?:n)?|
        Seitenleiste|
        Speichern|
        Speicher|
        Sprache|
        Wird|
        Auswählen|
        Schließen|
        Öffnen
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# HTML-Attribute, deren deutscher Wert absichtlich als Fallback
# im Markup verbleiben darf.
I18N_HTML_ATTRIBUTES = (
    "data-i18n=",
    "data-i18n-title=",
    "data-i18n-aria-label=",
    "data-i18n-placeholder=",
)


def clean_value(value: str) -> str:
    value = value.strip()
    value = value.strip("'\"`")
    return value.strip()


def is_allowed(value: str) -> bool:
    return clean_value(value) in ALLOWLIST


def html_line_is_translated(line: str) -> bool:
    return any(attribute in line for attribute in I18N_HTML_ATTRIBUTES)


def extract_candidates(line: str):
    # HTML sichtbarer Text
    for match in re.finditer(r">([^<>]+)<", line):
        value = match.group(1).strip()
        if value:
            yield value

    # Attribute
    for match in re.finditer(
        r'\b(?:title|aria-label|placeholder)="([^"]+)"',
        line,
    ):
        yield match.group(1).strip()

    # JS string literals
    for match in re.finditer(
        r"""(?P<q>['"`])(?P<value>.*?)(?P=q)""",
        line,
    ):
        value = match.group("value").strip()
        if value:
            yield value


hits = []

for path in SCAN_FILES:
    if not path.exists():
        continue

    relative = path.relative_to(ROOT)

    for line_number, line in enumerate(
        path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines(),
        start=1,
    ):
        stripped = line.strip()

        # Kommentare überspringen.
        if stripped.startswith(("//", "/*", "*", "#")):
            continue

        # Bereits markierte HTML-Fallbacks überspringen.
        if path.suffix == ".html" and html_line_is_translated(line):
            continue

        for value in extract_candidates(line):
            if is_allowed(value):
                continue

            if not GERMAN_PATTERN.search(value):
                continue

            hits.append(
                (
                    str(relative),
                    line_number,
                    value,
                )
            )


if hits:
    print("Potential untranslated German UI strings:")
    print()

    for filename, line_number, value in hits:
        print(
            f"{filename}:{line_number}: {value}"
        )

    print()
    print(f"{len(hits)} potential strings found")
else:
    print("✓ No untranslated German UI strings found")
    print("0 potential strings found")
