# LTX-MLX 0.18: Talking Photo und Video Extend/Retake

## Voraussetzungen und Abgrenzung

- Bereits vorhandene Q4-Modellgewichte unter `~/.local/share/mlx-nobby/models/ltx-2.5-mlx-q4`.
- Verifizierte, **isoliert installierte** Upstream-0.18.0-Runtime unter
  `~/.local/share/mlx-nobby/ltx-2-mlx-v0.18.0`
  (Commit `b82b97e3d000e01361f8cfcb745244b15b89a521`).
- Video-Service `8060` benutzt bereits 0.18.0 und bleibt unverändert.
- Der Agent `8010` nutzt bis zur **separaten** Umstellung weiterhin seine stabile
  bisherige Talking-Photo-A2V-Runtime.
- Weder Modellgewichte noch bestehende Originalvideos werden überschrieben,
  heruntergeladen oder automatisch entfernt.

## Talking Photo sicher auf 0.18.0 umstellen

Die neue Umschaltung betrifft ausschließlich den Agent-LaunchAgent. Beim
`--apply` werden aktive Talking-Photo-Jobs anhand des Job-Status und
der laufende Video-Service geprüft, die Zielruntime verifiziert und die
LaunchAgent-PLIST gesichert. Ein Health-Fehler versucht automatisch
Rollback; zum manuellen Rollback dieselbe Funktion mit `stable` verwenden.

```bash
cd ~/mlx-web
python3 scripts/switch-ltx-talking-photo-runtime --to 018     # Dry Run
python3 scripts/switch-ltx-talking-photo-runtime --to 018 --apply
# Rollback:
python3 scripts/switch-ltx-talking-photo-runtime --to stable --apply
```

**Nicht während laufender Talking-Photo-, Video- oder GPU-Aufträge umschalten.**
Der frühere technische A2V-Test mit 0.18.0 ist bestanden; die bildliche
Lippensynchronität für ein menschliches Porträt muss real geprüft werden.
Die Umschaltung fügt auch keine neuen Talking-Photo-Qualitätsmodi hinzu,
sondern nutzt die bereits eingeführten 8+3, 15+3 und 30+3 Schritte.

## Video Extend und Retake

In der Medienbibliothek ein **bestehendes Video** oder **Talking Photo**
öffnen. In der Vorschau erscheinen zwei neue Aktionen:

- **Video verlängern**: generiert weitere Frames nach der Quelldatei.
  Distilled verwendet das Ende der Quelle als Kontext (mindestens 25 Frames).
- **Bereich neu erstellen**: wählt Start/Ende in Sekunden; das Backend
  richtet den Abschnitt auf LTXs Latent-Frame-Raster aus. Dabei wird
  `--no-regen-audio` verwendet, damit vorhandene Sprache nicht neu
  erzeugt wird.

Beide Operationen sind experimentell. Das Videofenster akzeptiert nur
lokal gespeicherte, LTX-kompatible Videos: 24 fps, 8k+1 Bildframes,
640/704/etc.-Raster in Vielfachen von 64, mindestens 25 und höchstens
1441 Frames. Fremde Dateien, Symlinks, externe URLs, nicht unterstützte
Modelle und unbekannte CLI-Argumente werden abgewiesen.

`LTX-MLX 0.18.0` wird für Edit-Aufträge fest auf dem lokalen, gepinnten
Checkout und Q4-Modell ausgeführt. Der Agent koordiniert die
Ressourcenübergabe und generiert neue, separat gespeicherte Video-IDs
unter `~/.config/mlx-web/videos`, wodurch die neue Version in der
Bibliothek sichtbar wird. Ursprüngliche Quelldateien bleiben unangetastet.

Edit-Endpunkte:
```
GET  /api/mlx/video/edit/status?source_kind=video&source_id=<24hex>
POST /api/mlx/video/edit/jobs
GET  /api/mlx/video/edit/jobs/<24hex>
POST /api/mlx/video/edit/jobs/<24hex>/cancel
```

Beispiel-JSON:
```json
{"source_kind":"video","source_id":"aaaaaaaaaaaaaaaaaaaaaaaa",
 "operation":"extend","prompt":"Continue the desert flyover",
 "distilled":true,"extend_frames":4,"seed":42}
```

**Performance-Hinweis**: Retake/Extend haben je nach Quelldauer, Modell,
Speicherbelegung und Modus möglicherweise hohen Speicherbedarf. Die
Distilled-Modi sind experimentell und kein Garant für identisches
Bild- und Audiomaterial. Zunächst mit 1–4 Latent-Frames und kurzen
LTX-Clips testen.

## Tests und Rollout

```bash
cd ~/mlx-web
test-venv/bin/python -m pytest -q \
  tests/test_video_edit_ltx018.py \
  tests/test_talking_photo_ltx.py \
  tests/test_talking_photo_max_quality.py \
  tests/test_ltx_018_rollout.py
node --check frontend/assets/chat/video-edit.js
node --check frontend/assets/chat/media-library.js
```

Nach GitHub-CI:
```bash
git fetch origin main
git switch main && git merge --ff-only origin/main
docker compose up -d --build --no-deps mlx-web
./scripts/mlx agent restart
```
Die Agent-Runtime schaltet sich dadurch **noch nicht** um; das ist nur
mit dem separaten, expliziten `--apply`-Befehl möglich.

### Validierungsgrenzen

Die CI deckt CPU-Logik, API-Schemata, Sicherheit, JS-Syntax und
Browsertests ab. Der erste echte Render per Extend/Retake auf dem
M5 Max muss lokal erfolgen, weil CI keine passende GPU und keine
Modellgewichte hat. Ergebnisse visuell und akustisch prüfen.
