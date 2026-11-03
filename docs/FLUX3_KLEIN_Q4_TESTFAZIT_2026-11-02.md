# FLUX 3 Image Klein Q4 – lokale Bewertung

**Stand:** 02.11.2026  
**Status:** Getestet, nicht übernommen / aus MLX-Nobby entfernt.

## Beobachtungen

- Die lokale Ausführung funktionierte technisch auf dem Apple-Silicon-Testgerät (M5 Max, 48 GB RAM).
- Ein erstes Bild überzeugte durch den fotorealistischen Eindruck und die allgemeine Bildqualität.
- Bei einer späteren klar formulierten Bildaufgabe wich das Ergebnis deutlich von der Anforderung ab. Für den vorgesehenen Workflow war die Zuverlässigkeit der Umsetzung damit nicht ausreichend.
- **Gesamturteil für unseren konkreten Workflow:** derzeit nicht geeignet. Keine Aussage über alle Einsatzgebiete des Modells.

## Messwerte aus einem lokalen Test

| Kennzahl | Ergebnis |
| --- | --- |
| Modell | `mflux-community/flux-3-image-klein-mflux-q4` |
| Runtime | MFLUX 0.24.0, separates Test-Venv |
| Auflösung | 1024 × 1024 Pixel |
| Generierung | 16 Schritte, ca. 17 Sekunden |
| Gemeldeter MLX-Spitzenspeicher | 4,08 GB |

Die Angaben sind Einzelmessungen und kein umfassender Benchmark. Ein verlässlicher Qualitätsvorteil gegenüber den bestehenden Modellen wurde nicht nachgewiesen.

## Entscheidung

- Die experimentelle FLUX-3-Integration wird nicht weitergeführt.
- Den Modell-Eintrag `mflux-flux3-image-klein-q4` aus vorhandenen Registries automatisch auslaufen lassen.
- **Juggernaut XL** bleibt unverändert, ebenso die übrigen produktiven Bildmodelle und vorhandene Bilddateien.
- Erneut testen nur bei einer substanziell überarbeiteten Modellversion oder nach belastbaren neuen Vergleichsergebnissen.
