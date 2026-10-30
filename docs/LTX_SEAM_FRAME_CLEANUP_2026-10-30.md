# LTX – Frame-genaues Stitching (experimenteller Pilot)

## Warum

Der Identity-Lock-Pilot hat den harten Startanker repariert. Unabhängige
Segmente können trotzdem Gesichter, Belichtung, Farben und Bewegung
unterschiedlich generieren. Zusätzlich werden 3-s/24-fps-Abschnitte mit
73 Bildern (8k+1) produziert; bei naivem Stream-Copy-Concatenation wird
das erste Bild eines Folgesegments als zusätzliche zeitliche Kopie des
vorherigen Schlussbilds wiedergegeben. Das kann als kurzer Ruck/Stopp
sichtbar werden.

## Diese Änderung

- Concatenation läuft weiterhin **sequentiell** über den FFmpeg-concat-
  demuxer, statt alle 1080p-Segmente gleichzeitig zu dekodieren.
- Die wiederholten Frameindizes n = 73, 146, 219 ... werden entfernt
  (720p/540p entsprechend 121/145).
- Video-PTS werden als konstante 24 FPS neu aufgebaut.
- H.264 CRF17 wird CPU-seitig mit `libx264` neu kodiert; die Segment-
  Checkpoints bleiben als unveränderte MP4-Dateien vorhanden.
- Audio wird konservativ zeitlich an die korrigierte Dauer angenähert
  und zu AAC neu kodiert. Bei gesprochenen Videos müssen Segmentgrenzen
  weiterhin auf hörbare Übergänge geprüft werden.
- Das Video erhält bei 9 s exakt 217 Bilder (9,0417 s Container-Dauer);
  das letzte Bild liegt auf t=9,000 s.

## Was diese Änderung NICHT löst

- Kein echtes zeitliches Modell-Conditioning über Segmentgrenzen hinweg;
  Bewegungsrichtung/Kopfbewegung kann trotz Frame-Identität springen.
- Kein biometrischer Face-ID-Lock; leichte Gesichtsveränderung möglich.
- Keine automatische Farbkorrektur: Globale RGB-Mittelwert-Anpassungen
  können je nach Szene Hauttöne verschlechtern. Erst Farbabweichung im
  echten Clip messen und dann eine begrenzte, szenenabhängige Korrektur
  hinzufügen. Generische Crossfades können Gesichtsdoppelbilder erzeugen.

## Test

`python3 -m pytest -q tests/test_video_segmented.py`

Ein CPU-only FFmpeg-Integrationstest rendert drei Mini-Clips mit Audio
und prüft 217 CFR-Frames bei 24 FPS. Kein realer MLX-Metal-Lauf in CI.

Zuerst denselben **9s-1080p**-Test mit identischem Foto/Prompt vergleichen,
bevor 30s erneut gerendert werden. Segmentgrenzen bei 3 s und 6 s visuell
kontrollieren. Wenn die Bewegung weiterhin springt, ist der korrekte nächste
Schritt ein LTX-Video-Conditioning mit begrenztem Sliding Window, nicht ein
stärkerer statischer Bildanker.
