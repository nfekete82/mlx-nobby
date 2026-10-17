# Chat-Streaming- und Kontext-Reuse-Benchmark (opt-in)

Dieser Benchmark testet das **laufende MLX-Nobby-Agenten-Streaming** und
verändert keine Runtime-Einstellungen, Modellgewichte, DFlash2-Parameter,
RAM-Limits oder Modellrollen.

## Durchführung auf dem Mac

Nur starten, wenn Chat und Medienjobs ruhen. Mit dem aktuell geladenen
Qwen3.8-27B-Modell und aktiviertem DFlash2:

```bash
cd ~/mlx-web
python3 scripts/benchmark-chat-experience.py   --agent-url http://127.0.0.1:8010   --context-sizes 4000   --samples 3   --max-tokens 48
```

Optional ein ausführlicher (und entsprechend rechenintensiverer) Durchlauf:

```bash
python3 scripts/benchmark-chat-experience.py   --context-sizes 4000,8000,16000   --samples 3   --max-tokens 48   --output /tmp/nobby-chat-experience-1.json
```

Der optionale JSON-Bericht wird **exklusiv neu** mit Dateirechten `0600`
angelegt. Existierende Reports werden nicht überschrieben. Ohne
`--output` wird nur auf stdout ausgegeben. Prompts, Antworten, Datei- oder
Chatverläufe werden nicht protokolliert.

Benutzt werden:
- `POST /api/runtime/chat/stream` am lokalen Agenten auf Port 8010.
  Dieser Pfad übernimmt den existierenden Runtime-Lease,
  Modell-Lock und die Server-seitige Zulassung.
- `GET /api/performance/observatory?limit=100` für lokale
  Statuskontrolle und *historische* Router-Metriken.
- Ausschließlich synthetische, deterministisch aufgebaute
  Testtexte mit wechselnder Nonce. Keine vorhandenen Gespräche
  oder Benutzerdateien werden gelesen.

### Kennzahlen richtig verstehen

| Kennzahl | Bedeutung |
| --- | --- |
| `short.first_content_ms.p50/p95` | Warm-/Wiederholungsbeobachtung bis zum **ersten sichtbaren** Chattext einschließlich Gateway/Queue/Prefill |
| `short.total_ms` | Gesamtdauer inklusive Modellausgabe |
| `contexts[].priming` | Erster Request mit neuem langen Kontext; nicht zwangsläufig kalt |
| `contexts[].same_prefix_followup` | Gleicher Chat-Präfix plus Antwort und Folgefrage |
| `contexts[].different_prefix_control` | Gleich großer synthetischer, aber anderer Kontext vor derselben Folgefrage |
| `contexts[].control_minus_followup_first_content_ms` | Positiv heißt: Follow-up war schneller; ein **Hinweis**, aber kein Beweis für einen Cache-Hit |
| `router.total_ms` | Historische Klassifizierungszeit vorhandener `router.classify`-Aufrufe, **nicht** Zeit der Benchmark-Anfragen |

Der Agent-Streaming-Endpunkt stellt derzeit keine präzisen nativen
`prompt_ms` bereit. Die TTFT umfasst auch Queuing und Prefill; sie
ist **keine isolierte Prefill-Messung**. Für native Prompt-Metriken ist
zusätzlich `scripts/benchmark-chat-latency.py` auf Port 8000 vorhanden,
der aber den Agent-Lease umgeht und separat unter kontrollierten Bedingungen
eingesetzt werden sollte.

Die Größen 4k/8k/16k sind mit ca. vier Zeichen pro Token **heuristisch
dimensioniert**. Die reale Tokenzahl kann erheblich abweichen. Ein
Tokenizer-/Cache-Hit-Zähler wird hier nicht gemessen. Das
Vergleichspaar isoliert auch nicht vollständig die Unterschiede zwischen
unterschiedlichen Prompt-Inhalten, Systemtemperatur und Cache-Zuständen.
Darum bitte Aussagen zu Beschleunigung erst aus wiederholten,
vergleichbaren Läufen und möglichst mit nativen Timing-/Cache-Metriken
ableiten.

### Betrieb und Schutz

- Nur Loopback-HTTP erlaubt; keine externen Server oder Netzübertragung.
- Der Benchmark ist **opt-in** und erzeugt mehrere echte Modellantworten.
- Im Agenten-Observatory aktive Chat-, Bild- oder Videoruntimes verhindern
  den nächsten Probeaufruf. Während jedes Streams greifen zusätzlich die
  existierenden Modell-/Runtime-Sperren.
- Keine Modellinstallation, keine ungefragten Restarts, kein Workload in CI.
- Keine Änderung an RAM-Guard, Prefill-Step-Size, Draft-Blockgröße
  oder Thinking-Konfiguration.
- Standard: drei kurze Antworten plus drei Antworten für 4k Kontext.
  Größere Kontexte müssen explizit angefordert werden.
- Die synthetischen Tests umgehen den Intent-Router, weil er unabhängig
  beobachtet wird. Der historische Router-p50 kann auch null sein,
  wenn seit Agent-Neustart keine geeigneten Daten vorliegen.

### CPU-Tests

```bash
python3 -m pytest -q tests/test_chat_experience_benchmark.py
```

Die Tests ersetzen sämtliche Netzwerk-Aufrufe und verursachen keine
echte Modellinferenz. Anschließend gelten die normalen CI-Prüfungen
auf GitHub.
