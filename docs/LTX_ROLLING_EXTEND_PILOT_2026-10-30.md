# LTX Rolling Window – 10-Sekunden-Pilot, 540p

## Ziel

Die native `ltx-2-mlx extend --distilled`-Implementierung trägt bei jedem
Aufruf **25 Pixel-Frames des Quellvideos** (inklusive Audio-Kontext).
Bisher wurde dafür ein immer länger werdendes Video neu geladen.
Der neue opt-in-Modus übergibt genau 25 Frames und speichert den fertigen
Film nur in einzelnen, überprüften Dateien auf der Festplatte.

## Ablauf

1. 6 s (145 Frames) über die bestehende native LTX-I2V/T2V-Generierung.
2. Letzte 25 Frames und entsprechendes Audio als kleines Kontext-MP4.
3. Native LTX-MLX-0.18-Verlängerung um 6 latente Frames = 48 neue Pixel-Frames.
4. Erste 25 Kontext-Frames aus der Extend-Ausgabe entfernen und nur 48 neue
   Frames in einem eigenen verifizierten Teilcheckpoint speichern.
5. Einmal wiederholen; 145 + 48 + 48 = **241 Frames** = 10 Sekunden Timeline
   bei 24 fps (letztes Frame liegt bei 10.0s).
6. Teilclips als MP4 auf dem Datenträger verbinden. Feste Größe des Modellfensters
   statt immer größerer Quellvideos, kein paralleler Metal-Decoder.

## Sicherheits- und Qualitätsgrenzen

- **Nur explizit** `continuation_mode=rolling`, nur 10 s, 540p, 24 FPS.
- `profile=standard` (Modellprofil), `quality=fast` (540p), LTX-MLX.
- Laufzeit muss genau den geprüften LTX-MLX-Commit verwenden.
- Runtime-Lease, RAM-/Swap-Überwachung, Abbruch, Lifecycle-Stop,
  Checkpoints mit Hash und validierter fortsetzbarer Konfiguration.
- Image-to-Video nutzt das ursprüngliche Bild für die ersten 6 s;
  Folgesegmente verwenden echten Videokontext statt eines einzelnen Bildes.
- Keine Garantie für Gesicht, Farbgebung, Bewegungsqualität oder Lip Sync.
- Nach dem Kurztest kann man 720p und längere Videos separat validieren.

## Test im Chat

Ursprüngliches Porträtbild hochladen und schreiben:

> Erstelle ein 10-Sekunden-Video mit Rolling-Window-Test: The person slowly
> turns their head, smiles naturally, fixed camera, no scene changes.

Im Qualitätsdialog **Schnell (540p), 10 Sekunden** wählen. Wichtig:
Rolling Window wird nur aktiviert, wenn der Ausdruck `Rolling-Window-Test`
im Prompt steht; bei anderen Videoanfragen ändert sich nichts.

## Entwicklungstests

```bash
python3 -m pytest -q tests/test_video_rolling.py tests/test_video_segmented.py
node tests/test_video_job.mjs
```

Die Tests verifizieren echte FFmpeg-Trim-/Concat-Schritte mit Mini-Clips.
Die eigentliche Metal-Generierung muss anschließend auf dem M5-Max geprüft
werden. Bei GPU-/RAM-Fehlern den Job nicht automatisch wiederholt starten.

## Was wir vergleichen

Zeitpunkte 5.9/6.1 und 7.9/8.1 Sekunden: Bewegungsrichtung, Hauttöne,
Augen/Mundform, Haare und Audio. Bei schlechtem Ergebnis bleibt der
bisherige segmentierte Modus unverändert verfügbar.
