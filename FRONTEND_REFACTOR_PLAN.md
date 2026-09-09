# Frontend-Refactor-Plan

## Ziel und Rahmen

Dieser Plan betrifft ausschließlich `frontend/index.html` und `frontend/chat.html`. Er führt kein Framework ein, verändert keine API-Verträge und erhält Markup, IDs, Klassen, Texte, Requests und Verhalten zunächst unverändert. Der erste Schritt jeder Auslagerung ist eine **mechanische Extraktion**; erst danach dürfen interne Strukturen in kleinen, einzeln testbaren Änderungen verbessert werden.

Aktueller Umfang:

| Bereich | Umfang | Aktuelle Form |
| --- | ---: | --- |
| Control Center | 2.202 Zeilen | Tailwind-CDN, HTML-Markup plus 1.604 Zeilen Inline-JavaScript |
| Chat | 3.360 Zeilen | externe CDN-Bibliotheken, 1.024 Zeilen Inline-CSS, ca. 2.010 Zeilen Inline-JavaScript |

## Bestandsaufnahme

### Control Center (`index.html`)

Die Seite besteht aus fünf Hash-Views: Dashboard, Models, Downloads, System und Logs. Sie nutzt Tailwind-Klassen direkt im HTML und erzeugt Karten, Listen, Badges und Aktionen dynamisch per DOM-API.

Globale Zustände:

- `busy`: gemeinsame Sperre für Modell-, Cache-, Job-, Server- und Thinking-Aktionen.
- `currentThinking`: gerenderter Thinking-Zustand.
- `logsPaused`, `logSources`, `activeLogSource`: kompletter Zustand des Log Viewers.

Stark gekoppelte Bereiche:

- `setupAppViews()` / `findSectionByHeading()` / `showAppView()` hängen an sichtbaren `h2`-Texten (`Neues Modell`, `Modelle`, `Lokaler Cache`, `Downloads & Jobs`) und der aktuellen DOM-Hierarchie bzw. der Klasse `mt-6`.
- Alle mutierenden Modell-, Cache-, Job-, Server- und Thinking-Funktionen teilen `busy`, `setButtonsDisabled()`, Status-Elemente und anschließende Refreshes.
- `loadLogsView()`, `renderLogTabs()`, `renderActiveLog()` und `filteredLogText()` bilden eine geschlossene Log-Viewer-Einheit.
- `loadModels()`, `loadCache()` und `loadJobs()` erzeugen UI inklusive Event Listener; ihre Action-Funktionen aktualisieren mehrere Listen gegenseitig.

Wiederholungen bzw. ähnliche Strukturen:

- Viele `fetch`-Blöcke wiederholen Response-Prüfung, JSON-Lesen und die Umwandlung von `detail` in eine Fehlermeldung.
- `removeModelAlias`, `switchModel`, `redownloadModel`, `deleteModelCache`, `retryDownload`, `serverCommand` und `toggleThinking` haben das gemeinsame Muster: Sperren → Status setzen → Request → gezielte Reloads → Freigeben.
- Modelle, Cache und Jobs erzeugen jeweils Karten/Zeilen mit Badge, Metadaten und Action-Buttons. Das visuelle Markup ist ähnlich, die Daten und Aktionen jedoch verschieden genug, um zunächst getrennt zu bleiben.
- Dashboard- und Chat-Status laden beide `/api/mlx/status`, rendern aber unterschiedliche DOM-Ziele und dürfen daher nicht als gemeinsame Renderer zusammengelegt werden.

### Chat (`chat.html`)

Der Chat hat Sidebar-Sitzungen, Message-Rendering inklusive Markdown/Highlighting, Thinking-Abschnitte, Bearbeiten/Regenerieren, Settings, lokalen Dateiupload per Auswahl und Drag & Drop, Kontextanzeige, Auto-Compact sowie Fetch-Streaming.

Globale Zustände und Verträge:

- Persistenz: `STORAGE_KEY = 'mlx-web-chats-v1'`, `SETTINGS_KEY = 'mlx-web-chat-settings-v1'`.
- Sessions: `sessions`, `activeId` und das Schema `{ id, title, created, updated, messages }`.
- Generierung: `generating`, `abortController`.
- Upload: `attachments`, `ALLOWED_EXTENSIONS`, Größen- und Kontextlimits.
- Kontext: `MAX_CONTEXT_CHARS`, `COMPACT_AT_CHARS`, `KEEP_LAST_MESSAGES`.
- Direkte DOM-Referenzen beim Skriptstart: `input`, `messagesInner`, `messagesElement`, `sendButton`.

Stark gekoppelte Bereiche:

- `generateAssistant()` koppelt Request-Streaming, SSE-Parsing, Thinking-Zeitmessung, Session-Mutation, Persistenz, Rendering und Scrollverhalten.
- `sendMessage()` koppelt Prompt, Attachments, Titeländerung, Auto-Compact, Session-Persistenz und Generierung.
- `renderMessages()` kennt das gesamte Nachrichtenmodell, Thinking, Markdown, Highlighting, Attachments, Copy/Edit/Regenerate-Aktionen und `startEditMessage()`.
- `loadSessions()`, `saveSessions()`, `currentSession()`, Sidebar- und Message-Rendering teilen unmittelbar `sessions` und `activeId`.

Wiederholungen bzw. ähnliche Strukturen:

- Der temporäre Kopier-Status (`Kopieren` → `Kopiert` → Reset) kommt für Codeblöcke und Assistant-Nachrichten vor.
- `attachment-chip` wird für aktuell ausgewählte Dateien und gespeicherte User-Nachrichten gerendert.
- Mehrere Session-Aktionen mutieren Session-Daten und rufen anschließend `saveSessions()` sowie `renderAll()` oder `renderSidebar()` auf.
- Chat und Control Center enthalten je ein eigenes `loadStatus()` mit derselben API, aber unterschiedlicher Darstellung.

### CSS-Befund

- `index.html` hat kein eigenes CSS; Erscheinungsbild liegt in Tailwind-Utility-Klassen. Es gibt daher keinen gleichwertigen CSS-Block, der gefahrlos mit dem Chat zusammengeführt werden kann.
- `chat.html` enthält eigene CSS-Variablen und Komponentenselektoren.
- Exakt doppelt deklarierte Chat-Selektoren: `.chat-entry`, `.composer` und `.field textarea`.
- `.chat-entry` und `.field textarea` ergänzen sich jeweils. Der zweite `.composer`-Block ist dagegen widersprüchlich: Er enthält offenbar Settings-Panel-Eigenschaften (`top`, `right`, feste Breite, `display: none`) und überschreibt damit die vorherigen Composer-Stile. Dieser bestehende Befund wird **nicht** im Extraktionsschritt korrigiert, weil eine visuelle Änderung nicht Teil dieses Auftrags ist.
- Ähnliche UI-Konzepte über beide Seiten hinweg sind Header/Status, Buttons, Badges, Karten und Formfelder, aber sie verwenden unterschiedliche Stilmechanismen. Eine gemeinsame Stylesheet-Datei ist erst nach einem visuellen Token-/Klassen-Audit sinnvoll.

## API- und Event-Zuordnung

| Frontend-Bereich | Web-API | Besonderheit |
| --- | --- | --- |
| Control Center Status | `GET /api/mlx/status` | 3-Sekunden-Polling |
| System | `GET /api/mlx/system` | nur beim System-Hash-View |
| Logs | `GET /api/mlx/logs/all?limit=400` | Suche, Tabs, Pause, Autoscroll |
| Aliase | `GET /api/mlx/aliases` | dynamische Start-/Entfernen-Buttons |
| Modell anlegen | `POST /api/mlx/models/add` | startet Job, refresht drei Bereiche |
| Alias wechseln/löschen | `POST/DELETE /api/mlx/model(s)/...` | `busy`-Sperre |
| Cache/Jobs | `GET /api/mlx/cache`, `GET /api/mlx/jobs` | 3-Sekunden-Polling |
| Cache/Retry/Redownload | `DELETE/POST /api/mlx/cache|jobs/...` | Bestätigung und Folgerefresh |
| Server/Thinking | `POST /api/mlx/server/...`, `POST /api/mlx/thinking/...` | gemeinsame Sperre |
| Chat Status | `GET /api/mlx/status` | 5-Sekunden-Polling |
| Auto-Compact | `POST /api/chat/compact` | mutiert lokale Session |
| Chat-Streaming | `POST /api/chat/stream` | `ReadableStream`, SSE, `AbortController` |

Alle im aktuellen Frontend verwendeten API-Pfade existieren im Web-Backend. Es gibt keine Inline-HTML-Event-Attribute wie `onclick`; alle Listener werden in JavaScript registriert. Das erleichtert die Auslagerung, macht aber die Ausführungsreihenfolge und die dynamisch angehängten Listener wichtig.

## Empfohlene Zielstruktur

```text
frontend/
├── index.html
├── chat.html
└── assets/
    ├── css/
    │   └── chat.css
    └── js/
        ├── control-center.js
        ├── chat.js
        ├── shared/
        │   └── api.js                 # erst nach erfolgreicher Extraktion
        ├── control-center/
        │   ├── navigation.js
        │   ├── status.js
        │   ├── system.js
        │   ├── logs.js
        │   ├── models.js
        │   ├── cache.js
        │   └── jobs.js
        └── chat/
            ├── storage.js
            ├── attachments.js
            ├── sidebar.js
            ├── messages.js
            ├── stream.js
            └── settings.js
```

`assets/css/app.css` ist absichtlich **nicht** Teil der ersten Zielstufe: Das Control Center nutzt Tailwind im Markup, der Chat eigene CSS-Variablen. Eine gemeinsame Datei hätte ohne vorheriges Design-Audit keinen klaren Nutzen und birgt sichtbare Regressionsrisiken.

Das Backend liefert heute nur die beiden vollständigen HTML-Dateien aus. Bevor externe Assets aktiviert werden, muss in einer späteren, kleinen Backend-Änderung ein statischer Mount für `/assets` eingerichtet werden, etwa mit `StaticFiles(directory='/app/frontend/assets')`. Erst danach können `link`- und `script src`-Tags zuverlässig funktionieren. Dieser Backend-Schritt gehört in denselben kleinen PR/Änderungsschritt wie die erste Asset-Extraktion und erfordert anschließend den Docker-Rebuild.

## Sichere Refactor-Reihenfolge

### Phase 0 – Absicherung vor jeder Änderung

1. Aktuelle `index.html` und `chat.html` sichern.
2. Smoke-Test beider Seiten, der vorhandenen Navigation und aller Frontend-API-Pfade ausführen.
3. Screenshot-/manuelle Checkliste für Dashboard, Models, Downloads, System, Logs und Chat festhalten.
4. Keine semantischen HTML- oder Klassennamen ändern.

### Phase 1 – Mechanische, reversible Extraktion

1. Statische Auslieferung von `/assets` im Web-Backend ergänzen und testen.
2. Den vollständigen Inline-Block aus `chat.html` **bytegleich** nach `assets/css/chat.css` verschieben; nur durch `<link rel='stylesheet' href='/assets/css/chat.css'>` ersetzen.
3. Den vollständigen Chat-JavaScript-Block zunächst unverändert nach `assets/js/chat.js` verschieben und den Script-Tag am bisherigen Dokumentende durch `<script src='/assets/js/chat.js'></script>` ersetzen.
4. Den vollständigen Control-Center-JavaScript-Block zunächst unverändert nach `assets/js/control-center.js` verschieben und analog einbinden.
5. Nach jedem einzelnen Subschritt Browser- und API-Smoke-Tests ausführen; bei Abweichung nur diesen Schritt zurücknehmen.

In dieser Phase keine ES-Module verwenden: Ein externes klassisches Script erhält die derzeitige globale Sichtbarkeit und die Ausführungsreihenfolge am Dokumentende. `defer` oder `type='module'` erst einsetzen, wenn alle Abhängigkeiten explizit sind.

### Phase 2 – Gemeinsame, reine Hilfen

1. `assets/js/shared/api.js` als klassisches Namespace-Script einführen, z. B. `window.MlxApi`.
2. Zuerst nur reine Request-Hilfen auslagern: JSON lesen, `response.ok` prüfen und FastAPI-`detail` sicher in einen Fehlertext überführen.
3. Bestehende Seitenfunktionen behalten ihre Namen und DOM-Updates; sie rufen lediglich die neue Hilfsfunktion auf.
4. Erst wenn beide Seiten unverändert funktionieren, kann eine kleine gemeinsame Status-Request-Hilfe folgen. Die beiden Renderer bleiben getrennt.

### Phase 3 – Control Center nach fachlichen Bereichen trennen

1. `navigation.js`: `findSectionByHeading`, `setupAppViews`, `currentAppView`, `showAppView`, Hash-Listener.
2. `logs.js`: gesamter Log-Viewer mit seinen drei States und allen Log-Controls.
3. `status.js` und `system.js`: Status- und System-Loader plus Formatter.
4. `models.js`, `cache.js`, `jobs.js`: jeweils Loader, Renderer und Action-Funktionen desselben Fachbereichs.
5. Eine kleine Orchestrierungsdatei `control-center.js` hält nur Shared State, Listener-Registrierung, Initialisierung und Polling.

`busy` bleibt zunächst in der Orchestrierung als einzige Wahrheit. Erst nach stabiler Trennung sollte daraus ein expliziter UI-Aktionszustand werden.

### Phase 4 – Chat nach Zuständigkeit trennen

1. `storage.js`: Session-Schema, Laden/Speichern, `currentSession`, Erzeugen/Benennen/Löschen.
2. `attachments.js`: Datei-Validierung, Lesen, Attachment-State und Kontextaufbau.
3. `sidebar.js`: Sidebar-Rendering und Session-Menü.
4. `messages.js`: Markdown-Sanitizing, Code-Buttons, Thinking-Block, Nachrichtenrendering und Bearbeiten.
5. `stream.js`: Compact, Auto-Compact, Send, Regenerate, Fetch-Streaming, Abbruch und Thinking-Zeit.
6. `settings.js`: Settings-Storage und Formularbindung.
7. `chat.js`: kontrollierter State-Container, DOM-Referenzen, `renderAll`, Initialisierung und Event-Bindings.

Der Chat sollte erst nach Phase 1 in ES-Module umgestellt werden – und nur, wenn Tests für Streaming, Abbruch, Kontextkomprimierung und Session-Persistenz vorhanden sind. Alternativ bleibt ein kontrollierter `window.MlxChat`-Namespace zunächst risikoärmer.

### Phase 5 – Erst danach: gezielte Bereinigung

1. Den widersprüchlichen zweiten `.composer`-Block anhand eines visuellen Vergleichs untersuchen und vermutlich nach `.settings` korrigieren.
2. Duplizierte Copy-Feedback-Logik in eine kleine Chat-Hilfe überführen.
3. Wiederkehrende Control-Center-Action-Abläufe in eine Helper-Funktion überführen.
4. Erst am Ende entscheiden, ob gemeinsame Design-Tokens oder gemeinsame Komponenten tatsächlich Nutzen bringen.

## Prüfpunkte und Risiken beim Auslagern

| Bereich | Risiko | Sichere Maßnahme |
| --- | --- | --- |
| Inline Event Listener | Keine HTML-Attribute vorhanden; Listener für dynamische Elemente entstehen beim Rendern. | Listener in denselben Renderer-Dateien belassen; keine Umstellung auf String-Handler. |
| Ausführung vor `DOMContentLoaded` | Beide Scripts stehen heute nach ihrem DOM-Markup und greifen sofort auf Elemente zu. | Erste Extraktion am selben Dokumentende ohne `defer`/Module; spätere Umstellung nur mit explizitem Bootstrap. |
| Globale Variablen | `busy`, Log-State, Chat-Session-State, `generating`, `attachments` und DOM-Referenzen sind funktionsübergreifend. | Zuerst ein Script pro Seite; beim Split kontrollierter Namespace/State-Objekt statt verdeckter Modul-Scope. |
| Hash-Navigation | Navigation ist an Hash-Werte, `h2`-Texte und DOM-Struktur gekoppelt. | Phase 1 unverändert kopieren; DOM-Markup erst nach einem separaten Navigations-Refactor anfassen. |
| Streaming-Chat | SSE-Puffer, Abbruch, Thinking-Zeit, Render/Scroll und Persistenz sind eng gekoppelt. | `generateAssistant()` zunächst als vollständige Einheit verschieben; erst später in kleine Funktionen aufteilen. |
| `localStorage`-Sessions | Schlüssel und Message-Schema sind lokale Nutzerdaten. | Schlüssel und Schema unverändert lassen; bei Schemaänderungen nur additiv mit Migration. |
| Drag & Drop Upload | Event-Reihenfolge, `relatedTarget`, File-Input-Reset und `attachments`-State sind sensibel. | Composer-Listener und Attachment-Logik zunächst gemeinsam in `chat.js`/`attachments.js` lassen. |
| Thinking UI | Backend streamt `reasoning`; UI nutzt `_thinkingStarted` und `thinking_seconds`. | Message-Schema und Streaming-Verarbeitung unverändert behalten; Thinking-Renderer nicht vor `stream.js` trennen. |
| Auto-Compact | Grenzen müssen zum Backend-Verhalten passen; der Aufruf mutiert lokale Sessions. | Konstanten unverändert lassen und Compact vor jeder Streaming-Änderung manuell testen. |
| Log Viewer | Drei globale States plus Suche, Pause, Copy und Autoscroll. | Als geschlossenes Modul auslagern, nicht in generische Listenkomponenten pressen. |
| System View | Geringe Kopplung, aber über Hash lazy geladen. | Nach Navigation auslagern; `showAppView()`-Vertrag beibehalten. |
| Models / Cache / Jobs | Renderer erzeugen eigene Buttons; Actions triggern mehrere Refreshes und teilen `busy`. | Je Fachbereich zusammen auslagern; Refresh-Reihenfolge und CSS-Klassennamen unverändert lassen. |

## Dateien mit der besten ersten Auslagerungsreihenfolge

1. `assets/css/chat.css` – rein mechanisch, keine Logik.
2. `assets/js/chat.js` – zunächst als ein unveränderter Block, da alle Zustände und Events intern zusammenhängen.
3. `assets/js/control-center.js` – ebenfalls zunächst unverändert als ein Block.
4. `assets/js/shared/api.js` – erst nach erfolgreichen mechanischen Extraktionen.
5. `assets/js/control-center/logs.js` – klar abgegrenzter Fachbereich.
6. `assets/js/control-center/navigation.js` und `system.js`.
7. Chat-Unterbereiche in der Reihenfolge Storage → Attachments → Sidebar → Messages → Streaming.

## Vorläufig bewusst inline bzw. als Einheit belassen

- Das HTML-Markup beider Seiten: IDs, Klassen, Reihenfolge und Tailwind-Klassen bleiben unangetastet.
- Der vollständige Streaming-Kern, bis die mechanische Extraktion stabil getestet ist.
- Die Control-Center-Hash-Navigation, bis ihre Heading-/DOM-Abhängigkeit separat abgesichert wurde.
- `busy` und die Refresh-Orchestrierung von Models/Cache/Jobs, bis die fachlichen Module bestehen.
- Chat-Session-Schema und `localStorage`-Schlüssel.
- Externe CDN-Tags: Sie sind nicht Teil dieses Refactors und werden in diesem Plan nicht verändert.

## Abnahmekriterien für jeden späteren Schritt

1. Beide Dokumente laden ohne JavaScript-Fehler.
2. Dashboard-Polling, alle fünf Hash-Views und Log-Controls funktionieren.
3. Modell hinzufügen, wechseln, Alias entfernen, Cache- und Job-Aktionen funktionieren unverändert.
4. Neuer Chat, Session-Wechsel, Umbenennen, Löschen, Bearbeiten und Regenerieren erhalten lokale Daten.
5. Datei-Auswahl und Drag & Drop behalten dieselben Limits, Chips und Kontextinhalte.
6. Thinking-Stream, Abbruch, Auto-Compact, Markdown, Code-Kopieren und Autoscroll funktionieren.
7. Alle vorhandenen Web-API-Endpunkte bleiben über die bisherigen Pfade erreichbar.
8. Nach Asset-/Backend-Änderungen: Python-Syntax, betroffene API-Endpunkte und `docker compose up -d --build` testen.
