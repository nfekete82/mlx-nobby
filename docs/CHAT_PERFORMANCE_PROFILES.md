# MLX-Nobby Chat-Leistungsprofile (experimentell)

Nobby unterstützt zwei **opt-in** Chat-Modi auf dem lokalen Apple-Silicon-Modellserver.
Die Standardkonfiguration bleibt unangetastet, solange kein Profil gewählt wird.

Hintergrund: Auf dem M5 Max mit MLX-VLM 0.6.17 und
Qwen3.8-27B-Abliterated-MLX-4bit ist DFlash2 beim Generieren schnell (ca.
40 Tokens/s). Das MLX-VLM-0.6.17-DFlash-Prefill nutzt jedoch keine APC-Wiederverwendung.
Beim lokalen Versuch mit APC statt DFlash betrug die Ersttext-Latenz für
eine ~4k-Kontext-Folgefrage 423 ms statt 8.691 ms; ein Exact-Cache-Hit mit
7572 matched tokens wurde bestätigt. Das sind **Einzelmessungen**, kein
genereller Performanceanspruch. Erstantwort und veränderter Kontext
brauchten weiterhin rund 8–9 Sekunden.

## CLI

```bash
cd ~/mlx-web
./scripts/mlx chat-profile status
./scripts/mlx chat-profile apc
./scripts/mlx chat-profile dflash
./scripts/mlx chat-profile default
```

| Profil | Eigenschaften |
| --- | --- |
| `default` (Vorgabe) | Alte Konfiguration wie bisher. **Kein APC/DFlash-Override**, keine Runtime-Neustarts beim Upgrade |
| `dflash` | Bereits eingerichteten und lokalen DFlash-Drafter verwenden, APC deaktivieren. Bestätigt `--draft-model` und `--draft-kind dflash` am laufenden Server |
| `apc` | DFlash im Serverprozess ausschalten, APC im RAM einschalten, 512 Blöcke × 16 Tokens und ein Exact-Cache-Eintrag, **keine APC-Disk-Persistenz** |

APC und DFlash sind in dieser Version getrennte Modi: `mlx_vlm`
0.6.17 wählt für DFlash einen spekulativen Pfad, der
`cached_tokens=0` meldet. Beide gleichzeitig zu aktivieren ist
hier keine nachgewiesene Verbesserung.

Der Profilwechsel schreibt **nur** die Variable
`MLX_CHAT_PERFORMANCE_PROFILE` in
`~/.config/mlx-server/config`. Die ursprünglichen
`SPECULATIVE_*`-Werte bleiben unverändert.
`default` entfernt den neuen Profileintrag wieder.
Anschließend startet ausschließlich der Modellserver neu;
Agent, Router, Docker und Medien-Dienste werden nicht neu gestartet.
Es wird weder ein Modell heruntergeladen noch der globale RAM-Guard
modifiziert oder umgangen.

Bei fehlerhaftem Start wird versucht, die vorherige
Konfiguration automatisch wiederherzustellen und erneut zu starten.
Die CLI lehnt den Profilwechsel ab, wenn Agent/Observatory
nicht erreichbar oder Chat/Medienjobs bzw. eine Runtime-Lease
aktiv sind. Profilwechsel nur auf einem ansonsten ruhenden
System durchführen. Falls beim Neustart zu wenig freier Speicher
vorhanden ist, kann der bereits vorhandene Runtime-Guard den Start
verzögern; laufende Daten gehören nicht in ein Experiment.

## Kontrollierter A/B-Benchmark mit längeren Antworten

```bash
cd ~/mlx-web
./scripts/mlx chat-profile status
./scripts/mlx chat-profile compare   --context-sizes 4000   --samples 2   --max-tokens 384   --timeout 300
```

Die CLI startet nacheinander DFlash und APC, testet echte
Streaming-Antworten (keine zweistellige OK-Antwort) und
stellt im `finally`-Block das anfängliche Profil wieder her.
Bei einer Unterbrechung wird soweit möglich ebenfalls zurückgeschaltet.
Während des Vergleichs nicht selbst chatten und keine Medienjobs starten.

Berichtet werden Ersttext-TTFT, Gesamtdauer und Antwortzeichenanzahl
pro Erstfrage, Folgefrage mit gleichem Kontext und neuer Kontextvariante.
Zusätzlich sind die Cache-Statistiken und die
Systemdiagnose (freie Prozent, Swap, Headroom, Speicherdruck)
vor und nach den Messungen enthalten.

Für größere Kontexte ist `--context-sizes 4000,8000` möglich.
Die Größe wird heuristisch über Zeichen generiert: **kein**
modellgenauer Tokenizer-Count. Die gemessene erste sichtbare
Antwort ist *inklusive* Queue/Prefill/Gateway, nicht nur
die native Model-TTFT. `max-tokens` begrenzt die Antwort,
die tatsächliche Tokenzahl kann darunter liegen.
Die Antwortqualität ist mitzuprüfen; das Experiment
beweist noch keine generelle Überlegenheit von APC.
Antwortinhalte und synthetische Prompts werden nicht gespeichert.

Optional einen privaten Report ohne Überschreiben bestehender Dateien
mit Rechten `0600` ablegen:

```bash
./scripts/mlx chat-profile compare   --context-sizes 4000 --samples 2 --max-tokens 384   --output /tmp/nobby-chat-profiles-compare-1.json
```

**Wichtige Speichergrenze:** `APC_NUM_BLOCKS=512` beschränkt
die Anzahl des Block-Pools, nicht den gesamten Unified-Memory-Verbrauch.
Ein Exact-Cache kann zusätzliche Modellelemente/KV-Snapshots halten;
`resident_bytes=0` beim Pool ist kein Beleg für 0 Byte.
Daher keine Aussage über "1 GB APC" oder gefahrlosen
Parallelbetrieb schwerer Medienjobs. Wie bisher gelten
die Nobby-RAM-Sicherheitsvorkehrungen und der exklusive
Modell-Lease.

## CPU-Regression ohne MLX-Inferenz

```bash
./test-venv/bin/python -m pytest -q   tests/test_chat_performance_profiles.py   tests/test_chat_experience_benchmark.py
bash -n scripts/mlx-server-start
bash -n scripts/mlx
```

Die Tests prüfen Profil-Werte, atomisches Schreiben, Statusabfrage,
Job-/Lease-Ablehnung, Revert bei fehlgeschlagenem Neustart,
SSE-Handling, längere Antworten und Cleanup auch bei
A/B-Benchmark-Fehlern. Die tatsächliche Inferenzzeit muss auf
dem Mac durch den Benutzer gemessen werden.
