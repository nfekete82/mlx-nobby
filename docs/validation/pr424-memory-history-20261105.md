# PR #424: Prüfung des Langzeitgedächtnisses mit echten lokalen Quellen

**WIP — keine Produktivfreigabe. Arbeit auf ausdrücklichen Wunsch beendet.**

Nachtrag: Der damals offene Legacy-Deadline-Fehler wurde anschließend gezielt
[nachgewiesen und korrigiert](pr424-legacy-deadline-20261105.md).
Der folgende Bericht dokumentiert weiterhin den damaligen WIP-Stand.

Testdatum: **5. November 2026** (Europe/Berlin). Kein Merge, Deployment,
Modellwechsel, Neustart oder Schreibzugriff auf produktive Originaldaten.
Die Anwendung auf 8090/8010 wurde für diese Abnahme nicht angesprochen.

## Ursachen und zusammenhängende Korrektur

| Pipeline-Stufe | Ursache | Änderung |
| --- | --- | --- |
| Quellen | Historische Verarbeitung las nur die neueste Tresorversion; `.revisions` wurde übergangen. | Alle aufbewahrten Revisionen sind lesbar und anhand Chat, Ordinal und Inhaltsdigest für den Worker validierbar. Die Seitenleiste wird nicht wiederhergestellt. |
| Quellenzugang | Frühere, inzwischen entfernte Chats lagen noch in Backups und Browser-Speichern. | Lesende Inventur und Prüfung; eindeutige Quellen ausschließlich in den privaten Test-Tresor kopiert. Kein automatischer produktiver Browser-/Backup-Import. |
| Vollständigkeit | Versionslose `smart_observed`-Hashes konnten unvollständige frühere Extraktionen endgültig überspringen. | Nur abgeschlossene Segmentaufträge der aktuellen Extraktorversion gelten als verarbeitet. Alte Marker und Ergebnisse bleiben erhalten. |
| Entdeckung | Eine volle Weckwarteschlange konnte die weitere Einplanung abbrechen; Fortschritt war flüchtig. | Erst SQLite-Aufträge festschreiben, danach bestmöglich die begrenzte Warteschlange wecken. Fortschritt, Entdeckungsphase und Fehler bleiben in SQLite. |
| Wiederaufnahme | Fehler blieben bis zum manuellen Neustart liegen; Modellprosa konnte gültiges JSON verdecken. | Pending-Aufträge werden nach Prozessstart wiedergefunden; maximal drei automatische Versuche mit Abstand. Formatfehler erhalten eine strengere Ausgabevorgabe. Ein vollständiges Schemaobjekt darf von verworfener Modellprosa eingerahmt sein; mehrere/abgebrochene Objekte bleiben Fehler. |
| Segmentkontext | Ein Projekt oder eine Person kann ausschließlich am Anfang einer langen Nachricht benannt sein. | Spätere Segmente erhalten begrenzten vorherigen Nutzer- und Nachrichtenkontext. Werte und Belege müssen weiterhin im tatsächlich bearbeiteten Segment stehen. |
| Speicherung | Eine Quelländerung entfernte frühere Evidenz, Episoden und Jobs. | Unveränderliche Quellrevisionen erhalten diese Daten; neue Versionen ergänzen sie. |
| Speicherung | Ergänzende Qualifikationen, Aufgaben, Technologien oder Ziele wurden als derselbe Einzelwert behandelt. | Unabhängige Werte erhalten stabile getrennte Schlüssel; Spitznamen sind vom vollständigen Namen getrennt. Äquivalente Geburtstagsformate erzeugen keine neuen Widersprüche. |
| Evidenz | Bei einem widersprüchlichen Vorschlag blieben nur der kurze Wert und eine Ordinalreferenz, nicht der genaue Beleg. | Additive `conflict_evidence`-Tabelle; Vorschlagsbelege werden aufbewahrt, indexiert, exportiert und bei passenden Fragen zitiert. |
| Index | Relevante Wörter konnten nur in der Evidenz vorkommen, nicht im kurzen Wert. | Faktenindex enthält auch die gespeicherte Fakten- und Widerspruchsevidenz. Bestehende Exporte bleiben importierbar. |
| Abruf | Explizite Fragen konkurrierten mit Embeddings; Vergangenheitsformen wurden teilweise als normaler Chat behandelt. | Eigener begrenzter SQLite-/FTS-Pfad für ausdrückliche Erinnerungsfragen, einschließlich Vergangenheitsformen und benannter Personen. Kein Embedding-Start davor. |
| Rangfolge | FTS-Treffer deutscher Komposita konnten in der anschließenden Sortierung wieder verloren gehen; lange Widerspruchsblöcke verdrängten andere Behauptungen. | Gemeinsame normalisierte Suchbegriffe, FTS-Präfixe und BM25-Gewichtung; eigene Budgetierung einzelner Behauptungen und Vorschläge. |
| Antwort | Zu kurze Belege verloren Zeitangaben oder ergänzende Abschlüsse; ein Geburtsort konnte zum Wohnort werden. | Verifizierte Originalsatz-Erweiterung mit passender Quellrevision; Attributprüfung für Wohnorte; historische Angaben sind als solche gekennzeichnet. |
| Laufender Betrieb | Mehrere neue Nutzerturns in einem Save oder während Pause konnten ungeplant bleiben. | Alle noch unbekannten Nutzerturns werden dauerhaft eingeplant. Pause verhindert Abruf und Inferenz; offene Aufträge bleiben für die Fortsetzung erhalten. |

Die vorhandenen privaten SQLite-Stores, JSON-Quellen, der einzelne lokale
Qwen-Worker und der tatsächliche Chat-Stream bleiben die Architektur. Es gibt
keine neue Datenbank, Cloud-Inferenz oder zweite parallele Gedächtnis-Engine.

## Private Quellensuche

Geprüft wurden lesbare MLX-Installationen und frühere Checkouts, `~/Projects`,
`~/.config`, `~/MLX-Nobby-Backups`, lokale Archive sowie die beiden MLX-bezogenen
Docker-Volumes. Auch eine **Kopie** des Chromium-Local-Storage wurde ausgewertet.
Der dafür separat unter `/private/tmp` geladene
[CCL Chromium Reader](https://github.com/cclgroupltd/ccl_chromium_reader) und seine
Snappy-Abhängigkeit sind keine Anwendungsabhängigkeiten dieses PRs.

- Ausgangsbestand: vier aktuelle Chats, 37 Nutzerturns, 17 Fakten und drei
  offene Widersprüche.
- Sieben weitere geprüfte Chatquellen aus Backups und 13 aus dem Browser wurden
  in die isolierte Testkopie aufgenommen. Identische Kopien und reine ältere
  Präfixe wurden ausgesondert. Insgesamt: 24 unterschiedliche Chat-IDs.
- Die geprüften historischen SQLite-Archive enthielten keine darüber hinaus
  zusätzlichen Nutzerturns. Das Docker-Datenvolume enthielt Mailverarbeitung;
  das weitere MLX-Office-Volume war leer. Sieben untersuchte relevante Archive
  lieferten keine zusätzlichen vollständigen Chat-Exporte.
- macOS verweigerte den Zugriff auf Dokumente/Downloads auch außerhalb der
  Sandbox. Es wird **keine vollständige Suche sämtlicher Mac-Dateien** behauptet.
- In den lesbaren wiedergefundenen Originalchats wurden **keine benannten
  Projektgespräche** gefunden. Projektverzeichnisse oder erzeugte Dateien sind
  kein Beleg dafür, dass ein entsprechendes Chatgespräch stattfand. Es werden
  daraus keine vermeintlichen historischen Projekterinnerungen erfunden.

Private Quellen, Modellantworten, Fragen, Dateipfade und Prüfsummen liegen
außerhalb Git. Öffentliche Dokumentation enthält nur Verfahren und Zähler.

## Durchführung und Nachweise

Modell: bereits ausgewähltes **Qwen3.8-27B-Abliterated-MLX-4bit**, lokaler
MLX-Textserver auf Loopback-Port 8000. Kein anderes Modell wurde geladen.

`accept-memory-history.py` erstellt aus einem privaten Backup eine eigene
isolierte Home-Struktur. Der Test aktiviert die bereits bestehenden optionalen
Gedächtnisschichten ausschließlich dort. Getestet werden echte kopierte
Quellen, Qwen-Extraktion, SQLite-Commit, FTS und Quellenabruf sowie der reale
`MemoryChatMiddleware`- und `runtime_chat_stream`-Pfad bis zu Qwens SSE-Antwort.
Nur Modellwahl und Dienststeuerung im Test sind auf den bereits aktiven
Textserver festgelegt; sie dürfen keine produktiven Dienste umschalten oder
entladen. Embeddings sind für diese Abnahme deaktiviert. Der reguläre
Embedding-Pfad wird durch die Regressionstests geprüft.

Die aktuelle Historienentdeckung untersucht 98 verfügbare Nutzerturns und
plant 97 eindeutige Segmente ein. Davon wurden 61 tatsächlich mit Qwen
analysiert. 36 Segmente bleiben mit ausgewiesenem Ausschlussgrund erhalten;
Generierungsanweisungen sind keine autobiografischen Tatsachen. Quellen
werden dadurch nicht gelöscht. Ein anfänglicher Schemafehler wurde als Fehler
festgeschrieben und im nächsten realen Modellversuch behoben.

Der finale Prozess wurde nach zwei erfolgreichen Segment-Commits mit Exit 75
hart beendet. Nach dem Neustart blieben beide Checkpoints einschließlich
Versuchszähler identisch. Die übrigen Aufträge wurden fortgesetzt. Zusätzlich
wurden die sechs durch verbesserten Kontext betroffenen Folgesegmente langer
Nachrichten gezielt erneut geprüft; ihre vorherige Testdatenbank ist gesichert.

Die erste echte Antwortprüfung bestand 12/16 Fragen; die zweite 15/16.
Diese Fehlversuche werden ausdrücklich nicht als erfolgreiche Abnahme gewertet.
Sie führten zu den oben beschriebenen Evidenz-, Rangfolge- und Absichtskorrekturen.
Die vor dem Arbeitsstopp bereits abgeschlossene letzte Antwortprüfung bestand
**16/16 Fragen** einschließlich der Negativkontrolle fehlender Projektbelege.
Die abschließende lokale Erhaltungsprüfung bestätigt **93 zusätzliche Fakten**,
unveränderte ursprüngliche Fakten-/Widerspruchszeilen, unveränderte Backup-
und Quellprüfsummen sowie erfolgreiche SQLite-Integritäts-/Fremdschlüsselprüfungen.

Prüffragen betreffen unabhängige Angaben zu Identität, Geburtstag, Geburtsort,
Ausbildung, Studium, Arbeitgeber, beruflicher Historie, Kindern, Partnerschaft,
Betreuung, Schlafsituation, Herkunft der Eltern, Geschwistern und historischer
Arbeitslosigkeit. Eine zusätzliche Negativkontrolle verlangt eine ehrliche
Antwort bei fehlenden historischen Projektbelegen. Positive Antworten müssen
zu tatsächlich vorhandenen Chat-IDs verweisen; erforderliche und verbotene
Inhalte werden geprüft und die Antworten anschließend inhaltlich nachgelesen.

## Offener Fehler und letzter Prüfstand

Der letzte vollständige Python-Lauf endete mit **3.986 bestandenen Tests,
einem Fehler und 472 bestandenen Subtests**. Der Fehler ist konkret:

- `tests/test_memory_middleware.py::test_streaming_chat_is_enriched`
- Die synthetische angeheftete Legacy-Erinnerung „Nenn mich Nobby.“ fehlte
  im Systemkontext der normalen Anfrage „Erkläre Docker.“.
- HTTP 200 wurde geliefert; die erwartete Kontextanreicherung fehlte.
- Der einmalige kurze Einzelaufruf nach dem Arbeitsstopp bestand in 0,25 s.
  Damit ist der Fehler im Gesamtlauf **nicht behoben oder abschließend erklärt**.
  Ein Reihenfolge-/Zustands- oder Zeitbudgetproblem ist eine Hypothese, kein
  nachgewiesener Befund. Es wurde keine weitere Optimierungsschleife begonnen.

Der davor erfolgreiche Gesamtlauf mit 3.982 Tests wird nicht mit dem letzten
vollständigen Lauf verwechselt. JavaScript: **408/408** bestanden.
Übersetzungsaudit und Diff-Whitespace-Prüfung bestanden. Die echte letzte
Antwortabnahme und die Erhaltungsprüfung bestanden; die Gesamtsuite ist dennoch
nicht als vollständig grün freigegeben.

Vor einer Produktivfreigabe sind der Fehler im Suite-Kontext zu klären,
der finale Stand durch Review/CI zu bestätigen und eine separat autorisierte
Migration mit überprüftem Backup zu planen. Für einen positiven historischen
Projekt-Nachweis fehlen weiterhin Originalquellen. Auf ausdrückliche Anweisung
wurden keine weiteren langen Tests oder vollständigen Qwen-Analysen gestartet.

## Reproduktion außerhalb produktiver Daten

Ein Backup aus `scripts/backup-local-state.py` wird unterstützt. Private
Snapshots dürfen nicht innerhalb eines Git-Checkouts liegen. Zusätzliche
Quellen werden vorab ausschließlich in dessen isolierten Tresor kopiert.

```bash
python scripts/accept-memory-history.py --snapshot /private/tmp/PRIVATE-SNAPSHOT --phase extract --interrupt-after 2
# Der absichtliche Prozessabbruch liefert Exit 75.
python scripts/accept-memory-history.py --snapshot /private/tmp/PRIVATE-SNAPSHOT --phase extract --resume-jobs-only
python scripts/accept-memory-history.py --snapshot /private/tmp/PRIVATE-SNAPSHOT --phase answers --cases /private/tmp/PRIVATE-QUESTIONS.json
python scripts/accept-memory-history.py --snapshot /private/tmp/PRIVATE-SNAPSHOT --phase verify
```

`--resume-jobs-only` verwendet denselben dauerhaften Jobabruf und die begrenzten
Wiederholungen wie der normale Worker. Der Standard-Extraktionsmodus entdeckt
alle Quellen erneut und erlaubt ausdrücklich auch neue Versuche bereits
fehlgeschlagener Aufträge. Schon erfolgreich abgeschlossene, unveränderte
Aufträge werden übersprungen.

## Grenzen und Freigabe

Keine behauptete Erinnerung kann eine nicht verfügbare Quelle ersetzen.
Ein positiver historischer Projekt-Test ist ohne entsprechende Originalchats
nicht belegbar. Die synthetischen Projektregressionen prüfen Speicherung,
Mehrfachziele, Segmentkontext und Abruf; sie werden nicht als Ersatz für diesen
fehlenden historischen Nachweis ausgegeben.

Wörtliche Evidenz begrenzt erfundene Werte, garantiert aber nicht jede semantische
Zuordnung durch das Modell. Widersprüche bleiben reviewbar. Eine einzelne
Antwort bleibt durch ihr Kontextbudget begrenzt; vollständige Bestandsansichten
sind weiterhin paginiert verfügbar. Die Abnahme belegt die untersuchten Quellen
und Fragen, keine fehlerfreie Erinnerung an beliebige unbekannte Gespräche.

**Kein Merge und kein Deployment.** Die produktive Installation wird durch
Codeentwicklung, Tests oder Push nicht aktualisiert. Ihre Originaldaten und
laufenden Dienste bleiben unangetastet.
