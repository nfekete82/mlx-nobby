# Live Capture v1

Separater, **explizit auszulösender** Sammler für tatsächliche lokale
Agent-Anfragen. Speichert Rohantworten und gemessene Gesamtdauer in JSONL,
ohne automatische Wahrheitsbewertung und ohne fingierte Vorher/Nachher-Daten.

Der Sammler spricht einen vom Betreiber angegebenen lokalen JSON-Endpunkt
mit `POST {"message":"..."}` an. **Das ist ein Endpunkt-Vertrag, keine
Behauptung, dass der laufende Agent diese Route bereits anbietet.**
Vor dem Einsatz anhand der tatsächlichen FastAPI-Routen prüfen, ob dieser
Vertrag stimmt. Insbesondere ist `/v1/chat/completions` in diesem Projekt
ein **zustandsloser Modell-Transport ohne Agent-Tools** und für einen
Live-Intelligence-Agent-Benchmark nicht geeignet.

## Vorbereitung und Ausführung

In `questions.json` steht ein Array mit kurzen Testfragen:

```json
["Wer ist heute Bundeskanzler?","Welche offiziellen Preise wurden für das Pixel 11 angekündigt?","Was ist 17 mal 23?"]
```

Nur wenn eine passende lokale Agent-Route existiert, explizit starten:

```bash
python -m pytest tests/test_live_capture.py tests/test_live_evaluation.py -q
python -m agent.live_capture \
  --endpoint http://127.0.0.1:8010/DEINE_VERIFIZIERTE_AGENT_ROUTE \
  --questions questions.json --output live-capture.jsonl
```

Maximal 100 Fragen pro Lauf, nur Loopback-HTTP, Ausgabe wird niemals
überschrieben. Rohantworten können sensible Daten enthalten: nur lokal
speichern und nicht ins Repository committen.

## Grenzen

- Keine automatische Behauptungs- oder Quellenprüfung; menschliches Review nötig.
- Der bestehende `agent.live_evaluation`-Evaluator erwartet separate
  reviewte Before/After-Datensätze. `live-capture.jsonl` ist **noch kein**
  Eingabeformat für diesen Evaluator.
- Für echte A/B-Messungen müssen identische Fragen und vergleichbare
  Quellenstände einmal mit und einmal ohne Repair durchlaufen werden.
- Der Collector erzeugt weder automatisch 50 verschiedene Fragen noch
  erzwingt er Quellen oder Tool-Nutzung.
