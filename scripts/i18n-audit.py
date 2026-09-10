#!/usr/bin/env python3

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
I18N_SOURCE = ROOT / "frontend/assets/chat/i18n.js"
TRANSLATION_FILES = {
    "en": ROOT / "frontend/i18n/en.json",
    "de": ROOT / "frontend/i18n/de.json",
}
SCAN_FILES = [
    ROOT / "frontend/chat.html",
    ROOT / "frontend/index.html",
    *sorted((ROOT / "frontend/assets/chat").glob("*.js")),
    *sorted((ROOT / "frontend/assets/control").glob("*.js")),
    *sorted((ROOT / "frontend/assets").glob("*.js")),
]

# Intentional German content rather than untranslated UI.
ALLOWLIST = {
    "modelList",
    "imageModelList",
    "Deutsch knapp",
    "Deutsch",
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
        Datei(?:en|typ)?|
        Darstellung|
        Einstellungen?|
        Entfernen|
        Fehler|
        Hinzufügen|
        Löschen|
        Nicht|
        Modell(?:e|rollen|wechsel)?|
        Neue?r?|
        Notiz(?:en|text)?|
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
        Öffnen|
        Anzeigen|
        Abbrechen|
        Abgeschlossen|
        Aktiv(?:e|iert)?|
        Aktualisieren|
        Automatisch|
        Benutzerdefiniert|
        Daten|
        Deutsch|
        Dienste?|
        Einträge?|
        Fehlgeschlagen|
        Fertig|
        Fortsetzen|
        Gestoppt|
        Hochgeladen|
        Indexieren|
        Kein(?:e|er|es|en)?|
        Lade|
        Lokal(?:e|er|es|en)?|
        Profil|
        Reindexieren|
        Suche|
        Unterbrochen|
        Unbekannt|
        Wartet|
        Wissensbasis|
        Verwaltung
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

I18N_HTML_ATTRIBUTES = (
    "data-i18n=",
    "data-i18n-title=",
    "data-i18n-aria-label=",
    "data-i18n-placeholder=",
)


def clean_value(value: str) -> str:
    return value.strip().strip("'\"`").strip()


def is_allowed(value: str) -> bool:
    return clean_value(value) in ALLOWLIST


def html_line_is_translated(line: str) -> bool:
    return any(attribute in line for attribute in I18N_HTML_ATTRIBUTES)


def extract_line_candidates(line: str):
    for match in re.finditer(r">([^<>]+)<", line):
        value = match.group(1).strip()
        if value:
            yield value

    for match in re.finditer(
        r'\b(?:title|aria-label|placeholder)="([^"]+)"',
        line,
    ):
        yield match.group(1).strip()

    for match in re.finditer(
        r"""(?P<q>['"`])(?P<value>.*?)(?P=q)""",
        line,
    ):
        value = match.group("value").strip()
        if value:
            yield value


def flatten_keys(value, prefix=""):
    keys = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            keys.update(flatten_keys(child, path))
        else:
            keys.add(path)
    return keys


problems = []

i18n_source = I18N_SOURCE.read_text(encoding="utf-8")
if "const DEFAULT_LANGUAGE = 'en';" not in i18n_source:
    problems.append(("frontend/assets/chat/i18n.js", 1, "English is not the default language"))
if "localStorage.getItem(STORAGE_KEY)" not in i18n_source:
    problems.append(("frontend/assets/chat/i18n.js", 1, "Saved language is not read"))
if "localStorage.setItem(STORAGE_KEY, nextLanguage)" not in i18n_source:
    problems.append(("frontend/assets/chat/i18n.js", 1, "Selected language is not persisted"))
if "navigator.language" in i18n_source:
    problems.append(("frontend/assets/chat/i18n.js", 1, "Browser locale overrides the English default"))

translations = {
    language: json.loads(path.read_text(encoding="utf-8"))
    for language, path in TRANSLATION_FILES.items()
}
translation_keys = {
    language: flatten_keys(content)
    for language, content in translations.items()
}
missing_in_de = sorted(translation_keys["en"] - translation_keys["de"])
missing_in_en = sorted(translation_keys["de"] - translation_keys["en"])
if missing_in_de:
    problems.append(("frontend/i18n/de.json", 1, f"Missing keys: {', '.join(missing_in_de)}"))
if missing_in_en:
    problems.append(("frontend/i18n/en.json", 1, f"Missing keys: {', '.join(missing_in_en)}"))

for path in SCAN_FILES:
    if not path.exists():
        continue

    relative = path.relative_to(ROOT)
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "/*", "*", "#")):
            continue
        if path.suffix == ".html" and html_line_is_translated(line):
            continue

        for value in extract_line_candidates(line):
            if is_allowed(value) or not GERMAN_PATTERN.search(value):
                continue
            problems.append((str(relative), line_number, value))

    if path.suffix == ".html":
        for match in re.finditer(
            r"<(?P<tag>option|button|label|p|div|span|strong|small|h[1-6])\b"
            r"(?P<attrs>[^>]*)>(?P<body>[^<>]+)</(?P=tag)>",
            source,
            re.DOTALL | re.IGNORECASE,
        ):
            attrs = match.group("attrs")
            if any(attribute in attrs for attribute in I18N_HTML_ATTRIBUTES):
                continue
            value = re.sub(r"\s+", " ", match.group("body")).strip()
            if is_allowed(value) or not GERMAN_PATTERN.search(value):
                continue
            line_number = source.count("\n", 0, match.start()) + 1
            item = (str(relative), line_number, value)
            if item not in problems:
                problems.append(item)

        for match in re.finditer(
            r'data-i18n(?:-title|-aria-label|-placeholder)?="([^"]+)"',
            source,
        ):
            key = match.group(1)
            if key not in translation_keys["en"]:
                line_number = source.count("\n", 0, match.start()) + 1
                problems.append((str(relative), line_number, f"Unknown translation key: {key}"))


if problems:
    print("Internationalization audit failed:")
    print()
    for filename, line_number, value in problems:
        print(f"{filename}:{line_number}: {value}")
    print()
    print(f"{len(problems)} problem(s) found")
    raise SystemExit(1)

print("✓ English default and language persistence verified")
print("✓ English and German translation keys match")
print("✓ No obvious untranslated German UI strings found")
