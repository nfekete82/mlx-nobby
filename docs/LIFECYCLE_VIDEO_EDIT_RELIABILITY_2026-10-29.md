# Lifecycle und Video-Editor: Implementierung und Validierung, 2026-10-29

Branch: `fix/mlx-lifecycle-video-edit-reliability-20261029`.

## Verhalten und Architektur

Die bestehenden Jobverwaltungen bleiben maßgeblich. `ai_lifecycle_gate.py`
ergänzt eine persistente, prozessübergreifende Annahmesperre mit `flock` und
atomaren Zustandsdateien. Ein sofort sichtbarer Shutdown-Marker verhindert
weitere Ausführung, während bereits begonnene Registrierungen abgeschlossen
und anschließend vom Shutdown erfasst werden. Ein Fehler lässt die Sperre
geschlossen. Die Speicherprüfung beim launchd-Modellstart bleibt möglich;
Benutzeraufträge werden erst nach vollständiger Shutdown-Verifikation und
erfolgreichen API-Prüfungen wieder zugelassen.

`agent/ai_lifecycle.py` verbindet tatsächliche vorhandene Schnittstellen:

| Workload | Abbruch / Kontrolle | Verifikation und persistenter Zustand |
| --- | --- | --- |
| Extend und Retake | Bestehende Edit-Registry, Cancel-Event; bewachte eigene Prozessgruppe | Prozessende, Gruppenende, Worker und Generierungslock; atomare Jobdateien |
| Video über 8060 | `media_queue.cancel`, vorhandene native Cancel-Route und Video-Lifespan | launchd, Port, erfasste Prozessidentitäten und Agent-Queue |
| LTX-CLI und warmer Video-Worker | Gemeinsamer Prozesswächter und persistente Prozessidentitäten | Gruppenende; Runtime-Dateien werden beim Reaping entfernt |
| Talking Photo, inklusive Longform | `talking_photo.cancel_job`, vorhandene Prüfungen an Phasengrenzen; LTX-Prozesswächter | Workerende, persistente Talking-Photo-Jobs, Originale bleiben erhalten |
| Bilder, SDXL-Warmworker, MFLUX und Upscale | Agent-Medienqueue, native Cancellation und Lifespan; bewachte Providerprozesse | Prozessidentitäten, Dienst und Port; bestehende Queue-Persistenz |
| Speech / ASR / TTS | Kein erfundener Cancel-Endpunkt: laufende Requests enden durch kontrollierten Dienststopp | Nur exakte eigene launchd-Prozessbäume und Port 8050 |
| Shorts und Batch | `cancel_short_job`, bestehende Batch-Persistenz; Cancellation bleibt bei verspäteten Antworten terminal | Vorhandene Worker müssen ihre Ressourcen freigeben |
| Agent und Chatstream | Vorhandene RunContext-Cancellation und Stream-Events; Runtime-Lease prüft Shutdown | Agent-Ausführung und Streamworker müssen enden; Inferenzdienst wird gestoppt |
| Router, Embeddings und MLX-Serve | Exakte launchd-Labels, Annahmesperre an nativen Service-APIs / Agent-Proxy | API-/Modelldiscovery-Prüfungen vor Freigabe; Ports 8040, 8020 und 11234 |
| Dokumentindex und weitere Runtime-Lease-Nutzer | Gemeinsame Runtime-Sperre; Embedding-Inferenz wird gesperrt | Indexworker / eigene Dienste werden mit überprüft |

Der Prozesswächter läuft in einer eigenen Session und startet das Modell erst
nach persistierter Registrierung. Ein separates Kontrollrohr lässt stdin und
stdout der bestehenden Workerprotokolle unverändert. EOF bei Elternprozessende
löst SIGTERM aus, danach folgt bei Bedarf SIGKILL. Der Wächter bleibt bis zur
Gruppenbereinigung Gruppenführer. PID, Startidentität und zufälliges Token
werden geprüft; fremde oder wiederverwendete PIDs erhalten keine Signale.
Prozess- und Gruppenende werden begrenzt abgewartet. Ein fehlgeschlagenes
Cleanup wird als konkreter Jobfehler sichtbar und sperrt weitere KI-Aufträge.

Für ältere, noch unbewachte LTX-Prozesse berücksichtigt der Shutdown zusätzlich
die nachweisbare Abstammung vom aktuellen Nobby-Agenten und den exakten lokalen
CLI-/Runnerpfad. Eine gleiche CLI in einem fremden Terminal reicht nicht aus.
Globale Python-Kills oder unselektierte Prozessnamensuchen werden nicht ergänzt.

Terminal und HTTP verwenden denselben Ablauf. Ein zusätzlicher Operationslock
serialisiert komplette Stop-/Rebuild-/Restart-Sequenzen einschließlich der
verschachtelten Manageraufrufe. `mlx stop-ai` lässt Agent und Webanwendung
online. Ein Rebuild stoppt und verifiziert zuerst, synchronisiert danach mit
dem bestehenden sicheren Git-Verfahren, baut das Webimage, lädt den Agenten
neu und startet die Dienste. Die Sperre bleibt über den Agent-Neustart bestehen.
Der Menütext lautet jetzt „MLX-Nobby neu aufbauen“; es erfolgt kein macOS-Reboot.

## Tatsächlicher Video-Fortschritt und Wiederherstellung

Das installierte LTX-MLX-0.18-Checkout wurde ausschließlich gelesen:
`b82b97e3d000e01361f8cfcb745244b15b89a521`, lokaler Q4-Modellpfad wie bisher.
Relevante Quellen: `ltx_pipelines_mlx/cli.py` (`_cmd_extend`, Retake und
`_decode_and_save`), `utils/samplers.py` (tqdm-Beschreibungen),
`utils/progress.py` und `_base.py` (geklammerte Phasenmeldungen).

Die Auswertung verarbeitet unter anderem `Denoising (guided): ... | 2/8 ...`,
Carriage-Returns, geteilte Records und `[Decoding video + audio + muxing] ...`.
Ein begrenzter Dateitailer liest höchstens 64 KiB pro Aufruf; der Textrest ist
auf 8 KiB begrenzt, das aktive Log wird regelmäßig bei 4 MiB zurückgesetzt.
Die Cancellation-Schleife wartet niemals auf stdout oder einen Zeilenumbruch.
`PYTHONUNBUFFERED=1` reduziert Pufferungsverzögerungen.

`progress` ist während der Bearbeitung `null`, nach Erfolg `1.0`.
`phase_progress`, `current_step`, `total_steps` und `progress_scope="phase"`
beschreiben ausschließlich bestätigten Teilphasenfortschritt. Die vorherige
Oberfläche konsumierte den numerischen `progress`-Wert nicht; bestehende IDs,
Statusrouten und Ergebnisfelder bleiben erhalten. Unbekannte Ausgabe erzeugt
keinen Prozentwert, aktualisiert aber `last_activity_at`. Start-, Aktualisierungs-
und Endzeit werden persistiert. Das Frontend zeigt Laufzeit und letzte Aktivität
auch bei indeterminiertem Fortschritt.

Aktive Edit-Jobs lassen sich serverseitig auflisten. Lokal wird nur eine
versionierte Jobreferenz gespeichert. Backend-Discovery funktioniert auch bei
fehlendem, beschädigtem oder gesperrtem Browserstorage. Ein während des Reloads
fertiggestellter Auftrag wird über die gemerkte ID wiedergefunden. Andere Tabs
verwenden dieselbe Backend-Registry; der serverseitige Generierungslock und die
Frontend-Startsperre verhindern gleichzeitige doppelte Starts.

„Schließen“ lässt den Auftrag weiterlaufen. Ein ständig erreichbarer
Video-Editor-Button öffnet ihn erneut. „Bearbeitung abbrechen“ zeigt sofort die
Anforderung, deaktiviert doppelte Anfragen und pollt bis zum Terminalstatus.
Ein HTTP 200 allein wird nicht als erfolgreicher Abbruch interpretiert.
Netzwerkfehler erlauben einen erneuten Versuch. Veraltete Polling-Antworten
werden nach einem Abbruch oder Wiederverbinden ignoriert. Requests haben ein
Zeitlimit. Deutsche und englische Texte, Tastaturfokus und responsive Darstellung
sind integriert.

Unfertige Edits liegen unter einem vom Bibliotheksscan ausgeschlossenen
Dateinamen. Erst nach erfolgreichem Prozessende und der letzten synchronisierten
Cancel-Prüfung wird das Ergebnis atomar zum kanonischen Video veröffentlicht.
Originale und abgeschlossene Ergebnisse werden beim Abbruch nicht gelöscht.
Unterbrochene Jobdateien werden beim Agent-Neustart dauerhaft als fehlgeschlagen
markiert; ihre eigenen Prozessgruppen werden vorher bereinigt.

## Automatisierte Prüfung

Alle Läufe verwendeten das vorhandene `test-venv`, temporäre Homes/Zustandsdateien,
Mocks und ausdrücklich gestartete CPU-Testprozesse. Es wurde kein produktiver
Dienst gestoppt, kein Docker-Neustart ausgeführt und kein GPU-Modell geladen.
Die Prozessprüfungen benötigen Zugriff auf `ps`, der in der Ausführungssandbox
gesperrt war; sie liefen außerhalb dieser Sandbox mit demselben isolierten
Testaufbau. Es wurden ausschließlich eigene Testprozesse signalisiert.

Ergebnis: **64 gezielte Backendtests**, **648 Backend-Regressionstests** mit
170 bestandenen Subtests und **369 JavaScript-Tests** bestanden. Darin enthalten
sind fünf gezielte Verhaltenstests für den Video-Editor.

Die genauen Suite-Dateien und Ergebnisse stehen in
[`lifecycle-video-edit-validation.json`](lifecycle-video-edit-validation.json).

Gezielt reproduzierbar:

```sh
./scripts/test-tiers.sh quick tests/test_ai_lifecycle_reliability.py \
  tests/test_video_edit_ltx018.py tests/test_system_lifecycle.py \
  tests/test_lifecycle_status.py
node --test tests/test_video_edit_recovery.mjs
node --test tests/*.mjs
```

Die zusätzliche Backend-Regression umfasst Runtime-Koordination, Speicherbudget,
Bildprovider und Warmworker, Video, Talking Photo, Medienqueue, Shorts, Agent,
ModelProvider, Berechtigungen, Service-Bridges, Speech und Medien-Lifecycle.
Python-Kompilierung, JavaScript-Syntax, Shell-Syntax und `git diff --check`
werden ebenfalls geprüft. Die einzige bekannte Testwarnung betrifft die
vorhandene Starlette/httpx-TestClient-Deprecation.

## Betriebsgrenzen und noch nötige reale Prüfung

- Keine GPU-Renderqualität, Renderzeit, Metal-Speicherfreigabe oder echte
  launchd-/Docker-Neustartsequenz wurde auf dem produktiven M5 Max getestet.
  Erforderlich sind reale Extend-/Retake-Läufe, Abbruch während Laden und
  Generierung, warmer LTX-/Bildworker, Speech und anschließender vollständiger
  Rebuild in einem bewusst gewählten Wartungsfenster.
- CPU-Ausgaben simulieren das gelesene CLI-Format. Eine spätere Änderung des
  LTX-Logformats fällt auf indeterminierten Fortschritt zurück. Die Prozentwerte
  sind absichtlich niemals ein geschätzter Gesamtfortschritt.
- Direkte Terminalaktionen benötigen den aktualisierten Kontroll-Agenten.
  Ist er nicht erreichbar, scheitert der Ablauf ausdrücklich und hält die
  Annahmesperre geschlossen. Ein späterer erfolgreicher `restart-all` hebt sie
  nach Verifikation wieder auf.
- Bereits vor diesem Update verwaiste, nicht mehr zuordenbare Fremd-/Legacy-
  Prozesse werden nicht durch Vermutungen beendet. Für die einmalige Einführung
  den bisherigen Agenten erst aktualisieren, wenn vorhandene Altaufträge regulär
  beendet sind. Neu gestartete verwaltete Provider verwenden den Wächter.
- Ein Kernel-/Treiberproblem kann SIGKILL verzögern. Das wird als Fehler
  behandelt; ein erfolgreicher Shutdown wird dann nicht gemeldet.

## Installation auf dem Mac

Diese Befehle sind für die manuelle Ausführung nach Abschluss der Altaufträge
gedacht. Sie wurden im Rahmen dieser Tests nicht gegen die laufenden Dienste
ausgeführt. Es sind keine neuen Python-Abhängigkeiten erforderlich.

```sh
cd ~/mlx-web
git fetch origin fix/mlx-lifecycle-video-edit-reliability-20261029
git switch fix/mlx-lifecycle-video-edit-reliability-20261029
./scripts/mlx agent restart
./scripts/rebuild-all.sh
curl -fsS http://127.0.0.1:8010/api/system/lifecycle
curl -fsS http://127.0.0.1:8090/api/version
```

`rebuild-all.sh` schreibt nach `/tmp/mlx-nobby-rebuild.log`. Bei einem Fehler
bleibt die Jobannahme gesperrt. Nach Behebung der gemeldeten Ursache kann derselbe
Befehl erneut ausgeführt werden. Die vorhandene Git-Synchronisierung erhält
lokale Änderungen; es gibt keinen Force-Push und keinen automatischen Main-Merge.

## Geänderte Dateien

Die vollständige Dateiliste steht im Validierungs-JSON. Die zentralen Änderungen
liegen in `ai_lifecycle_gate.py`, `managed_process.py`, `agent/process_guard.py`,
`agent/ai_lifecycle.py`, `agent/video_edit_routes.py`, `agent/app.py`,
`frontend/assets/chat/video-edit.js` und den Lifecycle-Shellscripts. Die übrigen
Dateien verbinden vorhandene Queues, native Services, Proxies, Übersetzungen und
Tests mit diesen Mechanismen. Vorhandene ungetrackte Labor-/Benchmarkdateien
gehören ausdrücklich nicht zum Commit.
