# PR #424: Legacy-Erinnerung im lokalen Gesamttest

Gezielte Fortsetzung auf Basis von `e5ca0500`, 5. November 2026.
Keine historische Neuanalyse, Änderung produktiver Daten, Dienstumschaltung,
Deployment oder Merge.

## Nachgewiesene Ursache

`test_streaming_chat_is_enriched` verlangte eine angeheftete Anrede im
Chat-Systemkontext. Der Test isolierte zwar einige Datenpfade, verwendete aber
weiterhin den echten lokalen Embedding-Transport und dessen globalen,
fünf Sekunden gültigen Health-Cache. Bei kaltem/langsamem Dienst konnte bereits
der Health-Aufruf, bei warmem Cache das anschließende Vektor-Backfill das
Chat-Zeitbudget überschreiten. Auf CI ohne diesen Dienst fiel der Abruf dagegen
schnell auf lexikalische Suche zurück.

`MemoryChatMiddleware` verwendet absichtlich `wait_for(shield(future))`:
Beim Deadline-Ablauf läuft der erste Abruf weiter. Eine zweite Anfrage geht
währenddessen unmittelbar in den schnellen Abrufpfad. Dieser enthielt für
normale Nachrichten ausschließlich das strukturierte persönliche Gedächtnis,
**keine Legacy-Erinnerungen**. Dadurch verschwand die Anrede aus beiden
Anfragen. Mehr Zeit hätte die Abhängigkeit nur verdeckt.

Der Fehler wurde ohne produktive Dienste deterministisch reproduziert:
Ein kontrolliert blockierter `/health`-Aufruf beziehungsweise ein warmer
Health-Cache mit blockiertem `/embeddings` führte vor der Korrektur in beiden
Fällen zum identischen Fehler: `Nenn mich Nobby.` fehlt im Systemkontext.
Beide neuen Regressionen scheiterten in insgesamt 0,31 Sekunden. Das Testbudget
wurde dafür verkürzt, nicht erhöht.

Die alte Fixture schloss außerdem die drei Middleware-Executors nicht und
wartete nicht auf den abgeschirmten Abruf. Dieser konnte nach Testende noch
auf inzwischen zurückgesetzte globale Pfade/Funktionen zugreifen. Das ist ein
zusätzlicher Isolationsfehler; er wird nicht als alleinige bewiesene Ursache
des ursprünglichen Fehlers ausgegeben.

## Kleine, gezielte Korrektur

- Der schnelle Abruf verwendet den bereits vorhandenen lesenden
  `memory.explicit_context`-Helfer auch für normale Nachrichten.
- Dabei bleiben passende Legacy-Fakten und angeheftete Anrede-/Stilpräferenzen
  verfügbar. Unpassende Projekt- oder Modell-Pins werden nicht pauschal
  eingefügt. Datenschutz-, Lösch- und Pausefilter bleiben wirksam.
- Der vorhandene Anrede-Erkennungsausdruck wird wiederverwendet. Es gibt keine
  Sonderbehandlung für einen bestimmten Namen oder eine bestimmte Frage.
- Dieser Pfad ruft keine Embeddings auf und verändert keine Nutzungszähler.
  Zeitbudgets und Executor-Anzahl wurden nicht verändert.
- Die Middleware-Fixture isoliert zusätzlich Archivpfad, Health-Cache und
  Embedding-Transport. Nach Testende werden ihre Executors abgearbeitet und
  geschlossen, bevor `monkeypatch` globale Zustände wiederherstellt.

## Prüfungen

- Neue Deadline-Regressionen: kalter und warmer Cache; jeweils erste und zweite
  konkurrierende Chat-Anfrage, Erhalt von Anrede/Stil, Ausschluss eines
  unpassenden angehefteten Modells und unveränderte Nutzungszähler.
- Kurze Integration über echten Chat-Save, SQLite und Middleware bis zur
  Generierungsgrenze: neue normale Aussage gespeichert, Wiederholung ohne
  neue Faktzeile, echter Widerspruch als Rückfragehinweis. Getestet wurden beide
  Reihenfolgen: Generierung vor Autosave und Autosave vor Generierung.
- Vollständige lokale Python-Suite: **3.991 bestanden, 472 Subtests bestanden**,
  zwei bekannte Warnungen, 69,01 Sekunden. Der CPU-Testprozess erhielt einen
  nicht verwendeten Loopback-Embedding-Endpunkt; produktive Dienste waren kein
  Testbestandteil. Die expliziten Deadline-Regressionen simulieren beide
  blockierten Dienstzustände unabhängig davon.
- Zusätzlicher kurzer Abschlusslauf der Middleware-/Save-Integration bestanden.

Mit dem bereits aktiven lokalen **Qwen3.8-27B-Abliterated-MLX-4bit** wurden
zusätzlich genau zwei reale Chat-Stream-Antworten geprüft. Dafür wurden eine
neue isolierte Home-Struktur, fiktive kurze Aussagen und die echten
`put_chat`-/`runtime_chat_stream`-Handler verwendet. Nur Modellwahl und
Dienststeuerung waren auf den bereits aktiven Textserver festgelegt;
Embedding-Zugriffe waren deaktiviert. Es fand keine historische Analyse statt.

Ergebnis: erster Name gespeichert; identische normale Aussage nicht dupliziert;
abweichender Name als genau ein offener Widerspruch erhalten; ursprüngliche
Faktzeile unverändert; Qwen fragte im SSE-Stream mit beiden Alternativen und
Fragezeichen nach. Wiederholtes Speichern duplizierte auch den Widerspruch nicht.

Die frühere private Historienabnahme mit 16/16 Fragen wurde nicht wiederholt.
Die übrigen Grenzen des [Historienberichts](pr424-memory-history-20261105.md),
insbesondere fehlende historische Projektquellen und die separat zu
entscheidende Produktivfreigabe, bleiben bestehen.
