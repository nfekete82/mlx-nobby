# MLX Nobby – lokale Word-, Excel- und ZIP-Bearbeitung (Entwurf)

Der Chat akzeptiert direkt DOCX, XLSX, XLS und ZIP-Dateien. Die Dateien werden
über die bestehende Webanwendung lokal in einer begrenzten Worker-Pipeline
gelesen und der relevante Textausschnitt dem **lokalen** Chatmodell gegeben.
Es gibt keinen Cloud-Upload und keine Ausführung von Datei-/Archiv-Inhalten.

## Funktionsumfang

| Format | Prüfen / zusammenfassen | Änderungen | Einschränkungen |
| --- | --- | --- | --- |
| DOCX | Absätze und Tabellen | Exakte Text-Ersetzungen | Über mehrere Format-Runs geteilte Texte werden nicht verändert; keine Layout-Neugestaltung |
| XLSX | Tabellen, Zelladressen und Werte | Textzellen ersetzen | Zahlen, Formeln und Datentypen bleiben erhalten; komplexe Spalten-/Formeländerungen sind noch nicht möglich |
| XLS | Vorhandene Tabellenwerte lesen | Nein | Alte Excel-Binärdatei ist schreibgeschützt; für Bearbeitung zuerst in XLSX konvertieren |
| ZIP | Archivliste, Textvorschau | Textdateien im ZIP ersetzen | Keine Ausführung; Office-Dateien im Archiv werden nicht inhaltlich bearbeitet |
| CSV/TXT/MD/JSON | Auslesen | Exakte Text-Ersetzungen | Keine datenbankschematische bzw. strukturierte Datentransformation |

Die Oberfläche nimmt diese Dateien über den gewohnten Anhang-Button oder
Drag-and-drop an. Bei einer Prüfaufgabe wird eine Modell-Zusammenfassung
ausgegeben. Bei einem klaren Bearbeitungswunsch versucht das Chatmodell,
maximal 16 **exakte, am vorhandenen Text belegbare** Änderungen vorzuschlagen.
Nicht passende bzw. nicht sicher umsetzbare Änderungen werden nicht
still erfunden. Erfolgreich geänderte Dateien werden als **neue Kopie** mit
Download-Link angeboten. Das Original bleibt unberührt.

## Sicherheit und Ressourcen

- Max. 20 MiB pro Upload und Ausgabedatei, 40 MiB unkomprimiert je Archiv,
  120 Archiv-Einträge, max. 8 MiB je ZIP-Eintrag
- ZIP-Traversal, Symlinks, verschlüsselte Archive und auffällige
  Komprimierungsraten werden abgelehnt
- Office-XML-Container werden vor dem Öffnen ebenfalls auf gefährliche ZIPs geprüft
- Keine Makroausführung, keine Shell-Aufrufe oder Dateipfad-Freigaben
- Keine unkontrollierte Office-/ZIP-Byte-Einbettung in Chatverlauf oder Git
- Modell sieht höchstens 11.000 Zeichen aus dem Auszug; bei großen
  Dokumenten nur Teilprüfung – keine Vollständigkeitsgarantie
- Erzeugte Kopien liegen ausschließlich im lokalen Docker-Volume unter
  `/app/eml-data/office-workspace`; Download-Tokens sind zufällig und
  verfallen nach 24 Stunden
- Der LLM-Ausgang wird als strukturierter Plan validiert und nur exakte
  Ersetzungen werden angewendet; Modellbehauptungen sind nicht gleich
  erfolgreich ausgeführte Änderungen
- Komplexe DOCX-Formatierung und Tabellenfeatures können beim Speichern
  mit `python-docx` / `openpyxl` in Einzelfällen verändert werden. Die
  bearbeitete Kopie vor externer Weitergabe kontrollieren

## Rollout

Die Änderungen verwenden neue, auf `main` basierende Feature-Branch-Dateien.
Nach CI und lokalem Probelauf können sie freigegeben werden.

```bash
cd ~/mlx-web
git fetch origin
# Separater Feature-Branch, NICHT ungeprüft in die laufende Integration mergen.
git switch -c feat/chat-office-archive-workspace-20261103 --track origin/feat/chat-office-archive-workspace-20261103
python3 -m pytest -q tests/test_office_workspace.py
docker compose build mlx-web
```

Für die Endabnahme DOCX- und XLSX-Dateien mit echten Tabellen und ein ZIP
mit Text- und Binärdateien hochladen; Ausgabe herunterladen und öffnen.
Während der Installation kein automatischer Modell- oder Runtime-Neustart.
