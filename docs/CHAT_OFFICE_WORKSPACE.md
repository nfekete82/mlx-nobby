# MLX Nobby – lokale Word-, Excel- und ZIP-Bearbeitung

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

## Integrationsstatus und Abnahme

Die Funktion ist über [PR #407](https://github.com/nfekete82/mlx-nobby/pull/407)
am 3. November 2026 in `main` integriert. Die GitHub-Tests für den
zusammengeführten `main`-Commit `23d1104c` sind erfolgreich
(Python/macOS, Docker und Chromium). Das ist **keine** Bestätigung,
dass alle individuellen DOCX-/XLSX-Layouts bereits auf dem eigenen Mac
manuell geprüft wurden.

Beim regulären Update der laufenden Installation muss der Web-Container
mit dem aktuellen Backend neu gebaut werden. Es ist kein separater
Office-Feature-Branch mehr zu aktivieren.

Nach dem Update die lokale UI mit echten, nicht vertraulichen Testdateien prüfen:

1. Eine DOCX mit mehreren Format-Runs und Tabellen hochladen, Text prüfen
   und die erzeugte Kopie in Word öffnen.
2. XLSX mit Textzellen, Zahlen und Formeln bearbeiten: Nur angeforderte
   Textzellen dürfen sich ändern; die Kopie in Excel öffnen.
3. Ein kleines ZIP mit Text- und Binärdateien testen und sicherstellen,
   dass ausschließlich Textdateien angepasst werden.
4. Eine XLS-Datei lesend prüfen und verifizieren, dass keine Bearbeitung
   angeboten wird.

Vor einer Produktfreigabe zusätzlich den kanonischen lokalen Release-Gate
`./scripts/mlx test-release` ausführen (siehe
[Releasing](RELEASING.md)). Laufende fremde Medienjobs vorher beenden
oder den Test bei aktiver Arbeit verschieben.
