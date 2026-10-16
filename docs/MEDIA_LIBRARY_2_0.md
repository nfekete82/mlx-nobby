# Bibliothek 2.0 — lokales Medienstudio

Bibliothek 2.0 erweitert die bestehende, rein lokale Medienbibliothek ohne
Umzug der generierten Dateien, Cloud-Verarbeitung oder Änderungen an den
Renderengines.

## Oberfläche

- Bilder, Standardvideos und Talking Photos in einer gemeinsamen Übersicht.
- Video-Kacheln zeigen automatisch zwischengespeicherte JPEG-Vorschaubilder.
- Engine-Filter: Alle, Talking Photo, LTX Distilled, LTX direkt,
  Hybrid (LTX + MuseTalk), MuseTalk und andere Videos.
- Die Suche berücksichtigt zusätzlich die Engine sowie Metadaten bereits
  geladener Videos. Der Typfilter "Video" umfasst weiter Talking Photo.
- Videodauer und Auflösung werden bei Bedarf per `ffprobe` gelesen.
- Im Bild-Menü und in der Vollbildvorschau führt **Talking Photo** direkt
  zum vorhandenen Dialog; ein bestehendes PNG wird als ausgewähltes Foto
  übernommen. Keine erneute Bildgenerierung und keine Ablage-Kopie.
- Die bisherigen Speicher-, Download- und explizit bestätigten
  Löschfunktionen bleiben erhalten.

## Ressourcen und Sicherheit

- Nur streng validierte IDs und kanonische Dateien der bestehenden
  `media_lifecycle`-Wurzeln können zur Vorschauerstellung genutzt werden.
  Symbolische Links und Acceptance-Testmedien sind ausgeschlossen.
- Vorschaubilder werden ausschließlich auf Anfrage erstellt, auf 640 Pixel
  begrenzt und als lokale JPEGs zwischengespeichert.
  `ffmpeg` hat ein Zeitlimit (35 Sekunden), `ffprobe` (12 Sekunden).
  Die Antwort ist auf 1,5 MB begrenzt; der Browser erhält keine Pfade.
- Metadaten werden erst geladen, wenn eine Videokarte sichtbar wird
  (IntersectionObserver, mit Fallback für ältere Browser).
- Die Original-MP4 wird weder überschrieben noch kopiert; gespeicherte
  Miniaturansichten werden beim ausdrücklich bestätigten Löschen entfernt.
- Die ursprüngliche MP4-Playback-Route bleibt unverändert. Wenn der Agent
  kein `ffmpeg` bereitstellt, wird ein neutrales Platzhalterbild angezeigt.
- Engines älterer Talking Photos sind nur verfügbar, solange die
  ursprünglichen Job-Metadaten vorhanden sind; andernfalls erscheint der
  allgemeine Typ "Talking Photo".

## Validierung

- Pytests prüfen erlaubte und verbotene Pfade, Acceptance-Isolation,
  Thumbnail-Metadaten, Cache-Hit und Löschschutz.
- JS-Vertragstests prüfen Versionsparameter, Engine-Filter, sichere
  DOM-Konstruktion, lazy loading und Talking-Photo-Verknüpfung.
- Chromium-E2E prüft die Bildweitergabe und Engine-Filter auf Desktop
  und Mobil mit kontrollierten API-Fixtures.
- Der finale Apple-Silicon-Test muss reale Videos und Talking Photos in
  der Bibliothek anzeigen, die JPEGs erzeugen, und einen erneuten
  Talking-Photo-Render aus einem bestehenden Bibliotheks-PNG erlauben.

Dies ist ein Produkt-Feature, noch keine Freigabe. Die Versionsanhebung
erfolgt ausschließlich in einem separaten Release-Metadaten-PR nach grünen
Tests und dem lokalen Release-Gate gemäß `docs/RELEASING.md`.
