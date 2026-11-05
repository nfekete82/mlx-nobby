#!/usr/bin/env python3
"""Read-only, content-redacted conflict audit for the local MLX-Nobby Agent.

Print ONLY aggregate counts: never raw facts, sensitive values, quotes,
chat IDs, names, source IDs or private file locations.
Uses 127.0.0.1:8010 GET only. Does not edit or replay existing memories.
"""
from __future__ import annotations

from collections import Counter
import json
from urllib.request import urlopen


def subject_group(subject):
    subject = str(subject or "").casefold()
    if subject == "ich":
        return "ich"
    if subject == "partner":
        return "partner"
    if subject.startswith("familie."):
        return "familie"
    if subject.startswith("projekte."):
        return "projekte"
    if subject.startswith("personen."):
        return "personen"
    return "sonstige"


def field_root(field):
    return str(field or "unbekannt").split(".", 1)[0]


def aggregate(conflicts):
    """Return sanitized aggregates; source values are neither logged nor saved."""
    counter = Counter()
    repeated = Counter()
    for item in conflicts:
        counter[(field_root(item.get("field")), subject_group(item.get("subject")))] += 1
        repeated[str(item.get("fact_id", ""))] += 1
    per_field = Counter()
    for (field, _subject), count in counter.items():
        per_field[field] += count
    # Only expose the number of anchors with multiple candidate replacements.
    repeated_anchors = sum(count > 1 for count in repeated.values())
    return per_field, counter, repeated_anchors


def main():
    with urlopen("http://127.0.0.1:8010/api/personal-memory/conflicts",
                 timeout=15) as response:
        payload = json.load(response)
    issues = payload.get("conflicts", [])
    if not isinstance(issues, list):
        raise ValueError("Unexpected conflict response")
    per_field, grouped, repeated_anchors = aggregate(issues)
    print("=== OFFENE WIDERSPRÜCHE: ANONYMISIERTE VERTEILUNG ===")
    print("Total:", len(issues))
    print("Mehrere Vorschläge zum selben ursprünglichen Fakt:", repeated_anchors)
    for (field, subject), count in sorted(
        grouped.items(), key=lambda item: (-item[1], item[0])
    ):
        print(f"{field:18} {subject:12} {count:3d}")
    print("\n=== NÄCHSTE SCHRITTE ===")
    print("Gesundheit / Beziehung: getrennte, nicht-exklusive Aspekte prüfen.")
    print("Status: erst eindeutigen Zustand/Aspekt und Zeitbezug klären.")
    print("Name, Geburtsort, Beruf: echte Widersprüche nicht automatisch auflösen.")
    print("Die  bestehenden Konflikte bleiben vollständig unverändert.")
    print("Keine privaten Werte, Chat-IDs oder Quellentexte ausgegeben.")


if __name__ == "__main__":
    main()
