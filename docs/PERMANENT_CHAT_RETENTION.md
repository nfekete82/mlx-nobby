# MLX Nobby: Chats löschen, Erinnerungen behalten

## Gewünschte Benutzeroberfläche

Der Button **„Alle Chats löschen“** bleibt in der linken Seitenleiste unter
„Letzte Chats“ (Drei-Punkte-Menü). Jeder einzelne Chat hat weiterhin
„Löschen“ im Kontextmenü. Ein klarer Bestätigungsdialog ist erforderlich.

Diese Aktion entfernt nur die **aktiven Chats aus der Chatliste**. Sie darf
nicht die Langzeiterinnerungen löschen.

| Daten | Sidebar „Alle Chats löschen“ |
| --- | --- |
| Aktuelle Chat-JSON in der Verlaufsliste | Wird entfernt |
| Vorherige Chat-Revisionen | Bleiben |
| Privates Langzeit-Chatarchiv | Vollständige Quellkopie vor Entfernung |
| Memory DB (`memory.db`) | Bleibt |
| Private persönliche Fakten / Episoden | Bleiben |
| Indizierte Volltext-Chaterinnerungen | Bleiben |
| Durch Chats erzeugte Bilder | Bleiben |
| Externe Backups | Bleiben |

## Technische Umsetzung

- Bereits beim normalen Chat-Speichern werden Daten atomar auf die lokale
  Platte geschrieben. Ein bestehender Chat bekommt vor einer destruktiven
  Bearbeitung eine private Version unter `chats/.revisions/<id>/`.
- Vor jeder Sidebar-Löschung wird der **vollständige Chat** zusätzlich nach
  `~/.config/mlx-web/long-term-chat-memory/<id>/<uuid>.json` kopiert
  (Dateirechte 0600). Die Kopie liegt **außerhalb** der sichtbaren
  Chatliste und wird nicht durch automatische Testbereinigung gelöscht.
- Scheitert das private Archivieren, wird der Chat nicht gelöscht.
  Erst nach erfolgreichem Archivieren werden Tombstones geschrieben und die
  aktiven Chatdateien entfernt, damit alte Browser-Tabs sie nicht wiederbeleben.
- Der Agent ruft bei Sidebar-Löschungen **nicht**
  `personal_memory.remove_chat` oder `chat_archive.remove_chat` auf.
  Suchindex-Rebuilds lassen historisch gespeicherte Einträge in Ruhe.
- Chats werden per Bestätigungsdialog gelöscht; ein kurzlebiger, nur einmal
  nutzbarer Backend-Token verhindert versehentliche direkte Delete-Aufrufe.
  Das ist kein Authentifizierungssystem gegen lokale Schadsoftware.
- „Vergiss ...“ im Chat löscht weiterhin keine klassisch gespeicherten
  Erinnerungen. Das gezielte Verwalten der langfristigen Erinnerungen erfolgt
  in den Memory-Einstellungen.

## Verbindung mit dem Qwen-Gedächtnis (PR #424)

- `agent.app.memory_chat_reader(chat_id)` liest bei aktiven Chats die aktuelle
  Quelle und nach Löschung aus der Seitenleiste die letzte unveränderte
  private Kopie im Langzeitarchiv.
- `agent.app.iter_memory_chats()` streamt die privaten archivierten Chats und
  aktive Chats für spätere vollständige Qwen-Analyse. Der Haupt-Chatverlauf
  wird dadurch **nicht wiederhergestellt**.
- Die manuellen Rebuilds für persönliche Fakten und lexikalische Suche nutzen
  diese Quellen. Ein später erst eingeschaltetes Gedächtnis kann also auch
  ältere, aus der Seitenleiste entfernte Chats nachbearbeiten.
- Die asynchrone Qwen-Verarbeitung verifiziert den **aktuellen Text der privaten
  Quelldatei**, bevor ein Fakt geschrieben wird, und respektiert bestehende
  Ausschlüsse/Tombstones. Sie nutzt keine Cloud-Inferenz.
- Die Volltextquelle ist dauerhaft gespeichert; die Verfügbarkeit für eine
  konkrete Antwort hängt weiterhin von Indexierung, Relevanz, Kontextbudget
  und aktiviertem lokalem Qwen-Gedächtnis ab.
- „Vergiss …“ und „Das war nur ein Beispiel“ im Chat löschen keine
  bestehenden Erinnerungen automatisch. Gezielt und ausdrücklich bestätigtes
  Löschen bleibt eine eigenständige Einstellungsfunktion.
- Dieses Zusammenspiel ist derzeit **nur im Integrations-PR #424**, nicht in
  `main` oder der produktiven Instanz, und erfordert CI plus isolierte Abnahme.

## Wichtige Einschränkungen

**Löschen aus der Chatliste bedeutet nicht „alle Spuren entfernen“**:
Die Quellkopie im Langzeitgedächtnis und die Memory-Indizes bleiben explizit
erhalten, so wie vom Benutzer gewünscht. Eine separate und klar beschriftete
Einstellungsfunktion zur vollständigen Entfernung des Langzeit-Chatarchivs
muss vor der allgemeinen Freigabe ergänzt bzw. geprüft werden.
Die Erinnerungsdaten werden nicht automatisch mit dem Chatverlauf gelöscht.

Chat-Archivierung allein bedeutet nicht, dass jedes Detail automatisch vom
Sprachmodell erinnert wird. Eine spätere Suche/Wiederherstellung des
vollständigen Quellarchivs ist technisch möglich, benötigt aber einen
separaten, geprüften Index-/Restore-Prozess. Das aktuelle
`chat-archive.sqlite3` bleibt ein eigener opt-in-Suchindex.

Weder diese Änderung noch PR #421 können bereits früher endgültig gelöschte
und nicht anderweitig gesicherte Unterhaltungen rückwirkend rekonstruieren.
Beim vollständigen PR-Review müssen auch die asynchronen Qwen- und
Knowledge-Memory-Jobs nach einem Sidebar-Delete getestet werden, damit
laufende Lernprozesse nicht unterbrochen werden.

## Testen

```sh
python3 -m pytest -q tests/test_chat_retention.py tests/test_delete_all_chats.py \
  tests/test_personal_memory_integration.py tests/test_image_runtime.py
node --test tests/*.mjs
python3 scripts/check-public-privacy.py
python3 scripts/i18n-audit.py
```

Die Tests müssen ausschließlich in isolierten Testverzeichnissen laufen, nie
gegen produktive Chatdaten. Nicht mergen/deployen, bis die GitHub-CI und die
lokale macOS-Abnahme erfolgreich sind.
