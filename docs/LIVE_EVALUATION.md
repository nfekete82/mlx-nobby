# Live Intelligence – manuell geprüfte Live-Evaluation

Dies ist ein **Offline-Auswerter für echte, bereits durchgeführte Agent-Läufe**.
Er löst keine Webrecherche aus. Die bislang synthetische Benchmark-Suite bleibt
separat (`python -m agent.evidence_benchmark`).

## Datensatz anlegen

Erstelle außerhalb des Repositories `live-eval.jsonl`. Jede Zeile ist ein
JSON-Objekt für **dieselbe Frage** vor und nach der Reparatur. Als Grundlage
dienen die tatsächlichen Antworten, gemessenen Ende-zu-Ende-Laufzeiten und
nachträglich manuell geprüfte Referenzquellen.

Beispiel (ausschließlich Schema-Demo, **keine echte Live-Messung**):

```json
{"id":"demo-01","question":"Welche Preisangabe ist offiziell bestätigt?","reference_urls":["https://example.org/product"],"before":{"answer":"Preis 999 Euro.","elapsed_ms":1200},"after":{"answer":"Kein offizieller Preis bestätigt.","elapsed_ms":1450},"review":{"reviewer":"manual","before":"incorrect","after":"correct"}}
```

Wichtig: `example.org` durch die *tatsächlich geprüfte Artikel-URL* ersetzen
und Demo-Antworten niemals als produktive Messung eintragen.

## Auswertung

```bash
python -m pytest tests/test_live_evaluation.py -q
python -m agent.live_evaluation live-eval.jsonl --output live-report.json
```

Ergebnis: Anzahl Fälle, Labels vor/nach Reparatur, verbesserte Fälle,
Regressionen und zusätzliche Latenz (Mittelwerte). Mögliche Labels:

- `correct`: Aussage nach Sichtung der Referenz zutreffend
- `incorrect`: Aussage widerspricht der Referenz
- `unverifiable`: Referenz reicht zur Beurteilung nicht aus
- `not_answered`: Frage wurde nicht beantwortet

**Keine automatische Faktenprüfung:** Die CLI vertraut der menschlichen
Bewertung. Sie prüft Datenformat und berechnet Kennzahlen, aber ermittelt
weder Quellenqualität noch Ground Truth. Die Werte sind keine allgemeine
Halluzinationsquote. Ein realer A/B-Vergleich benötigt denselben Input, dieselben
Quellen und eine klar definierte Laufzeitmessung beider Varianten.
