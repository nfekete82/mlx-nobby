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

## EML-Anonymisierung aus dem normalen Chat

Auch direkt im Chat möglich (die bestehende Seite `/eml-anonymizer` bleibt erhalten):

1. Im Plus-Menü `EML-Dateien hinzufügen` oder `EML-Ordner hinzufügen` wählen. Alternativ `.eml`-Dateien mit der normalen Büroklammer auswählen oder auf den Composer ziehen.
2. Im Eingabefeld `Anonymisiere diese EML-Dateien.` absenden. Ohne ausdrücklichen Anonymisierungswunsch startet **kein** EML-Auftrag.
3. Die Dateien werden sequentiell an `/api/eml-anonymizer/upload` übertragen, anschließend startet `/api/eml-anonymizer/start` die vorhandene lokale Warteschlange.
4. Wartestatus und einen Link zur ZIP-Ausgabe zeigt Nobby direkt im Chat an. Für Details, Pause, Retry, Löschung und ZIP-Export bleibt `/eml-anonymizer` nutzbar.

Die normalen Chat-/LLM-Endpunkte erhalten **keinen EML-Inhalt** und die Dateien werden **nicht** im Chatverlauf oder im Browser-Storage gespeichert. Das Protokoll enthält nur den Prompt und eine zusammenfassende Rückmeldung, keine Dateinamen oder E-Mail-Texte. Ein fehlerhafter Upload lässt noch nicht hochgeladene Dateien ausgewählt und überspringt beim erneuten Absenden bereits erfolgreiche Uploads. Die manuelle Qualitätsprüfung bleibt zwingend, vor allem bei freien Namen, Zitaten und indirekten Personenbezügen.

Max. 30 MiB je Datei; die bestehende EML-Pipeline begrenzt den gespeicherten Gesamtbestand auf 20 GiB. Originale und Ergebnisse liegen im persistenten lokalen Docker-Volume. Lokale KI-Prüfung optional per Checkbox; bei großen Beständen langsamer.

Tests: `node --test tests/test_chat_eml_batch.mjs` sowie `./scripts/mlx test-quick tests/test_eml_anonymizer.py`.
