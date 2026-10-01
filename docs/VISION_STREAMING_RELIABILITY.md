# Vision streaming reliability

## Root Cause

Der Reliability-Gateway wartete für Text- und Bildnachrichten identisch
`MLX_CHAT_FIRST_BYTE_TIMEOUT` (Standard 30 s) auf den ersten Upstream-SSE-Chunk.
Nur aktive Bild-/Video-Generierungsleases erhielten das längere Media-Budget.
Vision-Inferenz läuft als Chat und erhielt diese Verlängerung nicht.

Der vorhandene Vision-Pfad in `backend/app.py` sendet `stream: false` und liest
den vollständigen Response, bevor er Inhalt als SSE ausgibt. Der Watchdog sieht
also nicht das erste Modelltoken, sondern erst die fertige Antwort. Synchrone
Context-/Routing-HTTP-Aufrufe in der Gateway-Factory konnten außerdem den
Event-Loop der Reliability-Schicht blockieren. Ein erster Metadaten-Chunk
wechselte bisher bereits zum normalen 45-s-Stall-Watchdog.

Der gemeldete direkte VLM-Test war erfolgreich (`mlx_vlm`, `images=1`):

| Messung | Wert |
| --- | ---: |
| Prompt-Tokens | 16193 |
| Prefill | 20.714 s |
| Time to first token | 21.869 s |
| Gesamtdauer | 24.967 s |

Dieser einzelne Lauf liegt unter 30 s und beweist allein keinen Timeout.
Die Codeanalyse erklärt jedoch die geringe Reserve für längere Prefills,
Gateway-Vorbereitung und Generierung sowie die gemeldete Recovery-Ursache
`chat_first_byte_timeout`. Modell und Vision-Routing wurden nicht geändert.

## Before / After

| Verhalten | Vorher | Nachher |
| --- | --- | --- |
| Textchat bis erster Gateway-Chunk | 30 s | Unverändert 30 s |
| Vision bis Assistant-Ausgabe | 30 s bis irgendeinem Chunk | Absolutes Budget von 60 s bis Inhalt/Reasoning oder Fehler |
| Vision während langer Vorbereitung/Prefill | Keine eigenen Heartbeats | Sofortiger SSE-Kommentar, dann alle 5 s bei ausstehenden Reads |
| Sources/Metrics vor Vision-Inhalt | Wechsel zu 45-s-Stall-Timeout | Restliches absolutes Vision-Budget; kein Reset |
| Vision-Gateway-Vorbereitung | Synchron im Event-Loop | Worker-Thread innerhalb des Vision-Budgets |
| Stall nach Assistant-Ausgabe | 45 s | Unverändert 45 s |
| Tote Runtime ohne Upstream-Chunk | Recovery und maximal ein Retry | Dasselbe, für Vision nach 60 s |
| Vision mit endlosen Metadaten | Transport konnte Stall-Erkennung verhindern | Absolute Inhaltsfrist löst Recovery/Fehler aus |
| Stream endet ohne Antwort | Sichtbarer Fehler | Unverändert; Heartbeats gelten nicht als Antwort |

Heartbeats sind SSE-Kommentare (`: vision request pending`), enthalten keine
Bilddaten und keine behaupteten Fortschrittsprozente. Sie halten den Transport
aktiv, setzen aber **keinen** Watchdog zurück. Der Frontend-SSE-Parser ignoriert
sie für Assistant-Inhalt, Sources und Modellmetriken. Sie beeinflussen weder
Tokenzählung noch Modell-TTFT. Der browserseitige Verzögerungshinweis orientiert
sich weiterhin am ersten Transport-Chunk und kann dadurch früher verschwinden;
der serverseitige Inhalts-Watchdog bleibt aktiv.

Bildnachrichten werden anhand gültiger `image_url`-Blöcke in allen übermittelten
Nachrichten erkannt, auch in der History. String-URLs und Objekte mit `url`
werden unterstützt. Eine URL im gewöhnlichen Text aktiviert das Budget nicht.

Aktive Image-/Video-Leases behalten das vorhandene Media-Wartebudget
(Standard 300 s) und den Recovery-Schutz. Vor dem ersten Upstream-Chunk wird
höchstens einmal Recovery angefordert und nach Bereitschaft mit neuer Agent-PID
wiederholt. Nach bereits weitergereichten Upstream-Chunks gibt es keinen Replay;
ein Stall erzeugt eine Recovery-Anforderung und einen sichtbaren SSE-Fehler.
Recovery-Cooldown und Lease-Prüfungen des Agenten bleiben unverändert.

Disconnect und Timeout schließen den Async-Iterator und canceln ausstehende
Reads. Laufende synchrone HTTP-Aufrufe in Worker-Threads können dadurch nicht
aktiv abgebrochen werden; deren bestehende HTTP-Timeouts gelten weiterhin.

## Konfiguration und Prüfung

`MLX_CHAT_VISION_FIRST_BYTE_TIMEOUT` wird vom Webprozess gelesen, Standard
`60`, mindestens `MLX_CHAT_FIRST_BYTE_TIMEOUT`. Docker Compose reicht den Wert
aus der Umgebung oder `.env` weiter. Ein Neustart bzw. Rebuild des Webcontainers
ist nötig, damit geänderter Code und Konfiguration wirksam werden.

Gezielte Regressionen verwenden künstlich verkürzte Fristen und Fake-Streams;
sie benötigen keine Modelle:

```sh
agent-venv/bin/python -m pytest -q tests/test_runtime_reliability.py tests/test_vision_empty_response_reliability.py
node --test tests/test_runtime_reliability_ui.mjs tests/test_sse_stream.mjs
```

Die Tests prüfen unverändertes Text-Recovery, Vision-Prefill über Text-/Stall-
Fristen, frühe und wiederkehrende Heartbeats, vorbereitende synchrone Arbeit,
Recovery trotz Heartbeats, endlose Metadaten, normalen Stall nach Ausgabe,
Disconnect-Cleanup, Bilder in der History und weiterhin sichtbare Leerantworten.
Der Frontend-Test verarbeitet Heartbeats zusammen mit beliebig fragmentierten
Sources-, Reasoning-, Content-, Metrics- und Done-Events.

Ein neuer Live-VLM-Lauf wurde für diese Änderung nicht ausgeführt; die oben
aufgeführten Modellmesswerte stammen aus dem gemeldeten Befund.
