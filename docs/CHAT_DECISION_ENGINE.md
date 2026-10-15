# Chat Decision Engine (erste Ausbaustufe)

Die bestehende semantische Klassifikation (kleiner Router + optionaler Manager)
bleibt die **einzige** allgemeine Intent-Erkennung. Die Decision Engine
`agent/chat_decision.py` legt einen einheitlichen Vertrag fest:

| kind | Bedeutung |
| --- | --- |
| `answer` | Normaler Chat ohne Tool |
| `clarify` | Ein Pflicht-Slot fehlt, gezielte Rückfrage |
| `execute_tool` | Alle nötigen Angaben liegen vor, Tool/Agent wird ausgeführt |

Der sichere Slot-Planer erkennt derzeit **nur Wetter** deterministisch. Für
alle anderen Aufgaben wird keine zweite Routing-Implementierung eingeführt:
Die Anfrage bleibt bei der vorhandenen semantischen Pipeline und
`decision_for_route` stellt ihre Auswahl im selben Format dar.
Ein späterer Tool-Slot-Katalog muss die erforderlichen Angaben pro
Fähigkeit definieren (ohne pauschale Rückfragen).

## Einheitlicher Weg

1. `POST /api/chat/actions/route`: identische Slot-Entscheidung,
   **ohne** Provideraufruf; `decision` wird ausgegeben.
2. `POST /api/chat/actions`: gleiche Entscheidung, tatsächlich
   rückfragen bzw. Open-Meteo über den vorhandenen `web_search`-Toolvertrag
   aufrufen. Modell/Agent/Media- und Dateiaktionen behalten ihre bestehende
   Zuständigkeit.
3. Frontend sendet nur explizit verifizierte `weather_location` aus einer
   erfolgreichen Wetter-Toolantwort als strukturierten Gesprächskontext.
   Nichts wird global gespeichert oder aus Nutzerprofil/IP geraten.

## Beispielgespräche

- `Wie wird das Wetter heute?` → `clarify(location)`
- `Göppingen` → `execute_tool(web_search, Wetter heute in Göppingen)`
- `Und morgen?` → `execute_tool(web_search, Wetter morgen in Göppingen)`
- `Wie wird das Wetter morgen?` → `clarify(location)` → `73033`
  → Wetter **morgen**, nicht heute (sofern Open-Meteo die PLZ auflösen kann)
- `Was gibt es heute Neues?` → vorhandener Router / News-Provider
- Bild- oder Dateiaktionen → unveränderte etablierte Routen

## Grenzen / Sicherheit

- Weder vage noch private Ortsangaben werden erfunden.
- Medienaktionen und Attachments werden vom Slot-Fastpath nicht abgefangen.
- Unklare Kontexte bleiben beim bisherigen semantischen Router.
- `weather_context_query` akzeptiert kurze explizite Ortsangaben nur
  unmittelbar nach der passenden Rückfrage; Folgefragen verwenden
  die zuletzt vom Wettertool verifizierte Ortsangabe.
- Der allgemeine Rückfragenmechanismus ist erweiterbar, aber **noch nicht**
  mit Pflicht-Slots für jedes Tool versehen.
- Provider-Ausfälle werden weiterhin als Ausfall ausgegeben, nicht mit
  Modellwissen aufgefüllt.

## Tests / Rollout

```bash
python -m pytest -q tests/test_chat_decision.py tests/test_weather_context.py \
    tests/test_chat_actions_web_search.py tests/test_weather_forecast.py
node --check frontend/assets/chat/generation.js
```

Nach Merge in `main` lokal einen Deployment-Branch verwenden, da `main`
bereits im separaten Worktree `~/mlx-web-v1-11-final-check` belegt sein kann.
Agent-Neustart ist für den Python-Router notwendig. Wegen des strukturierten
Browser-Kontexts ist zusätzlich ein Docker-Frontend-Rebuild erforderlich.
