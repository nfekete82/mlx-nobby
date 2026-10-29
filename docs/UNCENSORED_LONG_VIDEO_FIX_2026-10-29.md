# Uncensored-Profil und automatische Langvideos

Stand: 2026-10-29. Basis: `d9bf13d95f9e341adf4f923f4a39877b9e3eafc0` auf
`feat/automatic-long-video-sdxl-reliability-20261029`.
Fix-Branch: `fix/uncensored-long-video-profile-20261029`.

## Installierte CLI geprüft

Der lokale LTX-MLX-0.18-Checkout unter
`~/.local/share/mlx-nobby/ltx-2-mlx-v0.18.0` steht unverändert auf
`b82b97e3d000e01361f8cfcb745244b15b89a521`.
SHA-256 der geprüften `packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/cli.py`:
`1f8383c29f3acc362b6886e93de71b623677d9a04ed28527126b3f8b0ee29b23`.

`generate` registriert `--lora PATH STRENGTH` und setzt `_pending_loras` auf
den Pipeline-Instanzen. `extend` registriert diesen Parameter weder selbst
noch über `_add_base_args`; auch `_cmd_extend` und `_cmd_extend_distilled`
übernehmen keinen Adapter. Der gleiche Uncensored-Adapter lässt sich daher
über diese Extend-CLI nicht durchgängig anwenden. Prüfung durch Quelltext und
AST, ohne Import der MLX-Pipeline, Modellladen oder Rendern.

Die sichere Sperre bleibt im Backend und in `video_long.run` erhalten. Es gibt
keine neue Adapter-Unterstützung für Extend und keinen Eingriff in Checkpoints,
Speicherprüfungen, Retry, Cancellation oder Lifecycle. Standard-Langvideos nutzen
weiterhin die bestehende Orchestrierung.

## Verhalten im Dialog und in der Anfrage

| Qualität | Direkte Uncensored-Dauer | Standard 5/10/20 s |
| --- | --- | --- |
| Maximale Qualität / 1080p | bis 5 s | verfügbar |
| Standard / 720p | bis 10 s | verfügbar |
| Schnell / 540p | bis 20 s | verfügbar |

Die bisherigen 6-/8-Sekunden-Optionen der kleineren Profile sowie die
Text-zu-Video-Vorschau bleiben erhalten. Die Einschränkung gilt gleichermaßen
für Text-zu-Video und Bild-zu-Video mit einem Startbild.

Uncensored zeigt eine deutsche Erklärung mit den direkten Grenzen. Nicht
unterstützte Dauern sind deaktiviert; eine bereits gewählte längere Dauer bleibt
sichtbar und sperrt die Bestätigung einschließlich Enter und synthetischen
Klicks. Der Nutzer kann bewusst Standard oder eine kürzere Dauer wählen.
Profilwechsel kürzen die Dauer nicht stillschweigend.

Der Dialog wartet die Offline-Profilverfügbarkeit ab, bevor er geöffnet wird.
Jede neue Auswahl beginnt sichtbar mit Standard. Bestätigung hält Profil,
Dauer, Qualität und Format in einem unveränderlichen Snapshot fest. Ausschließlich
dieser Profilwert überschreibt ältere `options.video.profile`-Werte. Änderungen
am wiederverwendeten Auswahlfeld nach Bestätigung wirken sich nicht auf die
Anfrage aus. Die frühere Screenshot-Abweichung wurde nicht rückwirkend als
konkreter Browserfehler reproduziert; die möglichen Übergabefehler sind durch
Tests abgesichert und die Script-URL ist neu versioniert.

## Kompakte Validierungsfehler

Der native Dienst liefert für die gesperrte Fortsetzung einen eigenen
Validierungscode und einen festen deutschen Text. Sonstige unbekannte
400-/422-Validierungsfehler werden auf eine kurze deutsche Erklärung reduziert.
Ein gemeinsamer Filter schützt native HTTP-Antworten, Agent-Bridge, Queue und
Web-Proxy. Der Agent schützt auch fehlgeschlagene Tool-Ergebnisse innerhalb einer
HTTP-200-Antwort. Python-Fehlerkörper, Validator-Inputs, lokale Pfade und
Upload-Metadaten werden dabei nicht in die Fehlermeldung übernommen.

Das Frontend übernimmt nur bekannte öffentliche Validierungsmeldungen. Auch
strukturierte oder als JSON/Python-Repr gespeicherte Validierungsfehler älterer
Videojobs werden bei der Fehlerdarstellung gekürzt. Bestehende verständliche
Cancellation-Meldungen bleiben erhalten.

## Prüfung

- Vollständige ausgewählte Backend-Regression: **766 Tests und 201 Untertests
  bestanden**, 41 Dateien, 42,42 s. Enthält Qualität, Langvideos, Checkpoints,
  Retry, Cancellation, Prozessbereinigung und Lifecycle.
- Nach zwei zusätzlichen Testfällen/Assertions: **79 Profil-/Validierungstests
  und 31 Untertests bestanden**, 0,48 s. Diese überlappen mit der Regression;
  die Zahlen werden nicht addiert.
- Gesamtes Frontend: **369 Tests bestanden**. Zusätzlich zum bestehenden Ablauf
  prüft der Dialogtest Standard/Uncensored × 5/10/20 s × T2V/I2V bei maximaler
  Qualität und Hochformat, alte Optionen, nachträgliche DOM-Änderungen,
  gesperrte Klicks/Enter, Abbrechen und verzögerte Verfügbarkeit. Die
  Backend-Matrix deckt außerdem Standard- und Schnell-Qualität ab.
- HTTP-400/422- und HTTP-200-Toolfehler mit absichtlich privaten Pfaden und
  Upload-Inputs bleiben in der Chatdarstellung kurz und deutsch.
- `git diff --check` bestanden. Ein bestehender Starlette/httpx-TestClient-
  Deprecation-Hinweis bleibt bestehen.

Ein erster Backend-Sammellauf über einen zusätzlichen Python-Subprozess-Wrapper
hatte 754 erfolgreiche Tests und einen Fehler im bestehenden Test
`test_stale_pid_identity_never_receives_signal`: Der Wrapper änderte die dort
vorausgesetzte Prozessgruppe des Testprozesses. Der direkte pytest-Aufruf bestand
vollständig; Lifecycle-Implementierung und dieser Test wurden nicht verändert.
Für FFprobe-Prozessüberwachung war lesender `ps`-Zugriff außerhalb der Sandbox
nötig. Alle Testzustände lagen in isolierten temporären Verzeichnissen.

Es gab **keine produktiven GPU-Jobs, Modellladungen, Reboots, Dienstneustarts
oder Deployments**. Die Bildmodell-Testmatrix erhält keinen neuen Renderstatus:
Es wurde kein echtes Bildmodell getestet. Die echte visuelle Langvideo-Abnahme
aus dem vorherigen Bericht bleibt offen.

## Aktivierung

Commit und Push installieren keine laufenden Dienste. Zur Aktivierung müssen
Agent und nativer Videodienst aus diesem Branch neu geladen und das Web-Image
mit den geänderten Frontend-Assets neu gebaut werden. Anschließend die Chatseite
neu laden; `generation.js?v=20261029-video-profile-confirmation` verhindert die
Wiederverwendung des vorherigen Scripts. Der bestehende sichere Rebuild-Ablauf
ist im [Basisbericht](AUTOMATIC_LONG_VIDEO_SDXL_2026-10-29.md#installation-vollständiger-rebuild-erforderlich)
beschrieben; dort bei der Branchwahl den oben genannten Fix-Branch verwenden.
