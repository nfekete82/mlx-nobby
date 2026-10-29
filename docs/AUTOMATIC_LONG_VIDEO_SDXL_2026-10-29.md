# Automatische Langvideos und SDXL-Prozessreparatur

Stand: 2026-10-29. Basis: `523dd72c7b719fe5a3ff1bd12d1876a68b849b87`.
Branch: `feat/automatic-long-video-sdxl-reliability-20261029`.

## Tatsächlich umgesetzt

### SDXL und gemeinsame Prozessverwaltung

Der vorherige Code hatte zwei problematische Übergänge: `_ManagedPopen._retire`
entfernte die Prozessregistrierung allein aufgrund des Wächter-Exits; außerdem
eskalierte `terminate_record` nur bei weiterhin identitätsgleicher Wächter-PID
zu SIGKILL. Ein weiterlebendes Kind konnte dadurch entweder seine
Eigentumsnachweise verlieren oder nicht mehr eskaliert werden. `_stop_locked`
verkürzte den Fehler im Jobstatus auf den generischen SDXL-Text.

Der Wächter speichert nun atomar eine separate Kindprozessliste mit PID, PPID,
PGID, Zustand und Geburtsidentität. Auf macOS kommen Geburtszeit inklusive
Mikrosekunden, Eltern-PID, Gruppe und Zustand aus **einem** `proc_pidinfo`-Snapshot;
unter Linux aus einem `/proc/PID/stat`-Snapshot. Dadurch werden keine alten
`ps`-Gruppendaten mit der Geburtszeit einer zwischenzeitlich wiederverwendeten
PID kombiniert. Die gespeicherte Liste verfolgt auch nachweisbare Kinder in
einer anderen Gruppe.

Health betrachtet den Worker weiterhin als geladen und die Annahmesperre
schließt sofort, falls ein Wächter unerwartet endet und Kinder weiterleben.
Nach Wächterende bleiben Nachweise erhalten, solange lebende Gruppenmitglieder
oder identitätsgleiche Kinder existieren. SIGTERM und gegebenenfalls SIGKILL
werden an einzeln geburtsverifizierte Prozesse gesendet. Dafür muss der Wächter
nicht mehr leben. Unbekannte Gruppenmitglieder erhalten keine Signale und
verhindern eine Erfolgsmeldung. Zombies gelten als beendet; eigene direkte
Kinder werden mit `poll`/`wait` gereapt.

Pro Registrierung serialisiert ein `flock` die Bereinigung von Workerthread,
Idle-Timer und Lifecycle-Controller. Nichtblockierende Retirement-Prüfungen
verhindern rekursives Warten. JSON-Dateien werden erst nach Verifikation einer
inaktiven Gruppe entfernt. Leere Altregistrierungen, einschließlich `owner=None`,
werden beim SDXL-Start sicher bereinigt; defekte oder nicht verifizierbare
Registrierungen sperren die Jobannahme. Die kleinen `.cleanup.lock`-Dateien
bleiben als stabile Synchronisationspunkte erhalten, damit wartende Threads
nicht verschiedene Lock-Inodes verwenden.

Neue SDXL-Worker erhalten `owner="image:sdxl"`. Cleanup-Phasen werden gespeichert;
Fehler enthalten Ursache/Exception-Chain, PID, PGID, Owner, Anfangszustand,
Eskalationsphase und Restprozesse. Strukturierte Prozessdiagnostik enthält keine
CLI-Argumente, Prompts oder Medieninhalte. Die vorhandene SDXL-Freigabe innerhalb
von `image_runtime` bleibt vor Chat-Restore und Lease-Freigabe. Ein nicht
verifiziertes Cleanup schließt zusätzlich die globale Annahmesperre.

Modellgewichte, Qualitätsprofile, MPS-Watermarks und Speicherschwellen wurden
nicht geändert.

### Einordnung des gemeldeten Produktionsfehlers

Der gemeldete Fall mit Wächter 65958, Kind 65961, PGID 65958 und zurückgelassener
Registrierung wird durch isolierte Tests nachgestellt. Die ursprüngliche
vollständige Exception lässt sich aus dem generischen alten Jobtext allein
nicht rückwirkend beweisen. In der hier zugänglichen lesenden Live-Diagnose war
die Annahmesperre geschlossen, die Prozessregistry leer und 8030/8060 nicht
erreichbar. Es wurde weder ein Live-Worker beendet noch ein GPU-Render gestartet.
Die neue Diagnostik erhält die Exception-Chain bei einer erneuten realen Störung.

`scripts/diagnose-managed-processes.py` zeigt ausschließlich Prozessmetadaten.
`--cleanup-stale` entfernt nur nachweislich inaktive Registrierungen und sendet
keine Signale. Unbekannte aktive Gruppen bleiben unverändert.

### Automatische Langvideos im normalen Videojob

Die Orchestrierung läuft im vorhandenen nativen Video-Service, unter dessen
bestehendem Joblock und **einer** `video_runtime`-Lease. Es entstehen weder ein
zweiter Jobmanager noch Agent-Service-Rückaufrufe auf eine selbst gehaltene
Ressource. Der erste Abschnitt verwendet die bestehende Generierung; deren
warmer MLX-Worker wird vor der separaten Extend-CLI beendet.

Die normale Chat-Auswahl bietet nun 5/10/20/30 Sekunden auch mit dem vorhandenen
1080p-Profil. Bisherige 6-/8-Sekunden-Optionen für kleinere Profile und die
Vorschau bleiben erhalten. Defaults bleiben unverändert. Explizite Angaben wie
„20 Sekunden, maximale Qualität“ werden berücksichtigt und im Qualitätsdialog
sichtbar. 60 Sekunden sind nicht freigegeben.

Der Planner verwendet die bisherigen direkten Profillimits, 24 fps, `8k+1`
Pixelframes und höchstens zwölf zusätzliche latente Frames je Extend. Beispiele:

| Gewünschte Timeline bei 1080p | Geplante Abschnitte | Kumulative Frames |
| --- | --- | --- |
| 5 s | Initial 5 s | 121 |
| 10 s | Initial 5 s, Extend +4 s, +1 s | 121, 217, 241 |
| 20 s | Initial 5 s, Extend +4 s, +4 s, +4 s, +3 s | 121, 217, 313, 409, 481 |
| 30 s | Initial 5 s, sechs Extend à 4 s, abschließend +1 s | 121 bis 721 |

Das vorhandene „1080p“-LTX-Profil bleibt **1920×1088**, beziehungsweise dessen
Hochformat. Das 64-Pixel-Raster wird nicht durch heimliches Verkleinern aufgelöst.
Bei 720p sind bis zehn, bei 540p bis zwanzig Sekunden weiterhin direkt möglich;
längere reguläre Anfragen nutzen denselben Planner. Automatische Fortsetzung
ist auf den nativen LTX-MLX-Standardpfad beschränkt. Bestehende Multi-Image-
Keyframe-/Szenenaufträge bleiben bei ihren direkten Grenzen und ihrem eigenen
vorhandenen Szenenablauf. Uncensored-LoRAs werden nicht stillschweigend während
einer Fortsetzung weggelassen; entsprechende Langvideoanfragen werden abgelehnt.

### Verifizierte Semantik der installierten CLI

Gelesen wurde das installierte 0.18-Checkout
`b82b97e3d000e01361f8cfcb745244b15b89a521`, insbesondere
`ExtendDistilledPipeline.extend_from_video`, die CLI und deren Decoderpfad.
`extend --distilled --direction after` verwendet den Quellclip als zeitliche
Bedingung, trägt dessen letzte 25 Pixelframes und passende Audiotokens in das
neue Fenster und gibt anschließend **den gesamten verlängerten Clip** zurück.
Die bereits getragenen Video-/Audiotokens werden beim Anfügen verworfen.

Die Implementierung verwendet deshalb kein nachträgliches Concatenation und
fügt den Quellclip nicht erneut an. Jeder Aufruf übernimmt Prompt, Modell,
Auflösung, Seitenverhältnis und Framerate. Vor jedem Extend werden die
vorhandenen Memory-Guards geprüft; währenddessen laufen die unveränderten
aktiven RAM-/Swap-Grenzen weiter.

Wichtig: Diese CLI kodiert auch den bisherigen Clip erneut durch VAE und
MP4-Encoder. Die Anwendung fügt keine zusätzliche Videokompression hinzu;
verlustfreie beziehungsweise perfekte Bild-/Audiokontinuität kann damit aber
nicht versprochen werden. Die UI zeigt diese Einschränkung ausdrücklich.

### Checkpoints, Prüfung und Veröffentlichung

Nach jedem Abschnitt prüft FFprobe tatsächlich Framezahl, Framerate,
Abmessungen, Videodauer, maximal eine Audiospur sowie Audioformat und
Audio-/Videolänge. Zwei Übergangsframes werden mit FFmpeg/Framemd5 untersucht.
Identische Übergangsframes führen zu einem Hinweis, da Stillstand auch
beabsichtigt sein kann; das ist kein behaupteter semantischer Qualitätstest.

Die Timeline ist `(Frames - 1) / 24`. Ein Clip mit 481 Frames hat daher die
gewünschte 20-Sekunden-Timeline und etwa **20,0417 Sekunden** Containerdauer.
Genau dieser zusätzliche Frame wird verifiziert und als `actual_duration`
ausgewiesen. Abweichungen von der geplanten Framezahl werden nicht akzeptiert.

Ein atomarer Checkpoint enthält effektive Parameter, Runtime-SHA, Modell-ID,
Config-SHA, Gewichtsdatei-Metadaten, gegebenenfalls First-Frame-SHA sowie
Frameinformationen und SHA256 jedes validierten Zwischenvideos. Die Clips
liegen unter `video-jobs/long/JOB_ID/`, außerhalb der Medienbibliothek.
Nur der vollständig validierte letzte Clip wird atomar als kanonisches MP4
veröffentlicht. Es werden keine Originalmedien überschrieben.

Ein expliziter Retry kopiert und validiert sichere Checkpoints; fertige
Abschnitte werden nicht erneut mit dem Modell berechnet. Änderungen oder
Beschädigungen führen zu einer konkreten Ablehnung. Beim Service-Neustart
werden aktive Aufträge unterbrochen markiert und Manifeststände wiedergefunden,
auch wenn die letzte Jobstatus-Aktualisierung nicht mehr geschrieben wurde.
Es gibt keine automatische GPU-Wiederaufnahme. Ein Systemstopp bleibt als
unterbrochener, manuell fortsetzbarer Auftrag erkennbar; ein expliziter
Benutzerabbruch startet keine Fortsetzung.

Die vorhandenen Chat-Poller erhalten Planung, Abschnittsnummer, bestätigte
Videodauer, Teilphasenfortschritt, Laufzeit, letzte Aktivität, Retry und Cancel.
Browser-Reload bleibt beim selben aktiven Backendjob. Ohne bestätigte Schritte
erscheint ein indeterminierter Fortschritt. CLI-Ausgabe und Medienprüfungen
laufen cancellable; stilles stdout blockiert den Abbruch nicht. Nach Cancel
bleiben sichere Checkpoints erhalten, unvollständige Stufen werden entfernt.

### Zusätzliche Queue-Reparaturen

Bildgenerierung benötigt einen ausgefallenen Videodienst nur dann nicht mehr,
wenn dessen eigenes launchd-Label nachweislich fehlt, Port 8060 frei ist und
keine zugehörigen aktiven registrierten Prozesse nachweisbar sind. Unbekannte
Zustände bleiben gesperrt. Eine geschlossene globale Lifecycle-Sperre wird
dadurch nicht aufgehoben.

Bei HTTP 409/503 bleiben sicher redigierter Fehlergrund, Dispatch-/Retry-Zähler,
Wartebeginn, Wartezeit und nächste Retry-Zeit persistent und in Chat/Jobs-Panel
sichtbar. Ein wartender Videodienst wird konkret benannt. Die Tests verwenden
eigene Queue-Modulzustände, damit ein aus anderen Regressionen noch laufender
Scheduler die Dispatch-Zähler nicht verfälscht.

## Automatisierte Prüfung

Ergebnis des finalen kombinierten Laufs: **689 Backendtests** und **170 Subtests**
bestanden, dazu **369 JavaScript-Tests**. Die letzte gezielte Cleanup-/Video-
Regression umfasste 215 bestandene Tests und 52 Subtests.

Die exakten Suites und Ergebnisse stehen in
[`automatic-long-video-validation.json`](automatic-long-video-validation.json).
Alle Modelle sind gemockt. FFmpeg/FFprobe verarbeiten nur kleine synthetische
64×64-Clips. Die isolierten Prozessprüfungen benötigen `ps`/`proc_pidinfo` und
liefen außerhalb der Sandbox; sie signalisieren ausschließlich selbst
gestartete Testprozesse. Kein produktiver Shutdown, Reboot oder GPU-Render
wurde ausgeführt. Die bekannte Starlette/httpx-TestClient-Deprecation bleibt
eine Testwarnung.

```sh
./scripts/test-tiers.sh quick tests/test_managed_orphans.py \
  tests/test_sdxl_memory_safety.py tests/test_video_long.py \
  tests/test_queue_service_reliability.py
node --test tests/test_video_job.mjs tests/test_media_quality.mjs
node --test tests/*.mjs
```

Die Regression umfasst außerdem die bisherigen Lifecycle-, SDXL-, Talking-
Photo-, Shorts-, Multi-Image-, Edit-, Agent-, Speech-, Queue- und Runtime-Suites.
Fehler während der Entwicklung betrafen die neue Fail-closed-Erwartung bei
ungültigen Identitäten, alte Dauer-/Cache-Erwartungen und einen nicht isolierten
Test-Scheduler; diese wurden gezielt korrigiert.

## Installation: vollständiger Rebuild erforderlich

Python-Code von Agent, Bild- und Videodienst sowie Frontend-Assets wurden
geändert. Ein reiner Browser-Reload reicht nicht. Nach regulärem Abschluss
vorhandener Altaufträge auf dem Mac ausführen:

```sh
cd ~/mlx-web
git fetch origin feat/automatic-long-video-sdxl-reliability-20261029
git switch feat/automatic-long-video-sdxl-reliability-20261029
./scripts/mlx agent restart
./scripts/rebuild-all.sh
curl -fsS http://127.0.0.1:8010/api/system/lifecycle
curl -fsS http://127.0.0.1:8030/health
curl -fsS http://127.0.0.1:8060/health
```

Die bestehende sichere Git-Synchronisierung bleibt erhalten. Main wird nicht
automatisch mit diesem Branch gemergt. Vorhandene lokale Labor-/Benchmark-
Dateien gehören nicht zum Commit. Modellgewichte müssen nicht neu installiert
werden.

## Gezielte manuelle Abnahme auf dem Mac

Diese Befehle wurden **nicht** gegen produktive Dienste ausgeführt. Zunächst
prüfen, dass keine anderen Aufträge aktiv sind; Bild- und Videoabnahme
nacheinander durchführen. Ein Render gilt erst nach Terminalstatus und Sicht- /
Audioprüfung als reale Modellvalidierung.

Nur lesende Prozessdiagnose:

```sh
./test-venv/bin/python scripts/diagnose-managed-processes.py
```

Optional ausschließlich verifiziert leere Altregistrierungen entfernen:

```sh
./test-venv/bin/python scripts/diagnose-managed-processes.py --cleanup-stale
```

Kontrollierter Juggernaut-Test über die existierende native Jobs-API:

```sh
image_job_id="$(curl -fsS http://127.0.0.1:8030/jobs \
  -H 'Content-Type: application/json' \
  --data '{"operation":"generate","chat_id":"manual-sdxl-acceptance","chat_revision":0,"payload":{"model":"juggernaut-xl","prompt":"A ceramic cup on a wooden table in soft daylight","quality":"standard","width":512,"height":512,"seed":42}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
curl -fsS "http://127.0.0.1:8030/jobs/$image_job_id"
```

Status bis `completed`/`failed` abfragen. Nach Erfolg die Prozessdiagnose erneut
ausführen: kein lebender SDXL-Worker und keine aktive SDXL-Registrierung dürfen
zurückbleiben. Bei Fehlern muss die Ursache einschließlich PID/PGID sichtbar sein;
kein gewaltsames Freigeben der Sperre vor Verifikation. Den tatsächlichen
GPU-Test mit Parametern, Laufzeit, Qualität und Befund anschließend in der
Bildmodell-Testmatrix dokumentieren.

Kontrollierter 20-Sekunden-/1080p-Test:

```sh
long_job_id="$(curl -fsS http://127.0.0.1:8060/jobs \
  -H 'Content-Type: application/json' \
  --data '{"operation":"t2v","chat_id":"manual-long-acceptance","chat_revision":0,"payload":{"prompt":"A realistic continuous camera flight over a futuristic city at sunset","quality":"quality","duration":20,"seed":42}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
curl -fsS "http://127.0.0.1:8060/jobs/$long_job_id"
```

Erwartet: fünf geplante Abschnitte, bestätigte Dauer bis 20 Sekunden, 481 Frames,
24 fps, 1920×1088 und genau ein finales Bibliotheksvideo. `actual_duration`
berücksichtigt den zusätzlichen Frame. Auf demselben Weg 5/10/30 Sekunden
auswählen; 5 Sekunden dürfen keinen Extend starten. Im Chat zusätzlich Reload,
Cancel und manuelles Fortsetzen eines absichtlich unterbrochenen Auftrags prüfen.

Cancel eines noch aktiven nativen Abnahmejobs:

```sh
curl -fsS -X POST "http://127.0.0.1:8060/jobs/$long_job_id/cancel" \
  -H 'Content-Type: application/json' --data '{}'
curl -fsS "http://127.0.0.1:8060/jobs/$long_job_id"
./test-venv/bin/python scripts/diagnose-managed-processes.py
```

Ein HTTP 200 allein ist kein Abbruchnachweis. Status und Prozessende müssen
bestätigt sein. Sichere Checkpoints bleiben erhalten, ein expliziter Abbruch
wird nicht automatisch fortgesetzt.

## Noch nicht real validiert

**Es gibt keine Erfolgsaussage über echte 1080p-Langvideoqualität.** Nicht real
geprüft sind Metal-Spitzen bei wiederholter Quellclip-Kodierung, sichtbare
Kamera-/Szenenkontinuität, Audioübergänge, wiederholte VAE-/MP4-Verluste und
Renderzeiten für 10/20/30 Sekunden. Der installierte vollständige Re-Encode
kann trotz kleinem Extend-Fenster mit wachsender Quelllänge mehr Speicher
benötigen; Guards und Checkpoints ersetzen keine echte 48-GB-Abnahme.

Auch der produktive SDXL-Wiederholungsfehler, ein echter Docker-/launchd-Rebuild
und das Layout auf realen Desktop-/Mobilbrowsern benötigen noch bewusste
Abnahme. 60 Sekunden bleiben deshalb nicht auswählbar. Unbeweisbare Prozesse
werden weiterhin nicht auf Verdacht beendet.
