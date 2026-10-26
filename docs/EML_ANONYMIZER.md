# Lokale EML-Stapel-Anonymisierung

MLX-Nobby bietet unter /eml-anonymizer (Chat-Plusmenü: E-Mail-Anonymisierung) einen eigenständigen Import für einzelne und viele EML-Dateien. FAQ-Entwürfe können jetzt per kombiniertem Prompt aus den anonymisierten E-Mails erzeugt werden.

## Ablauf

1. Dateien per Mehrfachauswahl, Verzeichniswahl oder Drag & Drop auswählen.
2. Der Browser überträgt sie einzeln an die lokale Web-Instanz; kein Chat-Kontext.
3. Optional das lokale Chatmodell zur zusätzlichen Namen-/Orte-Erkennung verwenden.
4. Starten: Die Warteschlange verarbeitet jeweils eine E-Mail. Pausieren wirkt nach der laufenden Nachricht.
5. ZIP mit email-000001.eml usw. und ANONYMIZATION-REVIEW.json herunterladen.
6. Nach der Prüfung können alle importierten Originale und Resultate aus dem Volume gelöscht werden.

Die anonymisierten Ausgaben sind neu erstellte Text-EML-Dateien. Originale MIME-Header, eingebettetes HTML, Bilddaten und sämtliche Anhänge werden nicht exportiert. Fachtext bleibt weitgehend erhalten. Jede Ausgabe ist zwingend manuell zu prüfen, nicht als garantiert anonym deklariert.

Originale und Ausgaben liegen in einem persistenten lokalen Docker-Named-Volume (eml-local), getrennt vom Chat-Verlauf. Die Webinstanz ist an 127.0.0.1 gebunden. Die bestehende Origin-Schutzschicht ersetzt keine Benutzer-Authentifizierung: Personen mit Host- oder Docker-Zugang können die Originale lesen. Export-Dateinamen enthalten keine ursprünglichen Namen.

Der KI-Modus benutzt ausschließlich den lokalen MLX-Agent-Bridge-Port 8010 und bittet das aktuelle lokale Chatmodell um exakte Namen und Orte. Es übernimmt nicht die gesamte Neufassung des Texts. Scheitert die KI-Erkennung, gibt die Pipeline ein regelbasiertes Ergebnis mit Warnung aus. Bei Nachrichten über 12.000 Zeichen prüft die KI nur den Anfang.

## Betriebsgrenzen

- Maximal 30 MiB pro EML, insgesamt 20 GiB pro Arbeitsbestand.
- Ein Upload nach dem anderen, in jeweils höchstens 1 MiB großen Chunks.
- SQLite-Queue im lokalen Docker-Volume; unterbrochene Nachrichten werden wieder angestellt.
- ZIP wird auf Platte erstellt. Für große Exporte ist zusätzlicher freier Platz nötig.
- Fehlerhafte E-Mails werden nicht gelöscht. Fehlerstatus enthält keine Originaldaten.

## Installation

cd ~/mlx-web
git fetch origin main
git merge --ff-only origin/main
./scripts/mlx test-quick tests/test_eml_anonymizer.py
MLX_NOBBY_BUILD_SHA="$(git rev-parse --short HEAD)" docker compose up -d --build mlx-web

Im Browser http://127.0.0.1:8090/eml-anonymizer öffnen.

## Datenschutz

RegEx und LLM können Namen, indirekte Identifikatoren und andere personenbezogene Informationen übersehen. Ergebnisse vor externer Verwendung manuell prüfen. Anhänge werden nicht anonymisiert, sondern komplett ausgelassen. Vor einem Docker-Rebuild die Batch-Verarbeitung pausieren.

## EML im normalen Chat bearbeiten

1. Auf `+ → Datei hinzufügen` klicken und eine oder mehrere `.eml`-Dateien auswählen. Einen **ganzen Ordner per Drag & Drop auf den Chat-Composer ziehen**. Der Browser-Dateidialog selbst kann nicht gleichzeitig Dateien und Ordner als gleichartige Auswahl anbieten; deshalb ist für ganze Ordner das Ziehen vorgesehen. Der gesonderte Ordner-Menüpunkt entfällt.
2. Die EML-Dateien erscheinen als normale Chat-Anhänge, der Chat-Prompt bleibt frei. Eingabe: `Anonymisiere diese E-Mails und entferne unnötige Signaturen.` Optional: `mit lokaler KI`.
3. Nobby zeigt im Chat während des Uploads `x/y`, anschließend während der tatsächlichen sequentiellen Anonymisierung `x/y fertig`. Bei Einzeldateien erscheint nach Fertigstellung ein direkter EML-Download-Link; bei Stapeln ein **nur auf diesen Auftrag begrenzter ZIP-Download-Link**.
4. Es handelt sich weiterhin um denselben bestehenden regelbasierten Anonymisierer (mit optionaler lokaler Namen-/Orte-KI). **Der freie Prompt wird derzeit nicht als frei konfigurierbare Redaktionsanweisung ausgeführt.** Standardmäßig werden Signaturen und unnötige Fußtexte nach bestehenden Regeln entfernt. Weitere Einzelanweisungen wirken nur, wenn der Anonymisierer sie bereits unterstützt.
5. Alle Ergebnisse sind als `review_required` markiert. Vor Weitergabe ist eine menschliche Prüfung erforderlich. Die ZIP enthält eine Prüfdatei, kann keine Garantie der Unidentifizierbarkeit liefern und lässt Originalanhänge weg.

Technik: Uploads erhalten eine zufällige Stapel-ID. `/api/eml-anonymizer/batch/{batch_id}/status`, `/result` und `/export` grenzen Status, EML und ZIP auf exakt diesen Stapel ein. Alte Daten bleiben separat im persistenten Docker-Volume. Ein späteres Nachladen eines anderen Chats oder das Schließen der Browserseite stoppt den serverseitigen Worker nicht; die **Live-Anzeige** ist dagegen nur in der aktiven Seite aktuell. Weitere Steuerung, Fehler und Löschung sind unter `/eml-anonymizer` möglich.

Verarbeitung: maximal 30 MiB pro EML, 10.000 gleichzeitig angehängte EML-Dateien, maximal 20 GiB Gesamtspeicher des Bestands. Die Inhalte werden nur zum lokalen Anonymisierer hochgeladen, nicht als Text an das LLM gesendet oder im Chatverlauf abgelegt. Im gespeicherten Chat stehen nur Prompt, Fortschritt und Download-Link. Bei Importfehlern bleiben die noch nicht hochgeladenen EML-Anhänge zur Wiederholung erhalten.

Tests: `node --test tests/test_chat_eml_batch.mjs`, `./scripts/mlx test-quick tests/test_eml_anonymizer.py` und Browser-CI.


## FAQ direkt im Chat erstellen

Eine oder mehrere `.eml` über **Datei hinzufügen** hochladen, einen Ordner auf den Chat ziehen und zum Beispiel schreiben:

`Anonymisiere diese E-Mails, entferne Signaturen und erstelle aus den fachlichen Fragen und Antworten eine FAQ.`

Der Chat erkennt den FAQ-Wunsch auch ohne das Wort „anonymisieren“ und führt aus Datenschutzgründen **immer zuerst die lokale EML-Anonymisierung einschließlich lokaler KI-Namenserkennung aus**. Anschließend erzeugt ausschließlich das **lokale** MLX-Chatmodell bis zu zwei FAQ-Entwürfe pro EML, maximal aus den ersten 10.000 Zeichen des bereits anonymisierten Textes. Es darf keine nicht belegte Lösung behaupten: Reklamationen ohne nachgewiesenen Abschluss werden als „offen“ gekennzeichnet. Reine Höflichkeitsnachrichten erzeugen keine FAQ.

Bei einem FAQ-Auftrag wird im Chat **eine einzige, gemeinsame FAQ-Datei als Markdown** zum Hauptergebnis. Der ZIP-Download mit anonymisierten Einzel-EMLs ist nur noch eine optionale Sicherung. Ein nachgelagerter lokaler KI-Schritt bündelt ähnliche Fragen thematisch und kennzeichnet widersprüchliche und offene Fälle konservativ. Die FAQ enthält Frage, Antwort, Kategorie und Bearbeitungsstatus. Bei großen Datenmengen erfolgen KI-Aufrufe in kleinen Gruppen (maximal acht Einträge, zwei Zusammenfassungsrunden pro Kategorie); gruppenübergreifende Duplikate können daher weiterhin vorkommen. Nicht erreichbare Modelle oder ungültige Antworten führen zu sichtbaren FAQ-Fehlern, **nicht zu erfundenen Antworten**. Die anonymisierten EML-Dateien stehen weiterhin zum Download.

Der FAQ-Prozess ist für größere Bestände rechenintensiv; pro E-Mail wird eine weitere lokale Modellanfrage benötigt. Der Nutzer-Prompt dient derzeit zur Wahl des EML-Anonymisierungs- und optionalen FAQ-Modus, nicht zur beliebigen Neu-Definition sämtlicher Filterregeln. FAQ-Ausgaben bleiben **Entwürfe mit zwingender fachlicher und Datenschutzprüfung**. Die lokale KI kann versehentlich noch identifizierende Angaben übernehmen. Vor externer Nutzung prüfen.

### Umlaute und Zeichencodierung

Der MIME-Parser bevorzugt korrektes UTF-8 auch dann, wenn ein älterer Client den Body als ISO-8859-1 oder CP1252 bezeichnet. Für Legacy-Bytes werden deklarierte und gängige westliche Zeichensätze ausprobiert. Erkennbar falsch dekodierte Folgen wie `GrÃ¼ße` werden vorsichtig repariert. Die exportierten EMLs verwenden MIME-konformes UTF-8 mit lesbarem 8bit-Textkörper (nicht mehr Quoted-Printable), der FAQ-Entwurf ist UTF-8-Markdown. Sehr stark beschädigte oder gemischt kodierte Originale müssen weiterhin manuell kontrolliert werden.

FAQ-Status und Daten sind pro Chat-Auftrag im lokalen SQLite-Bestand gespeichert und werden bei `/api/eml-anonymizer/batch/{batch_id}/faq` ausgegeben. Bei `purge` werden auch die FAQ-Zwischenstände gelöscht.

Tests: `./scripts/mlx test-quick tests/test_eml_anonymizer.py` und `node --test tests/test_chat_eml_batch.mjs`.

### Gemeinsame FAQ und Fehlerbehandlung

Die Chat-Verarbeitung startet nach der Anonymisierung per `/api/eml-anonymizer/batch/{batch_id}/consolidate` einen Hintergrund-Zusammenfassungsauftrag. Über den Batch-Status steht `faq_merge_state` bereit. Bei `ready` bietet `/batch/{batch_id}/faq` die Datei `FAQ-Gemeinsam-Entwurf.md`. Kein erneuter Upload der ursprünglichen Dateien ist nötig. Startaufrufe sind idempotent, der Download bleibt im lokalen Daten-Volume. Bei KI-Fehlern entsteht keine vermeintlich fertige FAQ; der Chat zeigt die Störung an, die einzeln anonymisierten EMLs bleiben zugänglich. Alle FAQ-Entwürfe sind weiterhin fachlich und datenschutzrechtlich prüfpflichtig.


## Verlässlicher FAQ-Fortschritt und Wiederaufnahme

Die gemeinsame FAQ-Erstellung arbeitet jetzt mit **dauerhaft gespeicherten Modellschritten** in `faq_merge_steps` (SQLite im lokalen EML-Volume). Nach jedem Modellaufruf werden Ergebnis und gemessene Verarbeitungsdauer gemeinsam transaktional gespeichert. Bei Unterbrechung, Docker-Neustart oder fehlgeschlagenem Modellaufruf bleiben diese Teilresultate erhalten. Der gerade unterbrochene Aufruf wird neu durchgeführt, fertige Schritte werden aus dem Checkpoint übernommen. Nach Neustart ändert `setup()` ein zuvor laufendes FAQ-Merge auf `queued`. Beim nächsten Aufruf von `GET /api/eml-anonymizer/status` oder der Batch-Statusroute fährt der Server die Warteschlange automatisch wieder hoch. Mehrere FAQ-Merges werden lokal **nacheinander** ausgeführt. Ein fehlgeschlagener Batch kann über `POST /api/eml-anonymizer/batch/{batch_id}/consolidate` ohne neue EML-Uploads fortgesetzt werden. Der Aufruf liefert `queued`, `processing` oder `ready`. Bestehende fertige FAQ-Downloads werden wiederverwendet.

Während der Verarbeitung liefert `GET /api/eml-anonymizer/batch/{batch_id}/status` zusätzlich:
- `faq_merge_completed`, `faq_merge_total`, `faq_merge_percent`: tatsächlich dauerhaft gespeicherte Teilverarbeitung
- `faq_merge_eta_seconds`: **geschätzte** Restzeit aus den gemessenen Laufzeiten fertiger Schritte, zunächst `null`; wird bei Beginn der zweiten Runde an deren tatsächlichen Umfang angepasst
- `faq_merge_elapsed_seconds`: verstrichene Zeit seit Start (einschließlich Unterbrechungen)
- `faq_merge_current_step_seconds`: Dauer des aktuellen Modellaufrufs; `faq_merge_slow` meldet auffällig lange Laufzeit, beweist keinen Hänger
- `faq_merge_state`: `not_started`, `queued`, `processing`, `ready`, `failed`

Der normale Chat zeigt während der FAQ-Zusammenfassung Fortschrittsbalken, Prozent, X/Y, Laufzeit, geschätzte Restzeit und Hinweise auf langsame Schritte. Die Anzeige wird beim aktiven Chat alle zwei Sekunden aktualisiert. Schließt man den Tab, läuft der Backend-Auftrag weiter, aber die alte Chat-Nachricht lädt ihren Fortschritt derzeit nicht automatisch nach; der Status kann direkt über die Batch-Status-URL eingesehen werden.

**Migration bestehender Langläufer:** Einen noch laufenden Auftrag aus einer Version *ohne* Checkpoints zuerst abschließen lassen. Ein Docker-Rebuild beendet dessen bisherige ungesicherte Modellarbeit; das neue System kann alte, während der Verarbeitung nicht gespeicherte Schritte nicht rückwirkend rekonstruieren. Die bereits erzeugten anonymisierten EMLs und einzelnen FAQ-Entwürfe bleiben erhalten, sodass nach dem Update kein erneuter EML-Upload nötig ist. Das Zusammenführen kann für diesen Batch über `/consolidate` neu gestartet werden. Einträge können weiterhin personenbezogene Informationen enthalten; FAQ-Ausgaben bleiben strikt prüfpflichtig.
