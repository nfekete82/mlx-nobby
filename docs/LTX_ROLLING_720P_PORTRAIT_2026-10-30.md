# LTX Rolling Window – 720p / Hochformat / RAM-Telemetrie

## Umfang

- Weiterhin **opt-in** über `Rolling-Window-Test` bzw. `continuation_mode=rolling`.
- 10 Sekunden / 24 FPS, entweder 540p oder 720p; 1080p weiterhin gesperrt.
- Querformat: 1024×576 (540p) / 1280×704 (720p).
- Hochformat: 576×1024 (540p) / 704×1280 (720p).
- Jeweils 6 s Ausgangsvideo + 2 s + 2 s native LTX-MLX-0.18-Extend.
- Pro Extend nur die letzten 25 Videoframes + Audiokontext, keine
  vollständige erneute Kodierung des gesamten Filmes durch das Modell.
- Pro Abschnitt persistierte RAM-/Swap-Snapshots (`rolling_stage_memory`),
  Gesamtdauer und Sicherheitsprüfung vor/nach jedem Abschnitt.
- Hochformatfoto wird beim Rolling-Window-Test im Video-Dialog automatisch
  als 9:16 vorausgewählt, sofern Bildabmessungen erkennbar sind.
  Manuelle Auswahl hat Vorrang. Keine automatische Beschneidung:
  `contain` erhält das Original. Bei nicht passendem Seitenverhältnis
  bleiben eventuell kleinere Balken; für einen bildfüllenden Ausschnitt
  müsste explizit `cover` verwendet werden.

## Erster Mac-Test

1. Zuerst `python3 -m pytest -q tests/test_video_rolling.py` und
   `node tests/test_video_job.mjs` ausführen.
2. Video- und Agent-Dienste nur im Idle-Zustand neu starten;
   Web-Docker-Container für neue UI rebuilden.
3. Originalfoto hochladen. Prompt:
   `Erstelle ein 10-Sekunden-Video mit Rolling-Window-Test: The person
   slowly turns their head and smiles naturally. Fixed camera,
   consistent lighting, natural movement, no scene changes.`
4. Im Video-Dialog **Standard (720p)**, **Hochformat**, **10 s** wählen.
5. Nach Abschluss unter `Info` die drei RAM-/Swap-Messungen prüfen.
6. Übergänge bei 6 s und 8 s, Farbe, Identität, Lippenbewegung und
   Ton vergleichen. Nur wenn der 720p-Test akzeptiert ist, weiter
   zu längerem Rolling Window oder höherer Auflösung.

## Grenzen

Der 720p-Modus ist ein GPU-Pilot. CI testet CPU-/FFmpeg-Logik,
nicht den tatsächlichen Metal-Speicherbedarf. Kein automatischer
Fallback zu 540p, weil der Test falsche Qualitätsaussagen liefern würde.
Keine automatische Farbänderung; Hauttöne müssen zuerst am realen
Video beurteilt werden. Bestehende 540p-Pilotjobs und der
RAM-sichere 1080p-Segmentmodus bleiben unverändert.
