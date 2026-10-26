# Lokale EML-Stapel-Anonymisierung

MLX-Nobby bietet unter /eml-anonymizer (Chat-Plusmenü: E-Mail-Anonymisierung) einen eigenständigen Import für einzelne und viele EML-Dateien. FAQ-Erstellung ist nicht enthalten.

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

## Anonymisierung über normale Chat-Anhänge

Die EML-Dateien werden genauso angehängt wie andere Dateien. `/eml-anonymizer` bleibt nur für Fortschritt, Pause, Wiederholung, Export und gezieltes Löschen erhalten.

1. Im normalen Chat auf `+ → Datei hinzufügen` klicken und eine oder viele `.eml` auswählen. Auch Drag & Drop funktioniert. Mit `+ → Dateiordner anhängen` können alle EML-Dateien aus einem lokalen Ordner ausgewählt werden.
2. Die Dateien erscheinen als **gewöhnliche Anhang-Chips** mit Name, Größe und Entfernen-Schaltfläche. Bei mehr als 20 EMLs wird nur eine Vorschau mit Gesamtzähler gerendert.
3. Danach den **eigenen Prompt** eintippen, z. B. `Anonymisiere diese E-Mails.` oder `Anonymisiere diese E-Mails mit lokaler KI.`. Nobby startet nicht automatisch beim Anhängen.
4. Bei einem expliziten Anonymisierungswunsch werden die Originaldateien einzeln an die lokale `/api/eml-anonymizer/upload`-API gesendet; anschließend wird `/api/eml-anonymizer/start` aufgerufen. Einfache Anonymisierung ist Standard, `mit lokaler KI` aktiviert die ergänzende Namen- und Orte-Erkennung. **Andere frei formulierte EML-Aufträge werden derzeit noch nicht ausgeführt.** Individuelle Redaktionsregeln im Prompt werden derzeit nicht interpretiert.
5. Nobby bestätigt den Import im Chat und bietet einen Link zur vorhandenen Status- und ZIP-Export-Seite. Bei einem teilweisen Upload-Fehler verbleiben die nicht hochgeladenen Anhänge zur erneuten Übertragung. Erfolgreich importierte Dateien werden nicht doppelt hochgeladen.

Aus Datenschutzgründen werden Dateiinhalte und Dateinamen **nicht in den Chatverlauf oder den LLM-Prompt übernommen**; sie sind lediglich während der Auswahl als Anhang-Chips im aktuellen Browserfenster sichtbar. Die Chat-Historie enthält nur den eingegebenen Prompt und eine abstrakte Rückmeldung mit Dateianzahl. Keine EML-Bytes im Browser-Storage.

Die normale Chat-Nachrichtenverarbeitung mit Bildern, PDF und Textdateien bleibt unverändert. EMLs dürfen derzeit nicht zusammen mit anderen Anhangstypen in derselben Nachricht verarbeitet werden. Max. 30 MiB pro Datei, 20 GiB gespeicherter Gesamtbestand im vorhandenen lokalen Docker-Volume. Auch nach KI-Nachprüfung ist das Ergebnis **prüfpflichtige Pseudonymisierung, nicht garantierte Anonymisierung**. Vor externem Teilen jede Ausgabe kontrollieren; Anhänge werden aus dem Export entfernt.

Tests: `node --test tests/test_chat_eml_batch.mjs` und `./scripts/mlx test-quick tests/test_eml_anonymizer.py`.
