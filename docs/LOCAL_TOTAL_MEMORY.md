# MLX-Nobby: lokales Gesamtgedächtnis (PR #421)

## Ziel

Das Gedächtnis verbindet **vollständig gespeicherte Original-Chats**,
**durchsuchbare lokale Ereignisse**, **geprüfte persönliche Fakten** und
**vorhandene Medienbibliothek-Dateien**. Bei einer Frage bekommt das Modell
nur die relevanten Fundstellen als Kontext; der gesamte Datenbestand passt
nicht in einen einzelnen Modellprompt.

## Datenebenen

1. **Original-Chats:** `~/.config/mlx-web/chats/*.json` bleiben die
   maßgebliche Quelle für Benutzer-/Assistentennachrichten und gespeicherte
   Aktionsergebnisse. Kein globales Token-Limit wird als vollständiger
   Chatkontext ausgegeben. Bereits gelöschte Chats werden nicht wiederhergestellt.
2. **Lokaler Suchindex:** `chat-archive.sqlite3` (optional, SQLite FTS5)
   indiziert Benutzer-/Assistententext und aktualisiert/entfernt Einträge bei
   Änderungen. Ein einzelner Indexeintrag ist aus Ressourcengründen auf
   256.000 Zeichen begrenzt; längere **Originalnachrichten bleiben erhalten**.
   Tool-Payloads, Binaries und Dateipfade werden nicht pauschal indiziert.
3. **Strukturierte Chronik:** `archive_activity` erfasst separat Quelle,
   Tätigkeitstyp, Ausführungsstatus, Modell, soweit vorhanden Erstellprompt,
   Projekt und Artefakt-ID. Wiederholte Speicherungen desselben Jobs werden
   aktualisiert, echte unterschiedliche Ausführungen bleiben nachvollziehbar.
   Der Status „completed“ ist ein historischer Jobstatus und kein Beweis,
   dass die Datei heute noch existiert.
4. **Persönliche Fakten:** `personal-memory.sqlite3` enthält überprüfte
   Schlüssel/Werte mit Chat-Quelle, Korrekturen und Löschsperren.
   Die lokale Qwen-Analyse extrahiert bis zu fünf explizite, belegte Fakten
   pro verarbeiteter Nutzernachricht. Sehr lange Nachrichten (>1.600 Zeichen)
   bleiben vollständig im Originalarchiv, werden aber derzeit nicht als
   Ganzes semantisch extrahiert.
5. **Vorhandene Bilder/Videos:** bei gezielten Fragen wird die vorhandene
   lokale Medienbibliothek mit ihren bereits geprüften Metadaten abgefragt.
   Fehlende Prompts, Bildinhalte ohne Vision-Analyse und gelöschte Dateien
   werden nicht erfunden.
6. **Nobby Memory:** die bestehende `memory.db` bleibt erhalten und dient
   weiterhin dem semantischen Abruf langlebiger Notizen.

## Im Chat

- Kernidentität (z. B. Name, Beruf und Technologien) wird bei aktiviertem
  persönlichem Gedächtnis mit kleinem Kontextbudget berücksichtigt.
- Intimere Informationen und Projektinhalte werden nur bei passendem Thema
  abgerufen.
- Allgemeine Fragen wie „Was weißt du über mich?“ aktivieren eine begrenzte,
  quellenbasierte Übersicht aus Lebensbereichen, Langzeitgedächtnis und
  Aktivitäten.
- Knappes „und jetzt?“ übernimmt den vorigen **Suchkontext**, ohne die
  eigentliche Nutzernachricht umzuschreiben.
- Bei langsamen Embeddings bleibt ein leichtgewichtiger, rein lokaler
  persönlicher Kontext als Fallback.
- Explizite Fragen nach konkreten früheren Angaben (z. B. `Wie heißt mein Sohn?`)
  lesen im schnellen Pfad nun **auch** die aktuelle persönliche Faktentabelle,
  nicht nur Knowledge-FTS, Chatarchiv und ältere Langzeitnotizen. Verfügbare
  Werte und Chatquellen haben Vorrang vor allgemeinen Hinweisen.
- Die Quellen werden unabhängig abgefragt. Ein ausgefallener Knowledge-Index
  darf vorhandene persönliche Fakten nicht mit einer allgemeinen
  Fehlermeldung verdecken; ein leeres Suchergebnis einer Quelle gilt nicht
  als Nachweis, dass alle anderen Quellen ebenfalls leer sind.
- Der Chat darf alte Antworten und gespeicherte Erfolgsstatus nicht als
  aktuelle Realwelt-Verifikation darstellen.

## Aktivierung und Vollindexierung

Unter **Einstellungen → Gedächtnis**:

1. Gedächtnis fortsetzen, falls pausiert.
2. Unter erweiterten Einstellungen das lokale Chatarchiv einschalten und
   **Suchindex neu aufbauen** (wichtig für neue Aktivitätsfelder).
3. Persönliches Gedächtnis aktivieren.
4. Lokales Qwen-Lernen aktivieren.
5. **„Alle gespeicherten Chats mit Qwen analysieren“** starten.
   Der Produzent arbeitet den bisherigen Chatbestand nach Opt-in durch,
   wartet bei voller 100er-Queue, vermeidet bereits geprüfte Message-Hashes
   und stoppt bei Pause/Deaktivierung. Ein nach Unterbrechung erneut
   gestarteter Durchlauf überspringt bereits verarbeitete Nachrichten.
   Der Fortschritt zeigt Scannen, Warteschlange, Erfolge und Fehler.

Bei vielen tausend Chats benötigt der Vorgang entsprechend viel lokale
Modell-Rechenzeit. Die Option darf die normale Chatfunktion nicht blockieren;
es erfolgt keine Analyse auf externen Servern.

## Einsicht und Provenienz

- `GET /api/mlx/memory/archive/activities?kind=video&limit=25&offset=0`
  zeigt strukturierte, paginierte Aktivitäten.
- `GET /api/mlx/memory/smart/status` enthält `full_scan` mit
  `total`, `examined`, `queued`, `skipped` und `active`.
- Original-Chats und bestehende Medienbibliothek sind separat einsehbar.
- Lösch-/Ausschlussfunktionen müssen auch die abgeleitete Chronik bereinigen.

## Grenzen

„Alles lokal gespeichert“ bedeutet **vollständige auf dem Host vorhandene
Originaldaten plus bestmöglich abgeleitete Indizes**, nicht, dass das Modell
alle Fakten gleichzeitig im Arbeitsspeicher oder Kontextfenster hält.
Informationen, die die Anwendung nie als Text oder Metadaten protokolliert
hat, können nicht zuverlässig rekonstruiert werden. Im Zweifel muss Nobby
„nicht belegt“ statt einer erfundenen Behauptung sagen.

## Abnahme vor Deployment

```bash
python3 -m pytest -q tests/test_live_personal_recall.py \
  tests/test_archive_activity_memory.py \
  tests/test_smart_full_history.py \
  tests/test_chat_archive_memory2.py \
  tests/test_memory_middleware.py
node --test tests/test_memory_overview_ui.mjs
python3 scripts/i18n-audit.py
```

Danach Gesamttests, Browser-Abnahme und ein isolierter lokaler Funktionstest.
Kein produktiver Agent/Container wird durch das Prüfen des GitHub-Branches
automatisch verändert.

## 2026-11-06 — expliziter Live-Recall-Fix

Die Änderung betrifft ausschließlich die Konstruktion des Chat-Kontexts im
nativen Agent. Es gibt keine Migration, keinen Vollscan, keine Änderung an
Original-Chats oder den gespeicherten Fakten, keine neue Cloud-Abhängigkeit
und keine Änderung der Lösch-/Pause-Regeln. Die Prüffälle verwenden nur
fiktive Namen/Projekte in temporären SQLite-Dateien.

Die Tests prüfen konkreten Faktabruf über den echten Streaming-Middleware-Pfad,
Wiederherstellung aus der persönlichen Faktentabelle bei leerem Knowledge-Index,
Ausfallisolierung einschließlich fehlschlagender Diagnostik sowie
Datensparsamkeit bei themenfremden Fragen und globaler Pause.

Vor der lokalen Aktivierung: privaten Backup-Status prüfen, laufende
Chat-/Media-Jobs beenden lassen und nur den nativen Agent neu starten.
Docker-Web, GPU-Runtime und Memory-Modell müssen hierfür nicht neu gestartet
werden. CI-Erfolg ersetzt keinen Antwortqualitätstest mit den tatsächlich
vorhandenen (privaten) lokalen Erinnerungen.

## 2026-11-06 — German compound retrieval for remembered browser games

A confirmed `Merk dir: … Browserspiel … Echtzeitstrategiespiel …` command
saves a literal, source-linked note in the existing `personal-memory.sqlite3`.
The source can be present even when a new chat asks for `mein Strategiespiel`
and the lexical FTS index returns no match: German compounds are indexed as
complete tokens, while a related word need not share that exact token.
The SQL/FTS query now expands only a narrowly defined group of related game
terms; it does not invent a game name, engine, technology or project status.
Separate-source privacy filters, tombstones and opt-in settings are unchanged.

Synthetic regression tests cover the full confirmation-to-new-chat lookup with
the original wording shape, the correct source chat, no online embeddings,
ordinary unrelated technical questions and protection of an unrelated private
note. If local storage never confirmed `persisted: true`, the query fix cannot
restore an unsaved statement; inspect the read-only memory dashboard before
assuming retrieval is at fault.

Local diagnosis:
`GET /api/memory-dashboard/status` reports the paused flag and personal count.
`GET /api/memory-dashboard/items?source=personal&query=Browserspiel`
reads matching active personal notes without modifying them. The
`/api/knowledge-memory/context` or native module context can be used to verify
the exact retrieval path after the Agent is restarted. Do not include private
memory values in public test artifacts.
