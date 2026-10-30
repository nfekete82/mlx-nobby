# LTX: RAM-sichere Langvideos (30/60 Sekunden)

## Warum dieser Modus existiert

Der bisherige `video_long.py`-Pfad erweitert bei 1080p das **gesamte**
vorherige Video erneut. Die Zahl der Frames steigt bei 30 s auf 721.
Auf einem 48-GB-Mac kann daher der aktive RAM-Schutz bei 20 % verfügbarem
Systemspeicher oder bei 0,5 GB Swap-Zuwachs eingreifen. Das ist eine
bewusste Schutzfunktion und darf nicht deaktiviert werden.

## Umsetzung

Bei `duration` 30 oder 60 Sekunden schaltet `video_service`
automatisch auf `video_segmented.py` um. Der normale 5–20-s-Pfad bleibt
unverändert.

| Zielprofil | Einzelsegment | 30 s | 60 s |
| --- | ---: | ---: | ---: |
| 1080p | 3 s (73 Frames) | 10 | 20 |
| 720p | 5 s (121 Frames) | 6 | 12 |
| 540p | 6 s (145 Frames) | 5 | 10 |

Die Clips werden nacheinander unter **einer** Video-Runtime-Lease
generiert. Der vorherige letzte Frame wird per FFmpeg extrahiert und
als I2V-Ausgangsbild an den nächsten Render geschickt. Der
LTX-MLX-Worker wird nach **jedem** Segment hart beendet. Das schützt
vor sich über Segmente hinweg ansammelnden Metal- und Python-Reserven.

Während jedes Segmentjobs wird `memory_budget_snapshot` alle zwei
Sekunden neu erhoben und `ensure_active_memory_safe` verwendet.
Der Grenzwert bleibt unverändert. Beim Überschreiten wird der
Worker beendet und der letzte bestätigte Checkpoint bleibt erhalten.

Erfolgreiche MP4-Segmente besitzen einen SHA-256-Eintrag in einem
atomar geschriebenen Manifest. Die Fortsetzung akzeptiert ausschließlich
unveränderte Modelle, Einstellungen und Originalbilder. Ein altes
**Extend**-Checkpoint ist **nicht** mit dieser Strategie kompatibel.
Nach der erfolgreichen Veröffentlichung des endgültigen MP4
werden die temporären Segmente gelöscht; bei Fehlern bleiben sie erhalten.

Der FFmpeg-Concat-Demuxer setzt die Clips mit Video-/Audio-Stream-Copy
zusammen, damit nicht mehrere 1080p-Clips gleichzeitig dekodiert werden.

## Qualität und Grenzen

Die segmentierte Methode vermeidet stetig wachsende latente
Video-Tensoren, garantiert aber **keinen nahtlosen Film**.
An Übergängen können Bewegungen, Mimik oder Audio kurz springen.
Das letzte Bild hilft beim Erscheinungsbild, nicht bei dynamisch
durchgehender Bewegung. Der Gesamtspeicherbedarf wird auch bei
kurzen Segmenten nicht als absolute Obergrenze garantiert.

## Test / Rollout

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/feat/ltx-30s-segmented-memory-fix-20261030

python3 -m pytest -q \
  tests/test_video_segmented.py \
  tests/test_video_long.py \
  tests/test_video_mlx_provider.py \
  tests/test_video_mlx_warm_runtime.py

node tests/test_video_job.mjs

# Aktuelle lokale Messwerte
memory_pressure
sysctl vm.swapusage
tail -n 100 ~/.config/mlx-web/ltx-mlx-runtime.log
```

Für einen GPU-Akzeptanztest zunächst **30 s / 1080p** und danach
**60 s / 1080p** erzeugen. Nach jedem Segment `memory_pressure` und
`vm.swapusage` beobachten und MP4-Bild-/Audiogrenzen prüfen.
Keine automatischen echten GPU-Tests in CI; CPU-Mocks sind kein
Beweis für den maximalen RAM-Bedarf auf dem Zielgerät.
