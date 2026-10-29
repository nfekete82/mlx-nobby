# MLX-Nobby – Stabilitäts-, Qualitäts- und Performance-Audit

Datum: **2026-10-29**. Branch: `fix/mlx-nobby-full-stability-audit-20261029`.
Ausgangscommit: `a71f595382d75f7bb3f876f001a8e81a8c7b393f`.
Main bleibt auf `66615faaf2b27709a9c59e867f378cfbc13e32b3` unverändert.

## Ausgangszustand und Grenzen

Das getrackte Arbeitsverzeichnis war sauber. Die vorhandenen unversionierten
Labor-, Benchmark- und persönlichen Dateien wurden weder geändert noch in den
Commit aufgenommen. Die drei geschützten Benutzerkonfigurationen haben unveränderte SHA256-Werte;
alle 106 vorher erfassten unversionierten Pfade sind erhalten.
Es gab keine Modell-Downloads, Paketupdates, produktiven KI-Aufträge,
Dienstneustarts, Reboots oder automatisierte Installation der Änderungen.

Der lesende Live-Snapshot vom 2026-10-29, 19:47 UTC, zeigte:

| Dienst | Tatsächlicher Pfad / Port | Befund |
| --- | --- | --- |
| Chat | `/v1/models`, 8000 | HTTP 200, 13 Discovery-Einträge |
| Agent | `/api/system/lifecycle`, 8010 | erreichbar, letzter Lifecycle abgeschlossen |
| Embeddings | `/health`, 8020 | HTTP 200, ready |
| Images | `/health`, 8030 | ready, kein aktiver Job, nicht geladen |
| Router | `/v1/models`, 8040 | HTTP 200, 13 Discovery-Einträge |
| Speech | `/health`, 8050 | ok, keine aktive Generierung, nicht geladen |
| Video | `/health`, 8060 | ready, kein aktiver Job |
| Web / OrbStack | `/api/health`, 8090 | HTTP 200; bestehender Container lief weiter |
| MLX-Serve | `/v1/models`, 11234 | HTTP 200, drei Discovery-Einträge |

Der Agent hat keinen generischen `/health`-Pfad: dessen anfängliches 404 war
ein falscher Prüfpfad, kein ausgefallener Agent. Discovery ist kein GPU-Render-
oder Modellqualitätsnachweis. Die laufende Web-Installation meldete später
Version 1.19.0 / Commit `bf6db09e7dcd`; der neue Audit-Fix ist noch nicht aktiv.

Die Architektur verwendet neun projektbezogene geladene LaunchAgents inklusive
Embeddings-Probe, getrennte Python-Umgebungen und das Web-Image aus
`docker-compose.yml`. Embeddings und weitere MLX-Aufgaben nutzen MLX-Serve;
der Videodienst läuft aus der Image-Umgebung und nutzt die externe LTX-Runtime.
Der optionale MuseTalk-Dienst auf 8070 war konfiguriert, aber nicht geladen.
Andere lokale Anwendungen und Container gehören nicht zum Audit und wurden
nicht beeinflusst.

`docker compose config --quiet` bestand. Ein separater kurzlebiger Container
prüfte das vorhandene Web-Image ohne Netzwerk, veröffentlichte Ports oder
Host-Datenmounts, mit schreibgeschütztem Root-Dateisystem: Produktions-Webimports
und Video-Fehlerfilter funktionieren ohne installiertes Agent-Paket. Es wurde
kein neues Image gebaut und kein laufender Container ersetzt.

Alle sechs installierten Umgebungen bestanden `uv pip check`: Runtime, Agent,
Embeddings, Images, Speech und Tests. Die installierten Runtime-/Agent-/Speech-
Interpreter sind Python 3.13.13, Images/Embeddings 3.11.15. Bestehende Manifeste,
Quantisierungen, LoRAs und Sampling-Defaults wurden nicht verändert.

GitHub Actions wurde über lokale Workflows und den GitHub-Connector geprüft.
`Tests` und `Browser acceptance` laufen bei Main-Push oder Pull Request; für den
Ausgangscommit lieferte der Connector keine PR-Workflow-Läufe. Das ist keine
Remote-CI-Erfolgsaussage. Dieser Audit führt die Prüfungen lokal isoliert aus.

## Bestätigte Probleme und umgesetzte Korrekturen

Es wurde kein P0 bestätigt. Die folgenden P1/P2 sind durch isolierte Regressionen
reproduziert; das ist keine formale Sicherheits- oder Produktivzertifizierung.

| ID | Priorität | Problem | Tatsächlicher Fix |
| --- | --- | --- | --- |
| L1 | P1 | Resume entfernte die Pending-Datei eines anderen Shutdowns, der noch auf den Admission-Lock wartete. | Ein eigener Intent-Dateilock schützt den wartenden Shutdown. Resume erwirbt ihn nur ohne Warten und bleibt bei Konkurrenz gesperrt. Reentrante Fehlerpfade halten keine umgekehrte Locksperre; Thread- und Prozesskonkurrenz sind geprüft. |
| L2 | P1 | Ein Fehler bei der ersten oder späteren Wächter-Prozessprüfung ließ den gestarteten Modellprozess ohne Wächter zurück. | Der Fehlerpfad umfasst Start, erste Prüfung und Überwachung. Er beendet ausschließlich die eigene, noch durch den Wächter belegte Sitzung/Gruppe. Fremde Caller-Gruppen werden schon vor dem Start abgelehnt; Pipe und Selector schließen zuverlässig. |
| L3 | P1 | Service-Prozessnachweise nutzten sekundengenaue `ps`-Strings; Zombies konnten als lebend gelten. | Kernel-Geburtsidentität plus PID wird gespeichert und vor Signalen geprüft. Launchd-Label und Wurzelidentität werden vor/nach dem Scan bestätigt. Zombies erhalten keine Signale. Alte, lebende Nachweise ohne Geburtsidentität führen zu einer sichtbaren Sperre, niemals zu einem geratenen Kill. |
| L4 | P1 | Alte Shutdown-Nachweise konnten nach einer fehlgeschlagenen oder konkurrierenden Aktion weiter existieren. | Neue Aktionen und beginnende Verifikationen verwerfen alte Belege. Ein erfolgreicher Beleg ist an den Gate-Zustand gebunden; Resume prüft ihn auch nach den APIs erneut und verbraucht ihn erst beim verifizierten Erfolg. Wiederholtes erfolgreiches Resume bleibt idempotent. |
| L5 | P1 | Bootout ist asynchron; einzelne vorübergehende Zustände erzeugten sofort 503. Prüfwerkzeugfehler konnten außerdem als „nicht geladen/freier Port“ gelten. | Begrenzte Wiederholungen für Stop-Verifikation und vorübergehende Startup-503/502/504 oder Verbindungsfehler. `launchctl` akzeptiert nur Erfolg oder nachgewiesenes ESRCH (lokal Exit 113 verifiziert); `lsof` nur 0/1. Andere Fehler schließen die Annahme. |
| L6 | P1 | Beschädigte gespeicherte Statusfelder und untypisierte Fortschrittsfelder konnten spätere Status-/Lifecycle-Aufrufe mit internen Fehlern abbrechen. | Gespeicherter Zustand wird bereits beim Import validiert. Ungültige Dateien führen zu verständlichem Fehlerstatus und gesperrter Annahme. Falsch typisierte/überlange Fortschrittsmeldungen werden mit 422 abgelehnt. Ungültige Readiness-JSON-Antworten zeigen keinen privaten Fehlerkörper. |
| L7 | P1 | Bild-Validierungsfehler konnten vollständige Validator-Inputs inklusive Upload-Pfaden im Chat zeigen; falsch typisierte Action-Felder konnten den Fehlerfilter abbrechen. | Image-Bridge, Queue, Agent-Tool-Ergebnis und Web-Proxy verwenden feste deutsche Validierungstexte. Der Browser liest dafür keinen rohen HTTP-Körper mehr. Gespeicherte Bild-/Video-Validatorfehler werden gekürzt; auch falsch typisierte Action-Felder bleiben kontrollierte 422. |
| F1 | P2 | `remaining()` las die Kindprozessdatei innerhalb der Schleife einmal pro Hostprozess. | Pro Statusprüfung wird der Eigentumsnachweis einmal gelesen; dieselben Geburtsprüfungen bleiben bestehen. Gemessener CPU-/I/O-Gewinn siehe unten. |
| T1 | P2 | Die vollständige Python-Suite scheiterte bei Collection am Agent-Import unter einem unregistrierten Alias. Vier Dateivergleichstests litten unter dem in ihrem Arbeitsordner erzeugten Gate-Verzeichnis. | Der Batch-Test nutzt den regulären Modulimport. Lifecycle-Testdaten erhalten ein eigenes temporäres Verzeichnis außerhalb des jeweiligen Test-Arbeitsordners. |
| T2 | P2 | Tests erwarteten alte Cache-Versionen und noch nicht unterstützte Langvideo-Dauern. | Erwartungen auf den tatsächlichen vorhandenen Picker-Stand und die bereits implementierten Standard-/Qualitätsdauern korrigiert. Bestehende Langvideo-Funktionen werden nicht zurückgebaut. |
| T3 | P2 | Der i18n-Scan meldete vorhandene zweisprachige Editor-Helfer/Phasen und absichtlich deutsche Validierungsverträge als unübersetzt. | Er erkennt die konkreten zweisprachigen Formen; nur die festen deutschen öffentlichen Bild-/Video-Validierungsfehler sind ausgenommen. Neue unübersetzte deutsche Meldungen bleiben auffällig; gezielte positive/negative Tests sichern das ab. |
| T4 | P2 | Browser-Tests löschten frühere Artefakte gleichen Namens; ihr Agent kannte die vorhandene Editor-Jobliste nicht. | Jeder Test erhält ein neues Artefaktverzeichnis, EML-Daten sind isoliert und die bestehende GET-Jobliste wird korrekt simuliert. Unbekannte Requests bleiben 501; Konsole-/Netzwerkfehler werden nicht ignoriert. |

Die sechs ersten neuen Reproduktionstests waren vor den Änderungen rot und
bestätigten Gate-Race, PID-/Zombie-Probleme, Wächterfehler und wiederholte
Dateizugriffe. Die anschließenden Fix-/Testzyklen umfassen unter anderem einen
echten eigenen CPU-Kindprozess bei Wächterausfall und konkurrierende Prozesse
mit echten Dateisperren. Kein produktiver Prozess erhielt ein Signal.

## Bild, Video, Chat, optionale Dienste und Speicher

Die lokale Bildregistry hat Juggernaut als Default. Aktiviert waren außerdem
FLUX.1 schnell, Z-Image Turbo, Qwen Edit 2511, MLX-Serve Qwen Image 2.1 und Osaurus
Qwen 2.1 Edit. CyberRealistic Pony blieb als vorhandener Registry-Eintrag erhalten
und ist durch den vorherigen Picker-Fix weiterhin verborgen. Kein Modell wurde
neu angeboten oder ersetzt. Aktiviert bedeutet nicht durch diesen Audit gerendert.

Die CPU-Suite prüft unter anderem SDXL-Prozessbereinigung und Modellwechsel,
Bild-Cancellation, Referenzen, Varianten, MIME-/Formatbehandlung und die
bestehenden Qwen-/MFLUX-/MLX-Gen-Verträge. Die [Bildmodell-Testmatrix](image-model-test-matrix.md)
dokumentiert ausdrücklich: keine neuen GPU-Erfolgsmessungen, keine Änderungen
an Bildqualität, Steps, CFG oder Modellgewichten.

Video-Default bleibt `ltx-2.5-mlx-q4`. Der vorhandene Desktop-Headless-Eintrag
bleibt erhalten. LTX-MLX 0.18, Long-Video-Planer, Checkpoints, Retry, Full-HD,
T2V/I2V, Editor, FFmpeg-Validierung, Cancellation und Qualitätsprofile gehören zur
Regression. Der Uncensored-Adapter war konfiguriert und die Datei vorhanden;
das ist kein Load-/Rendernachweis. **Uncensored-Fortsetzung bleibt gesperrt**, da
die gepinnte Extend-CLI den Adapter nicht durchgängig übernimmt. Profilbestätigung
und kompakte deutsche Validierungsfehler bleiben erhalten.

Chat-Streaming, Routing, Modellwahl, Bild-/Videorouting und Fehlermeldungen werden
durch Python-/Node-Tests und reale Browser gegen simulierte Dienste geprüft.
Der gemeinsame Runtime-Lock bleibt erhalten. Optionale Speech-/MuseTalk-Ausfälle
werden in den vorhandenen Handoff-Pfaden berücksichtigt; unverifizierte aktive
Video-Prozesse werden nicht einfach übergangen. Der vollständige Wiederanlauf
prüft die sieben in `scripts/mlx restart-all` konfigurierten Modelldienste;
MuseTalk und Suchdienste werden dafür nicht zur neuen Pflichtabhängigkeit.

Bild-Validierungsfehler sind auch bei HTTP-200-Toolfehlern geschützt. Bereits
gespeicherte strukturierte/JSON/Python-Validatorfehler werden im Chat gekürzt;
normale verständliche Cancellation- und Laufzeitmeldungen bleiben erhalten.
Die Frontend-Script-Version ist `20261029-full-stability-audit`. Diese Änderung
senkt keine Bild-/Videoqualität und ändert keine Generierungsparameter.

Ein späterer lesender Snapshot zeigte 48 GiB RAM, etwa 20,64 GiB geschätzten
verfügbaren Speicher, 14,64 GiB Headroom nach Reserve und 12,5 GiB belegten Swap.
Die Pressure-Klasse war „normal“, die verwaltete Prozessregistry leer. Das
beweist weder die Abwesenheit eines Lecks noch dessen Ursache. Fremde Anwendungen
und historische Swap-Belegung werden MLX-Nobby nicht zugerechnet. Es wurde weder
Speicher gepurgt noch ein MPS-Limit deaktiviert. Admission verwendet weiterhin
frische Speicherwerte; der bestehende Diagnosecache ersetzt keine Schutzprüfung.

## Gemessene Performance

Ein konkreter Flaschenhals war das wiederholte Lesen der Kindprozessdatei bei
jedem Status-/Cleanup-Scan. Der Benchmark verwendet tatsächliche temporäre
JSON-Dateizugriffe, 1.000 synthetische Prozesszeilen, fünf gespeicherte
Geburtsidentitäten, ein Warmup-Paar und 20 abwechselnde Vorher-/Nachher-Paare.
Vorher ist der unveränderte Referenzalgorithmus des Ausgangscommits; die
Ergebnisidentitäten werden in jedem Durchlauf verglichen.

| Messung | Vorher | Nachher |
| --- | --- | --- |
| Dateilesungen je Scan | 1.000 | 1 |
| Median je Scan | 18,13 ms | 0,46 ms |
| Beobachtete Spanne | 17,78–19,20 ms | 0,42–0,49 ms |

Das entspricht ungefähr 97,5 % weniger Laufzeit in **dieser CPU-/I/O-Prüfung**.
Nebenwirkung: Ein einzelner Scan verwendet einen konsistenten Mitglieder-Snapshot;
die nächste Prüfung liest neu. Unbekannte aktive Gruppenmitglieder blockieren
weiterhin Cleanup-Erfolg und erhalten keine ungeprüften Signale.

Reproduzieren, ohne Dienste oder Modelle anzusprechen:

```sh
test-venv/bin/python scripts/benchmark-managed-process-status.py --samples 20 --rows 1000
```

Die vorhandenen unversionierten Benchmarkberichte wurden nur lesend ausgewertet.
V13/V14-Fix/V14-Final enthalten jeweils fünf Samples, End-to-End-Mediane von
43,82/45,16/46,37 s und sind selbst als `heuristic_review_only` gekennzeichnet.
Sie messen keinen aktuellen Modell-TTFT-Vorher-/Nachher-Vergleich. Der bestehende
[Performance-Audit](PERFORMANCE_AUDIT.md) dokumentiert bereits behobene Browser-
Requestschleifen. Es werden keine neuen Gewinne an Tokens/s, GPU-Renderzeit,
Bild-/Videoqualität, Modellwechselzeit oder Unified-Memory-Peak behauptet.

## Verifikation

Alle abschließenden Gesamtläufe sind erfolgreich:

| Prüfung | Ergebnis | Dauer |
| --- | --- | --- |
| Gesamte getrackte Python-Unit-/Integration-Suite | 3.859 bestanden, 462 Untertests bestanden, 0 Fehler | 114,28 s |
| Gesamte getrackte Node-Suite | 373 bestanden, 0 Fehler | 0,73 s |
| Vollständige isolierte Desktop-/Mobil-Browser-Suite | 118 bestanden, 0 Fehler | 183,27 s |

Exakte Testkommandos (die Auswahl über Git lässt vorhandene unversionierte
Benutzer-/Labortests unangetastet):

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  test-venv/bin/python -m pytest -q $(git ls-files 'tests/test_*.py')
node --test $(git ls-files 'tests/*.mjs')
PYTHONDONTWRITEBYTECODE=1 test-venv/bin/python -m pytest --e2e -q tests/e2e --maxfail=1
```

Der [maschinenlesbare Auditbericht](mlx-nobby-full-stability-audit-2026-10-29.json)
enthält Ergebnisse, Messwerte und Grenzen. Die Browser greifen ausschließlich
auf den isolierten Testserver mit simuliertem Agent zu. Lifecycle-Tests verwenden
eigene temporäre Gate-/Registry-Verzeichnisse und eigene CPU-Prozesse.

Vorherige Fehler wurden nicht ausgeblendet: Die Python-Collection scheiterte am
unregistrierten Agent-Alias; danach waren sechs Tests wegen Verzeichnis-Isolation
und veralteter Dauer-Erwartungen rot. Ein späterer Lauf fand den noch fehlenden
Berichtslink. Beim Bildfehlerfilter wurde eine bestehende präzise öffentliche
Job-ID-Meldung zunächst zu stark gekürzt; eine feste Allowlist bewahrt sie jetzt,
ohne private Validator-Inputs zu übernehmen. Die ersten 14 Browserfälle bestanden
UI-Assertions, meldeten aber Fehler durch den fehlenden Editor-GET-Vertrag im
Testadapter. Alle diese Ursachen sind behoben und die vollständigen Läufe grün.

Python-, JSON-, JavaScript- und Shell-Syntax, LaunchAgent-Plists und der i18n-Scan
bestanden ebenfalls. Der bekannte Starlette/httpx-TestClient-Deprecation-Hinweis
bleibt bestehen; es wurden keine Pakete dafür aktualisiert.

## Geänderte Dateien

- Lifecycle und Prozessverwaltung: `ai_lifecycle_gate.py`, `managed_process.py`,
  `agent/ai_lifecycle.py`, `agent/process_guard.py`, `agent/app.py`,
  `scripts/ai-lifecycle.py`.
- Öffentliche Bild-/Videofehler: `backend/media_errors.py`, `backend/app.py`,
  `agent/image_api.py`, `agent/video_api.py`, `agent/media_queue.py`,
  `frontend/assets/chat/generation.js`, `frontend/chat.html`,
  `frontend/i18n/de.json`, `frontend/i18n/en.json`.
- Diagnose und Audit: `scripts/benchmark-managed-process-status.py`,
  `scripts/i18n-audit.py`, `docs/image-model-test-matrix.md`, dieser Bericht und
  `docs/mlx-nobby-full-stability-audit-2026-10-29.json`.
- Tests/Isolation: `tests/conftest.py`, `tests/e2e/conftest.py`,
  `tests/e2e/harness.py`, `tests/test_ai_lifecycle_reliability.py`,
  `tests/test_batch_transform.py`, `tests/test_i18n_audit_helpers.py`,
  `tests/test_image_edit.mjs`, `tests/test_lifecycle_audit.py`,
  `tests/test_media_library_ui.mjs`, `tests/test_media_validation_privacy.py`,
  `tests/test_media_validation_privacy.mjs`, `tests/test_shorts_editor.py`,
  `tests/test_video_job.mjs`.

## Sichere Aktualisierung und manuelle Abnahme

Die Änderungen sind Quellcode, Tests und Dokumentation; laufende Prozesse laden
sie nicht automatisch neu. **Vor manueller Installation laufende Chat-, Bild-,
Video-, Audio-, Datei- und Batch-Aufträge regulär beenden lassen.** Eine reine
Browser-Aktualisierung oder ein isolierter Web-Neubau installiert den Agent-Fix
nicht. Bei uncommitteten getrackten Änderungen nicht fortfahren; nichts löschen,
zurücksetzen oder zwangsweise überschreiben.

```sh
cd ~/mlx-web
git fetch origin fix/mlx-nobby-full-stability-audit-20261029
git switch fix/mlx-nobby-full-stability-audit-20261029
git merge --ff-only origin/fix/mlx-nobby-full-stability-audit-20261029

# Erst im auftragsfreien Zustand: neuen Agent-Code für das Stop-Protokoll laden.
./scripts/mlx agent restart
./scripts/rebuild-all.sh

curl --fail-with-body http://127.0.0.1:8010/api/system/lifecycle
curl --fail-with-body http://127.0.0.1:8030/health
curl --fail-with-body http://127.0.0.1:8060/health
curl --fail-with-body http://127.0.0.1:8090/api/version
```

Der vorhandene Rebuild bewahrt den Branch, stoppt/verifiziert KI-Dienste, baut
Web/Frontend neu, synchronisiert LaunchAgents, lädt Agent-Code neu und prüft vor
Freigabe APIs und Web-Revision. Sein Git-Sync überspringt Feature-/Fix-Branches;
Main wird nicht zusammengeführt. Keiner dieser Installationsbefehle wurde hier
gegen die laufende Installation ausgeführt.

Manuell anschließend:

1. „KI beenden“ prüfen: Gate geschlossen, Modelldienste und eigene Worker beendet,
   Agent/Web weiterhin erreichbar, eindeutiger Abschlussstatus.
2. Wiederholen und anschließend „KI starten“/„MLX-Nobby neu aufbauen“ prüfen:
   kein doppelter Helfer, kein Freigeben vor verifizierten APIs, aktuelle Web-Revision.
3. Einen bestehenden Bildjob und einen kurzen Standard-LTX-Job getrennt prüfen,
   jeweils Abbruch und direkt folgenden Wiederholungsjob. Ergebnisse und echte
   Speicherfreigabe kontrollieren; nach jedem Bildmodelltest die Testmatrix ergänzen.
4. Standard 5/10/20 s und I2V-Porträt prüfen. Uncensored darf bei maximaler
   Qualität keine 10-/20-Sekunden-Fortsetzung bestätigen. Kein Profil darf still wechseln.
5. Gesondert echte 1080p-Langvideos, Editor/Checkpoints, Audio, TTFT und wiederholte
   GPU-Modellwechsel abnehmen. Diese reale Qualität-/Lastabnahme wurde nicht automatisiert.

Wenn die Verifikation fehlschlägt: Gate geschlossen lassen, gemeldete Phase und
Ursache prüfen. **Keine Gate-Datei löschen und keinen fremden Prozess beenden.**
Lebende Legacy-Nachweise ohne Geburtsidentität erfordern eine manuelle
Eigentumsprüfung oder den regulären nachgewiesenen Prozessabschluss. Ein erneut
kontrollierter vollständiger Restart regeneriert den Shutdown-Nachweis; eine
alte Belegdatei darf den neuen Zyklus nicht freischalten.

## Technische Bewertung

Die bestätigten Fehler werden durch kleine Änderungen an den vorhandenen
Lifecycle-/Wächterverträgen behoben, ohne neue Modelle, Scheduler, Dienste oder
Bildqualitätsänderungen. CPU- und simulierte UI-Freigabe ersetzen keinen echten
Metal-/MPS-Lasttest. Eine pauschale Produktionsfreigabe für ungetestete GPU-Pfade,
Systemabbrüche oder neue Modellqualitäten wird ausdrücklich nicht behauptet.
Die vollständigen lokalen CPU-/Browserregressionen sind grün. Die kontrollierte
Installation und reale GPU-/Qualitätsabnahme stehen noch aus.
