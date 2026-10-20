# Chat Quality v1 – reproduzierbare Qwen-Baseline

**Phase 1 von Chat Quality 2.0** ist ein **opt-in** Qualitätstest über den vorhandenen macOS-Agenten. Er nutzt den bestehenden Runtime-Lease, Modell-Lock und die RAM-Zulassung. Er startet, stoppt, lädt oder konfiguriert **keine** Modelle und Dienste; alle Eingaben sind synthetisch.

## Eingefrorene Suite

Die Datei `benchmarks/chat-quality-v1.json` enthält **48 Aufgaben** mit einer Suite-SHA256:

- **44 automatisch bewertete Fälle:** je acht Deutsch, Logik/Arithmetik, PHP 8, JavaScript und SQLite 3 sowie vier Chatverläufe für Kontext- und Korrekturtreue.
- **Vier Fälle zur manuellen Bewertung:** konkrete Beratung, sichere PHP-PDO-Codegenerierung, Quellentreue anhand eines *im Prompt vorgegebenen* synthetischen Auszugs und technische Langantwort. Die zugehörigen Prüfkriterien stehen in der Suite.
- Strenges Antwortprotokoll für die 44 Fälle: genau ein JSON-Objekt mit einem einzigen String-Feld `{"answer":"..."}`. Nur Unicode-NFC, Rand-Leerzeichen und Groß-/Kleinschreibung werden normalisiert. Falsche Antworten und Formatfehler bleiben unterscheidbar.

Die vier Review-Fälle fließen **nicht** in die automatische Genauigkeit ein. Sie prüfen weder echten RAG-Retrieval noch automatisch die Qualität generierten Codes. Ein Score ist kein universelles Intelligenzmaß.

## Lokaler Testlauf auf deinem Mac

Nur starten, wenn keine sonstigen Chat-, Bild- oder Videojobs laufen. Agent und Qwen müssen bereits auf dem Mac laufen.

```bash
cd ~/mlx-web
git switch main
git pull --ff-only origin main

# Schneller Verbindungstest – bewusst NICHT mit Baselines vergleichbar
./scripts/mlx benchmark chat-quality run --smoke \
  --output /tmp/nobby-quality-smoke-1.json

# Vollständige Baseline mit 48 echten Modellantworten
./scripts/mlx benchmark chat-quality run \
  --output /tmp/nobby-quality-baseline-1.json \
  --review-file /tmp/nobby-quality-manual-1.json
```

**Achtung:** Der komplette Lauf kann mehrere Minuten dauern. Modell und Hardware bleiben unverändert; die Antworten werden sequenziell erzeugt. Vor jeder Frage prüft das Programm die aktive Modellidentität/PID und die Runtime-Auslastung. Ein abgebrochener Lauf wird mit `partial` markiert; es wird dann keine vollständige Prozentzahl errechnet.

Nach einer **bewusst separat vorgenommenen** Modell- oder Runtime-Änderung:

```bash
./scripts/mlx benchmark chat-quality run \
  --output /tmp/nobby-quality-candidate-1.json \
  --review-file /tmp/nobby-quality-manual-candidate-1.json

# Vollständig offline; keine Modellinferenz
./scripts/mlx benchmark chat-quality compare \
  --baseline /tmp/nobby-quality-baseline-1.json \
  --candidate /tmp/nobby-quality-candidate-1.json \
  --output /tmp/nobby-quality-comparison-1.json
```

Der Vergleich verlangt identische Aufgaben-SHA und Generationseinstellungen sowie je **48 vollständige Resultate**. Ausgegeben werden neue Treffer, Regressionen, Ergebnisse je Kategorie, Median-Ersttext-Latenz (TTFT) und Median-Gesamtlaufzeit. Der Entscheidungscode lautet absichtlich immer `REVIEW` beziehungsweise `REGRESSION_REVIEW`: selbst ein perfekter Score ist keine automatische Freigabe für den Produktivbetrieb.

## Messgrenzen und Datenschutz

- **TTFT** ist das erste *sichtbare* Content-Delta, einschließlich Gateway, Warteschlange und Prefill. Der Agent-SSE-Endpunkt liefert hier **keine** validen nativen Token/s. Die werden nicht erfunden. Model Scout, Performance Observatory und die bestehenden Cache-Benchmarks bleiben für native Durchsatz-/Cachingdiagnosen zuständig.
- Das Netzwerk bleibt auf explizites HTTP-Loopback begrenzt; keine Proxy- oder Redirect-Weiterleitung an externe Hosts.
- Der Hauptbericht enthält **keine** Prompts, Antworten, alten Chats, persönlichen Dateien oder andere Benutzerinhalte, nur Fall-IDs, Noten, Zeiten, Suite-Fingerprint und Runtime-Identität.
- Nur per `--review-file` werden die vier *synthetischen* Review-Antworten für menschliche Sichtung gespeichert.
- Neue Reports entstehen exklusiv mit Dateirechten `0600` und überschreiben keine vorhandenen Dateien/Symlinks. Verwende für jede Messung neue Dateinamen.
- Ein fehlendes Modell, veränderte PID, aktiver anderer Runtime-Job, Abbruch oder ein unvollständiger Stream führt zu `partial`; solche Berichte sind **nicht vergleichbar**.
- Suite-Hash und Parameterabgleich schützen vor versehentlicher Verwechslung, sind aber **keine** manipulationssichere Signatur. Timing kann durch thermische Bedingungen, Warm-up, Modellzustand und parallele Last variieren.
- Die synthetische Quellentreue-Prüfung ist **kein** vollständiger Test der RAG-/Retrieval-Kette. Das sollte Phase 2 leisten.

## Prüfen (ohne echte Modellinferenz)

```bash
python3 -m pytest -q tests/test_chat_quality_benchmark.py
python3 scripts/benchmark-chat-quality.py --help
```

Die CI prüft ausschließlich Programmverhalten und Fixtures. Ein echter Lauf auf dem M5 Max ist für empirische Modellwerte weiterhin erforderlich. Dies ist **kein** neues Release oder eine automatische Aktivierung experimenteller APC/DFlash-Profile.
