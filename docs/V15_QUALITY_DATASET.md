# V15: eingefrorener Qualitätsdatensatz

`tests/fixtures/v15_quality_cases.json` enthält 64 unabhängig beschriftete Claims und 36 Quellenfixtures. Die semantischen Sollwerte wurden vor Anbindung an die neue Evidence-Implementierung festgelegt. Sie sind eine überprüfbare Bewertungsgrundlage, keine Behauptung, dass die Software freie Prosa bereits semantisch verifizieren kann.

24 Fälle beziehen sich auf kurze, am 11. Oktober 2026 per Browser überprüfte Auszüge aus sechs offiziellen Quellen: [NASA](https://science.nasa.gov/mars/moons/), [Python](https://www.python.org/downloads/release/python-3130/), [PostgreSQL](https://www.postgresql.org/about/news/postgresql-17-released-2936/), [CERN](https://home.cern/science/computing/the-birth-of-the-web/), [Nintendo](https://www.nintendo.com/us/whatsnew/nintendo-switch-2-launches-june-5-bringing-new-forms-of-game-communication-to-life/) und [Raspberry Pi](https://www.raspberrypi.com/news/introducing-raspberry-pi-5/). Die Fixtures speichern höchstens 25 Wörter je Originalseite. Zeilenumbrüche zwischen Überschrift und Datumsangabe sind normalisiert. Nintendo-Jahreszuordnung verwendet das dokumentierte Veröffentlichungsdatum. Raspberry-Pi-Modellzuordnung verwendet den dokumentierten Seitentitel. Spätere Änderungen der Originalseiten ändern diese eingefrorenen Testdaten nicht.

Weitere 40 Fälle prüfen ausdrücklich selbst verfasste adversarielle Szenarien. Ihre URLs auf `example.org` sind reservierte Testadressen; es werden keine erfundenen offiziellen Veröffentlichungen zitiert. Manipulierte Publisher-Metadaten und abweichende Redirect-Ziele sind absichtlicher Bestandteil dieser Fixtures. Die Fixtures werden niemals über das Netzwerk geladen.

Jeder Fall enthält Aussage, Quellen-IDs, Stichtag, Sollstatus und eine eigene Begründung. Abgedeckt sind Astronomie, Technikgeschichte, Softwareversionen, Konsolen und Einplatinencomputer sowie Verfügbarkeit, regionale Unterschiede, Vorbestellung, Preise, Modellzuordnung, Maßeinheiten, Populationen wissenschaftlicher Studien, zeitliche Einschränkungen, widersprüchliche Quellen, nur teilweise belegte Listen, Webseitenanweisungen, falsche Herkunft, RSS, fehlende Artikel, Rate-Limit, CAPTCHA, Cancellation und private Redirect-Ziele.

## Auswertung und Grenzen

Die fünf semantischen Goldstatuswerte sind `supported`, `contradicted`, `insufficient_evidence`, `conflicting_evidence` und `not_checked`. Ein exaktes Quellenzitat weist nach, was diese Quelle sagt; es beweist weder die Wahrheit des Inhalts noch beliebige daraus abgeleitete Aussagen. Eine nicht vorhandene semantische Verifikation muss `not_checked` bleiben. Sie darf nicht durch Umbenennung der Goldwerte als korrekte Faktenprüfung gezählt werden.

Die Tests prüfen Herkunft, Vielfalt und Bewertungslogik. `semantic_metrics` berechnet Genauigkeit, Präzision und Recall unterstützter Aussagen sowie Prüfungsabdeckung. Fehlende Ergebnisse zählen als Fehler. Eine pauschale Verweigerung oder eine pauschale Einstufung als unzureichend hat Recall null. Auch die pauschale Bestätigung aller Aussagen scheitert. Ein Test der Bewertungslogik gegen die eigenen Goldlabels ist ausdrücklich **keine Messung der Qualität des Agenten**.

Eine spätere semantische Auswertung muss echte, unveränderte Pipeline-Ergebnisse gegen diese eingefrorenen Goldlabels vergleichen und Fehlfälle einzeln berichten. Dokumentierte Quote-/Quellenintegrität und semantische Qualität müssen getrennte Kennzahlen bleiben. Dieser Datensatz ersetzt weder eine menschliche Antwortbewertung noch Live-Recherche unter dokumentierten Umgebungsbedingungen.

## Gemessene Grenze des reinen Quote-Verifiers

Der gezielte Testlauf `test-venv/bin/python -m pytest -q tests/test_v15_quality_dataset.py` bestand mit 78 Tests. Darunter sind sechs echte eingefrorene Quellenzitate mit Manipulations- und Offsetprüfungen sowie ausführbare Prüfungen für falsche Herkunft, RSS, private Redirects, teilweise Auswahl mit eigener Quellenangabe, erfundene Auswahl-IDs und escaped dargestellte Webseitenanweisungen. Dass eine Anweisung sicher zitiert wird, bedeutet nicht, dass ihre Auswahl inhaltlich hilfreich ist.

Die Goldverteilung beträgt 18 unterstützte, 19 widersprochene, 24 unzureichend belegte, zwei widersprüchlich belegte und eine nicht überprüfbare Aussage. Der reine Quote-Verifier gibt für alle 64 freien semantischen Aussagen korrekt seine technische Grenze `not_checked` zurück. Gegen die unveränderte semantische Bewertungsaufgabe ergeben sich dadurch **0 % Prüfungsabdeckung, 0 % Recall unterstützter Aussagen und 1,56 % Labelgenauigkeit**. Diese Werte zeigen eine noch offene semantische Verifikation; sie sind keine erfolgreiche Faktenqualitätsabnahme. Die Integritätsprüfungen für Quellenzitate werden davon getrennt betrachtet.


## Modellgestützte semantische Auswertung

`agent/v15_quality_benchmark.py` ruft denselben `verify_candidates`-Verifier wie die neue Recherchepipeline auf. Er verarbeitet höchstens acht Claims je Batch. Die semantischen Goldlabels und Begründungen werden dem Modell nicht gegeben. Jeder Claim erhält ausschließlich seine eigenen eingefrorenen Quellenpassagen; andere Fälle im selben Batch dürfen keine Belege beisteuern. Fehlgeschlagene Abrufe, RSS-Wrapper und private Redirect-Ziele liefern keine zugelassenen Passagen.

Beispiel mit neuen, noch nicht existierenden Ausgabedateien:

```sh
test-venv/bin/python -m agent.v15_quality_benchmark \
  --output /tmp/mlx-v15-quality-report.json \
  --raw-output /tmp/mlx-v15-quality-raw.jsonl
```

Der Aufruf verwendet den vorhandenen nativen ModelProvider mit RunContext, gemeinsamer Runtime-Lease, Modellsperre und RAM-Guard. Die App-Daten werden bereits vor ihrem Import in ein separates temporäres Home-Verzeichnis isoliert; vorhandene Modellkonfiguration und Rollen werden gelesen. Strikte JSON-Prompts deaktivieren die Gedächtnisanreicherung. Ausgabeziele werden exklusiv vor dem App-Import geöffnet. Bestehende Berichte und Rohdaten werden nicht überschrieben.

Der Bericht enthält die unveränderten Sollwerte, individuelle Entscheidungen, Konfusionsmatrix, Genauigkeit, Supported-Präzision und Recall, Abdeckung und Fehlerzahl sowie tatsächliche Modellaufrufe, Token- und Zeitmetriken. Rohdaten bewahren die an das Modell übergebenen öffentlichen Fixtures und dessen echte Antworten. Dataset- und Implementierungs-Hashes identifizieren den gemessenen Stand.

Diese Messung bewertet **modellgestützte Quellenentailment-Urteile gegen eingefrorene menschliche Labels**. Sie misst keine unabhängige Weltwahrheit, keine Suchqualität, keine automatisierte Claim-Extraktionsqualität und keine vollständige Antwortnützlichkeit. Eine Messung ist erst nach tatsächlichem nativen Lauf vorhanden; erfolgreiche Offline-Tests des Benchmark-Programms sind kein solches Ergebnis.
