# Talking Photo: LTX-only ohne MuseTalk

Stand: 21.10.2026. Standard ist **LTX Distilled (8+3)**; zweite Option ist **LTX direkt**.
Beide animieren das Bild und erzeugen die Mundbewegungen ausschließlich mit LTX 2.5 MLX.

- `Fast / MuseTalk` und `Hybrid / LTX + MuseTalk` sind aus dem Frontend entfernt.
- Neue API-Jobs akzeptieren ausschließlich `ltx-distilled` oder `ltx`; bei alten
  `fast`-/`quality`-Werten antwortet die API mit 422.
- Die Status-API befragt nur noch den LTX-Provider und benötigt Port 8070 nicht mehr.
- Vorhandene Videos, Aufträge, Download-, Abbruch-, Aufbewahrungs- und
  Wiederherstellungsrouten bleiben erhalten. Historischer MuseTalk-Code bleibt
  vorerst im Repository, wird aber von neuen Jobs nicht mehr aufgerufen.
- Der Code-Commit beendet keine Dienste und löscht keine Modellgewichte.
  MuseTalk-LaunchAgent erst bei inaktiven alten Aufträgen auf dem Mac anhalten;
  bei Problemen durch erneuten Start reversibel.
- Keine Änderung der LTX-Engineversion, Bild-/Video-/Speech-Pipelines oder
  installierten Stimmen. Dieser Branch basiert direkt auf `main`;
  LTX-0.17.0-/Admission-Experimente werden nicht mit integriert.
