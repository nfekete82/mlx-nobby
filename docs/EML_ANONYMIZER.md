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

Der Chat erkennt den FAQ-Wunsch auch ohne das Wort „anonymisieren“ und führt aus Datenschutzgründen **immer zuerst die lokale EML-Anonymisierung aus**. Anschließend erzeugt ausschließlich das **lokale** MLX-Chatmodell bis zu zwei FAQ-Entwürfe pro EML, maximal aus den ersten 10.000 Zeichen des bereits anonymisierten Textes. Es darf keine nicht belegte Lösung behaupten: Reklamationen ohne nachgewiesenen Abschluss werden als „offen“ gekennzeichnet. Reine Höflichkeitsnachrichten erzeugen keine FAQ.

Im Chat werden Fortschritt, bestehender EML-/ZIP-Download und bei verfügbaren Einträgen zusätzlich **FAQ-Entwurf (Markdown) herunterladen** angezeigt. Die UTF-8-Datei enthält Kategorie, Frage, Antwort und Bearbeitungsstatus. Doppelte identische Frage-Antwort-Paare werden beim Export zusammengeführt. Nicht erreichbare Modelle oder ungültige Antworten führen zu sichtbaren FAQ-Fehlern, **nicht zu erfundenen Antworten**. Die anonymisierten EML-Dateien stehen weiterhin zum Download.

Der FAQ-Prozess ist für größere Bestände rechenintensiv; pro E-Mail wird eine weitere lokale Modellanfrage benötigt. Der Nutzer-Prompt dient derzeit zur Wahl des EML-Anonymisierungs- und optionalen FAQ-Modus, nicht zur beliebigen Neu-Definition sämtlicher Filterregeln. FAQ-Ausgaben bleiben **Entwürfe mit zwingender fachlicher und Datenschutzprüfung**. Die lokale KI kann versehentlich noch identifizierende Angaben übernehmen. Vor externer Nutzung prüfen.

### Umlaute und Zeichencodierung

Der MIME-Parser bevorzugt korrektes UTF-8 auch dann, wenn ein älterer Client den Body als ISO-8859-1 oder CP1252 bezeichnet. Für Legacy-Bytes werden deklarierte und gängige westliche Zeichensätze ausprobiert. Erkennbar falsch dekodierte Folgen wie `GrÃ¼ße` werden vorsichtig repariert. Die exportierten EMLs sind MIME-konform mit UTF-8, der FAQ-Entwurf ist UTF-8-Markdown. Sehr stark beschädigte oder gemischt kodierte Originale müssen weiterhin manuell kontrolliert werden.

FAQ-Status und Daten sind pro Chat-Auftrag im lokalen SQLite-Bestand gespeichert und werden bei `/api/eml-anonymizer/batch/{batch_id}/faq` ausgegeben. Bei `purge` werden auch die FAQ-Zwischenstände gelöscht.

Tests: `./scripts/mlx test-quick tests/test_eml_anonymizer.py` und `node --test tests/test_chat_eml_batch.mjs`.
