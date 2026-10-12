# MLX-Nobby V2 — Final Validation

Validierungsdatum: **11. Oktober 2026, Europe/Berlin**.
Branch: `feat/v2-live-intelligence`. Geprüfter Produktionscode: `fe0f540`.

## 1. Executive Summary

Die Runtime-, Quellen- und Telemetrie-Härtung ist implementiert und lokal getestet.
**NOT READY:** Alle ausgeführten Tests und die GitHub-Prüfungen des finalen Codes
sind grün. Der finale sequentielle Live-Benchmark verfehlt mit **70,59 s Median**
das verbindliche Ziel **unter 45 s**. Degradierte externe Suchmaschinen und
verbleibende Grenzen der semantischen Faktenprüfung verhindern eine belastbare
Produktionsfreigabe. Die Härtung ist reviewbar; ein Release wird nicht empfohlen.

## 2. Gefundene Fehler

- Die bisherige Agent-Diagnose konnte andere Dienste nicht zuverlässig zuordnen;
  der gemeinsame Lease speicherte keine abgeschlossenen Warte-/Haltezeiten.
- Chat-Recovery konnte den Agent während legitimer Agent-Arbeit neu starten.
  Im ursprünglichen Live-Lauf waren drei von fünf Verbindungen nicht erreichbar;
  die Recovery-Diagnose dokumentierte `chat_first_byte_timeout` und einen PID-Wechsel.
  Eine vollständige Kausalkette für jede verlorene Verbindung ist nicht bewiesen.
- Cancellation während des Provider-Modell-Lock-Wartens konnte den äußeren Lease
  bis zur späteren Lock-Freigabe festhalten.
- Späte Datumsangaben in langen Zeilen und Angaben ohne wiederholtes Jahr konnten
  bei der Kontextkomprimierung verschwinden.
- ISO-/englische Termine, Preise in Markdown-Linktext und Geldbeträge mit
  vorangestelltem Währungssymbol entgingen Teilen der Prüfung. Preise benachbarter
  Geräte beziehungsweise ähnlich beginnende Modellnummern konnten falsch zugeordnet werden.
- Direktantworten des Diagnose-Planers umgingen den numerischen Quellen-Check.
- Beim Google-News-RSS-Fallback konnte ein „offiziell“-Titel einen Aggregator
  fälschlich zum automatischen Hersteller-Fetch machen. In einem Live-Lauf
  lieferte dieser Fetch keinen verwertbaren Text und weitere Planung war nötig.
- Falsch maskierte Anführungszeichen konnten einen zusätzlichen Reparaturaufruf
  und anschließend `invalid_agent_response` auslösen. Der Fehlerpfad protokollierte
  vollständigen Modelltext. Fehlgeschlagene JSON-Läufe verloren ihre bisherigen
  Schritte und Performance-Ereignisse in der API-Antwort.

## 3. Implementierte Korrekturen

- Zentrale, datensparsame Lease-Instrumentierung für alle vorhandenen gemeinsamen
  Erwerbs-/Freigabepfade; rollenbezogene Labels für echte Agent-/Coding-Aufrufe.
- Aktive Agent-Ausführung wird über Modell- und Tool-Phasen gezählt. Automatische
  Chat-Recovery respektiert diese Arbeit und andere beobachtete Runtime-Besitzer.
- Provider-Modell-Lock-Warten prüft Cancellation und gibt anschließend den äußeren
  Lease frei. Die Reihenfolge Lease → Modell-Lock bleibt erhalten.
- Komprimierung erhält zusätzliche datierte Verfügbarkeitsauszüge, auch aus langen
  Einzelzeilen und ohne wiederholtes Jahr, und kennzeichnet gekürzte Volltexte.
- Quellen-/Datumsprüfung berücksichtigt weitere Schreibweisen und Produktkontext.
  Die gemeinsame Abschlussgrenze prüft auch direkte Diagnoseantworten. Unbelegte
  Links werden entfernt; fehlende Artikeltexte werden ausdrücklich gekennzeichnet.
- Der automatische Hersteller-Follow-up verlangt bei bekannten Herstellern
  die tatsächliche Hersteller-Domain, nicht nur Titel-/Snippettext. Fehlerhaft
  strukturierte Such-URLs werden übersprungen; normale Tool-Prüfungen bleiben aktiv.
- Eine enge deterministische Formatkorrektur repariert Anführungszeichen nur im
  zweifeldrigen `final`-Antwortformat. Tool-Aktionen behalten die strikte Prüfung.
  JSON-Fehlerlogs enthalten nur feste Fehlertypen und Zeichenzahlen.
- Benchmark-Berichte enthalten p95, Fehlerquote, per-Frage-Kohorten, Aufrufzweck,
  Warte-/Vorbereitungs-/Upstream-Zeiten und bekannte Tokenzähler. Rohantworten
  werden inkrementell lokal gespeichert; Berichte verwenden Frage-Indizes.

## 4. Lease-Management-Ergebnisse

Reale Zwischenmessungen ordneten Wartezeiten von **44,95 s** und **41,94 s** dem
beobachteten Workload `image` zu. Die entsprechenden gesamten Lease-Wartezeiten
lagen bei 44,99 s und 41,94 s; die Modell-Lock-Wartezeit war gerundet 0 ms.
Damit ist ein konkreter anderer Dienst beobachtet, keine bloße Vermutung über den Besitzer.
Eine Beobachtung beweist nicht, dass derselbe Besitzer die gesamte Wartezeit verursachte.

Neue Tests verwenden echte Threads, einen separaten Prozess und `flock` für
Besitzerbeobachtung, Cancellation, optionale Erwerbs-Timeouts, verschachtelte
Leases und Wiedererwerb nach Fehlern. Ein Provider-Test bestätigt das Label
`coding` und die Lease-Freigabe bei Cancellation am belegten Modell-Lock.
Die Historie enthält Erwerbs-/Freigabezeit, monotone Warte-/Haltezeiten und
Ausgänge; `unknown` bleibt ausdrücklich unbekannt. Unbelegte Null-Wartepfade
werden nicht als fremde Besitzer interpretiert.

Scheduling, Prioritäten und Speichergrenzen wurden nicht umgestellt. Neue
Erwerbs-Timeouts sind optional; bestehende Produktionsaufrufe bleiben unbefristet.
Die Diagnosehistorie ist ein Ring von 128 Einträgen je Prozess und ein aggregiertes
Fenster der letzten 128 Einträge. Alte Prozessdateien bleiben lokal erhalten;
dies ist keine dauerhafte, vollständige Audit-Datenbank. Details:
[Runtime Lease Diagnostics](RUNTIME_LEASE_DIAGNOSTICS.md).

## 5. Performance vorher/nachher

Historische Benutzerberichte: V9 45,08 s, V10 40,25 s, V11 54,49 s,
V12 53,56 s Median, jeweils fünf erfolgreiche Läufe. Ihre vollständigen
Hardware-/Lastbedingungen sind nicht belegt; daraus folgt kein kontrollierter Vergleich.

Die neuen Messungen verwenden dieselbe bestehende öffentliche Testfrage und
mindestens fünf Wiederholungen pro Kohorte. Separate Agent-Prozesse isolieren
Benutzerdaten, verwenden aber den echten gemeinsamen Modellserver, Lease und
RAM-Guard. Hardware: Apple M5 Max, arm64, 18 logische CPUs, 48 GiB RAM;
macOS 26.6.2, Python 3.13.13, Modell `Qwen3.8-27B-Abliterated-MLX-4bit`,
Alias `qwen38_20260927`. Eine Ressourcenstichprobe zeigte normale Memory Pressure,
16,32 GiB geschätzte Verfügbarkeit, 6 GiB Reserve und 13,75 GiB verwendeten Swap.
Das ist keine kontinuierliche Ressourcenaufzeichnung.

Sequenziell bezeichnet den Benchmark-Client, nicht einen exklusiven Rechner:
Bildarbeit wurde tatsächlich parallel beobachtet. Laufzeiten werden nicht um
Wartezeiten bereinigt, fehlerhafte Versuche nicht versteckt. p95 verwendet
Nearest Rank und entspricht bei fünf Erfolgen dem Maximum. Kleine Stichprobe,
wechselnde Webinhalte und Hintergrundlast begrenzen jede Vorher-/Nachher-Aussage.

| Kohorte | Erfolge / Versuche | Fehlerquote | Median | p95 | Minimum | Maximum | Modellaufrufe je Erfolg |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Archivierter Ausgangscode `8e8a632`, sequenziell | 4 / 5 | 20 % | 41,97 s | 44,93 s | 37,56 s | 44,93 s | 3 |
| Zwischenstand nach erster Instrumentierung, sequenziell | 5 / 5 | 0 % | 46,16 s | 102,71 s | 30,96 s | 102,71 s | 2–4 |
| Derselbe Zwischenstand, zwei parallele Anfragen | 3 / 5 | 40 % | 134,33 s | 143,55 s | 87,02 s | 143,55 s | 3–5 |
| Härtungsstand `6e74dac`, sequenziell | 5 / 5 | 0 % | 53,10 s | 76,53 s | 49,61 s | 76,53 s | 4 |
| Härtungsstand `6e74dac`, zwei parallele Anfragen | 5 / 5 | 0 % | 97,41 s | 144,07 s | 77,32 s | 144,07 s | 4–5 |
| **Final `fe0f540`, sequenziell** | **5 / 5** | **0 %** | **70,59 s** | **79,16 s** | **66,05 s** | **79,16 s** | **5** |
| **Final `fe0f540`, zwei parallele Anfragen** | **5 / 5** | **0 %** | **152,74 s** | **177,80 s** | **114,62 s** | **177,80 s** | **5–6** |

Latenzstatistiken beziehen sich auf erfolgreiche Antworten. Der fehlgeschlagene
Ausgangslauf dauerte 51,05 s und endete nach Planung und Format-Reparatur mit
`invalid_agent_response`; seine alte Fehlerantwort verlor die Aufruftelemetrie.
Die zwei Fehler des ersten parallelen Zwischenstands waren ebenfalls ungültige
Modellantworten. Der separate erste Versuch gegen den bestehenden Dienst erreichte
nur 2/5 Antworten und 3 Verbindungsfehler; er ist kein brauchbarer Latenzvergleich.

| Median der summierten Phasen je erfolgreicher Antwort | Ausgangscode | Final, sequenziell | Final, parallel |
| --- | --- | --- | --- |
| Lease-Warten | 28,18 ms | 42,34 ms | 78,19 s |
| Modell-Lock-Warten | 0,00 ms | 0,04 ms | 0,06 ms |
| Modellvorbereitung | 37,47 ms | 78,47 ms | 99,05 ms |
| Upstream-Anfrage einschließlich Inferenz | 40,18 s | 68,71 s | 89,73 s |
| Bekannte Gesamttokens über alle Aufrufe | 16.876 | 31.594 | 41.727 |

Upstream-Zeit ist keine isolierte GPU-Rechenzeit; sie enthält Server- und
HTTP-Wartezeit. Die vereinfachten Benchmark-Ereignisse liefern Gesamttokens,
aber keine getrennten Prompt-/Completion-Zähler. Dort ausgewiesene Nullwerte
bedeuten unbekannt. Die lokalen Rohcaptures enthalten die detaillierten
Provider-Metriken, soweit der Server sie liefert. Unabhängig gebildete Mediane
der Phasen müssen sich nicht zum Median der Gesamtlatenz addieren.

Alle fünf finalen sequentiellen Antworten benötigten fünf `agent.plan`-Aufrufe
und zwei Fetches. Kein Format-Reparaturaufruf trat auf. Ein Lauf trägt
`missing_article_evidence`; fehlende automatische Flags bei den anderen vier
sind kein Wahrheitsbeweis. Nahezu fehlendes Lease-Warten widerlegt für diese
Kohorte eine Erklärung der 70,59 s durch fremde Lock-Besitzer.

Die finale parallele Kohorte ist separat abgeschlossen: fünf Antworten, keine
Transport-/Runtime-Fehler, fünf bis sechs Modellaufrufe. Drei Antworten tragen
`missing_article_evidence`. Der Median steigt auf 152,74 s; erhebliche zentrale
Lease-Wartezeit ist dort gemessen. Der 180-s-Request-Timeout wurde nicht erhöht,
um den längsten erfolgreichen Lauf von 177,80 s nachträglich einzuschließen.
Bei allen beobachteten belegten Leases dieser Kohorte lautete der Besitzer
`agent`; die Konkurrenz zwischen Agent-Aufrufen ist damit unmittelbar belegt.
Alle Modellaufrufe waren `agent.plan`, auch die sechsten Aufrufe.

**Belegter externer Blocker:** SearXNG auf Port 8081 antwortete mit HTTP 200,
sein Container lief. Die tatsächliche JSON-Suche lieferte jedoch **null Treffer**:
Brave und Google CSE meldeten `too many requests`, DuckDuckGo `access denied`,
Startpage `CAPTCHA`. Das ist ein degradierter Upstream, kein fehlender lokaler
Dienst. RSS-Ausweichpfade und nicht verwertbare Artikeltexte führten in den
Captures zu zusätzlichen Such-/Planungsschritten. Daraus folgt keine exakte
Kausalzuordnung jeder zusätzlichen Sekunde. Keine Suchsperre wurde umgangen,
kein Benutzerdienst neu gestartet und kein alternativer Provider ungeprüft aktiviert.

Zusätzliche Aufrufe sind unterscheidbar: weitere `agent.plan`-Aufrufe nach einem
zusätzlichen Fetch, `agent.plan_repair` bei Formatfehlern, `agent.final_repair`
und die vorhandene begrenzte `agent.evidence_repair`. Ein gemessener 102,71-s-
Zwischenlauf enthielt 44,95 s beobachtetes Bild-Warten und eine JSON-Formatreparatur.
Qualitätsreparaturen und notwendige zusätzliche Quellen werden nicht pauschal
entfernt, um den Zielwert künstlich zu erreichen.

## 6. Qualitätsprüfungen

Regressionen prüfen zukünftige Verkaufsstarts, ISO-/englische Termine, negierte
Erhältlichkeit, künftig verfügbares Zubehör neben bereits erhältlichen Geräten,
späte Verfügbarkeitsangaben, unabhängige Produktpreise und erfundene Links.
Die synthetische Evidenzprüfung lieferte bei 60 konstruierten Fällen TP=30,
TN=30, FP=0, FN=0. Das bewertet ausschließlich diese synthetischen Fälle.

Unabhängig geöffnet wurden die [offizielle Apple-Übersicht](https://www.apple.com/de/iphone/)
und die [Duo-Mitteilung](https://www.apple.com/de/newsroom/2026/09/apple-unveils-iphone-duo/).
Die Mitteilung nennt Vorbestellung am 16. Oktober und Verkaufsstart am 23. Oktober.
Am Validierungsdatum bedeutet die Listung in der Produktübersicht deshalb nicht
bereits erfolgte Verkaufsverfügbarkeit. Der Jahr-ausgelassen-Fall ist als eigener
Komprimierungsregressionstest aufgenommen.

Automatische Prüfungen sind Konsistenz-/Evidenzhinweise, keine unabhängige
Bestätigung von Wahrheit, Vollständigkeit oder Artikelautorität. Produktvarianten,
Regionen und Preise bleiben mögliche Ursachen scheinbarer Widersprüche.

Die manuelle Live-Stichprobe zeigt diese Grenze konkret: Ein Zwischenstand
bezeichnete das Duo unbelegt als kleineres Modell; numerische Checks erkannten
diese qualitative Behauptung nicht. Finale Antworten unterscheiden Listung und
zukünftigen Verkaufsstatus nicht durchgehend ausdrücklich. Die Datumsregression
ist getestet, eine allgemeine semantische Freigabe damit nicht nachgewiesen.
Der vierte finale sequentielle Lauf behauptet sogar einen bereits erfolgten
Verkaufsstart und unabhängige Bestätigung, obwohl kein Artikeltext geladen wurde.
Der angehängte Evidenzhinweis kennzeichnet die fehlende Bestätigung korrekt,
behebt aber den widersprüchlichen Antworttext nicht. Dieser Fall besteht die
manuelle Qualitätsabnahme nicht. `status=ok` im Benchmark bezeichnet einen
technisch abgeschlossenen Request, keine inhaltlich bestandene Antwort.

## 7. Testübersicht mit tatsächlichen Ergebnissen

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| Python, finaler Quellstand, `test-venv/bin/python -m pytest -q` | 2.085 bestanden, 419 Subtests bestanden, 47,40 s |
| JavaScript, `node --test tests/*.mjs` | 240 bestanden, 0 übersprungen |
| Chromium, `test-venv/bin/python -m pytest --e2e tests/e2e -q` | 78 bestanden, 126,40 s |
| `python -m compileall -q agent backend` und getrackte Python-Dateien | bestanden |
| `python -m pip check`, Basis- und Test-Environment | bestanden |
| JSON, i18n, JavaScript-/Shell-Syntax, launchd-Plists, Compose | 136 Prüfungen bestanden |
| Docker Compose Build mit CI-Buildargument | bestanden |
| Container-Entrypoint-Import ohne Netzwerk | bestanden |
| Synthetischer Evidenz-Benchmark | 60 Fälle, keine Fehlklassifikation in diesem Datensatz |

Die Browser-/Containerprüfungen wurden nach den Änderungen an Backend/Runtime
ausgeführt; die letzten Änderungen betreffen ausschließlich Recherche-Auswahl,
Kontextkomprimierung und ihre Regressionstests. Ein erneuter kompletter Python-Lauf
deckt diese Änderungen ab.
Eine Starlette-DeprecationWarning betrifft die bestehende httpx-Testclient-
Integration; sie ist kein Testfehler. Die erste Sandbox-Ausführung scheiterte an
Socket-/Subprozessrestriktionen; die freigegebene Testausführung reproduzierte
keinen dieser Fehler. Kein Test wurde entfernt, deaktiviert oder übersprungen.

## 8. CI-Ergebnisse

Alle drei GitHub-Prüfungen des finalen Produktionscodes `fe0f540` sind bestanden:

- [macos-tests: bestanden, 1 min 46 s](https://github.com/nfekete82/mlx-nobby/actions/runs/38092454398/job/114331504444)
- [docker-validation: bestanden, 18 s](https://github.com/nfekete82/mlx-nobby/actions/runs/38092454398/job/114331504524)
- [Chromium: bestanden, 4 min 56 s](https://github.com/nfekete82/mlx-nobby/actions/runs/38092454412/job/114331504614)

Workflows wurden gelesen; ihre Python-, JS-, JSON-, Übersetzungs-, Shell-, plist-,
Browser- und Docker-Schritte wurden auch lokal tatsächlich ausgeführt. Frühere
Runs wurden durch neue Pushes abgebrochen; sie sind keine bestandenen Prüfungen
des finalen Codes. Auf die geprüfte Implementierung folgt ausschließlich dieser
Dokumentationscommit; dessen erneute CI wird nach dem Push geprüft.

## 9. Sicherheitsprüfung

RAM-Reserve, Hard Limit, frische Modellladeprüfung, Runtime-Locks,
Tool-Permissions, Approval-Pfade, Workspace-/Upload-Grenzen, URL-/Redirect-Prüfung
und lokale Host-/Origin-Schranken bleiben bestehen. Speicherdiagnose-Caching
wird weiterhin nicht für Modellzulassung verwendet. Speech-/Embedding-Locks
und ihre unabhängigen Speicherprüfungen wurden geprüft und nicht unnötig
unter den Heavy-Runtime-Lease serialisiert.

Tests laufen mit isolierten Datenpfaden; Live-Prüfprozesse lesen ausschließlich
die benötigte Modellkonfiguration aus der bestehenden Installation und speichern
ihre übrigen Daten separat. Benutzer-Chats, Modelle, Medien, Datenbanken und
vorhandene Benchmarks wurden nicht gelöscht oder überschrieben. Nur eigens
gestartete Prüfprozesse werden nach Abschluss beendet. Neue Rohcaptures bleiben
unter dem ignorierten `artifacts/performance/v2-final-validation/`; sie werden
nicht gepusht. Vollständiger Modelltext wurde aus JSON-Fehlerlogs entfernt.
Dieser Review ist keine unabhängige Penetrationsprüfung.

## 10. Bekannte Restrisiken

- Release-Blocker: Der verbindliche sequentielle Median unter 45 s wird verfehlt;
  die externe Suche liefert wegen Provider-Sperren keine regulären Ergebnisse.
  Eine allgemeine semantische Faktenqualität ist nicht nachgewiesen.
- Live-Faktenprüfung ist heuristisch; semantische Behauptungen, Vollständigkeit,
  URL-Inhalt und Status ohne ausdrückliche Datumsangabe sind nicht allgemein beweisbar.
- Webprovider, externe Inhalte, nativer Modellserver und Hintergrundmedienarbeit
  können Laufzeit und Qualität ändern. Hoher Swap und kleine Stichproben begrenzen
  die Aussagekraft der Latenzvergleiche.
- Zentrale Diagnose-I/O ist best effort. Fehlende Daten bleiben unbekannt;
  Prozesshistorien sind begrenzt und keine garantierte lückenlose Ereignisspur.
- Explizit erzwungene Recovery behält ihre unterbrechende Wirkung. Ein Prozessneustart
  nach abruptem Kill wird nicht durch normale Python-Finally-Blöcke abgewickelt.
- Bestehende automatische Chat-Websuche verwendet einen Privacy-Denylist-Ansatz,
  keine vollständige DLP-Garantie; diese bekannte Produktgrenze bleibt dokumentiert
  in [V2 Live Intelligence](V2_LIVE_INTELLIGENCE.md).
- Browser-Acceptance nutzt den echten Webprozess mit isoliertem Agent-Fixture.
  Die Live-Benchmarks prüfen echte Agent-/Modell-Inferenz, aber keine vollständige
  neue native Bild-/Video-/Speech-Produktionsgenerierung.

## 11. Release-Empfehlung

**NOT READY.** Die verpflichtende Performance-Abnahme und die manuelle
Faktenqualitätsabnahme scheitern trotz grüner Tests und CI. Das Ergebnis
rechtfertigt weder eine Produktionsfreigabe noch
die schwächere Einstufung `CONDITIONALLY READY` für bloß nichtkritische Einschränkungen.

Vor einem Release müssen die genehmigten Suchprovider wieder verwertbare
Ergebnisse liefern, die zusätzlichen Recherche-/Planungsschritte unter Erhalt
der Quellenprüfung reduziert und mindestens fünf reale Wiederholungen je
relevanter Frage erneut gemessen werden. Die Verfügbarkeitsstatus müssen in
einer manuellen Quellenprüfung ausdrücklich korrekt getrennt sein. Der
45-s-Zielwert darf nicht durch Weglassen notwendiger Qualitätsprüfungen entstehen.
Kein eigenständiger Merge nach `main` und kein Release-Tag wurden ausgeführt.

## 12. Git-Commits und PR-Link

- `6e74dac`: Shared-Lease-, Recovery-, Cancellation-, Quellen- und JSON-Härtung,
  neue Regressionstests und Benchmark-Telemetrie.
- `64043b9`: Verfügbarkeitstermine ohne wiederholtes Jahr erhalten.
- `fe0f540`: Hersteller-Domain statt untrusted „offiziell“-Titel im Fastpath verlangen.
- Nachfolgender Dokumentationscommit: dieser Abschlussbericht, keine weitere
  Änderung am gemessenen Produktionscode.
- Bestehender [Pull Request #202](https://github.com/nfekete82/mlx-nobby/pull/202).

Lokale Rohdaten, Berichte, Prüfprotokolle und der isolierte Server-Harness bleiben
unter `artifacts/performance/v2-final-validation/` erhalten. Das Verzeichnis wird
absichtlich nicht versioniert; öffentliche Dokumentation enthält nur notwendige
aggregierte Messwerte und keine Prompts, Artikelvolltexte oder lokalen Modellpfade.
