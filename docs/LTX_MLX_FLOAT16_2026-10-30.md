# Native LTX-MLX: Float16 als Standard (30.10.2026)

## Ausgangslage

Auf dem M5-Max mit LTX-2.5-MLX-Q4, Runtime 0.18.0, identischem Prompt/Seed (42), 1280 × 704, 121 Frames bei 24 FPS und Distilled 8+3:

| Präzision | Wall-Zeit | Decoding/Audio/Mux |
| --- | ---: | ---: |
| `LTX2_COMPUTE_DTYPE=float32` | 144,22 s | 30,7 s |
| `LTX2_COMPUTE_DTYPE=float16` | 120,84 s | 31,0 s |

Float16 sparte **23,38 s (16,2 % Renderzeit)**. Der Nutzer hat die beiden MP4s verglichen und keinen sichtbaren Qualitätsunterschied festgestellt. Dies ist ein einzelner A/B-Lauf, kein allgemeines Performanceversprechen. Die eingesetzten Q4-Gewichte werden nicht geändert.

## Implementierung

`video_providers_mlx.py` stellt für den **nativen MLX-Provider** vor dem Start eines Subprozesses die upstream-gelesene Umgebungsvariable `LTX2_COMPUTE_DTYPE` auf `float16` ein. Dies geschieht sowohl für den persistenten Python-Worker als auch für den CLI-Fallback. Die übrigen Dienste (Chat, Bilder, Speech, Agent, MPS-LTX) erhalten keine zusätzliche Variable und werden nicht modifiziert. Schritte, Qualität, Auflösung, Audio, Low-RAM, Worker-Lebensdauer und bestehende Modellgewichte bleiben erhalten.

Priorität:

1. `LTX_MLX_COMPUTE_DTYPE=float32` oder `float16` im Video-LaunchAgent bzw. Dienstprozess (explizite Nobby-Einstellung).
2. Sonst bereits vorhandenes `LTX2_COMPUTE_DTYPE` im Video-Dienstprozess.
3. Sonst **`float16`** als neuer Standard.

Andere Werte werden mit klarer Fehlermeldung abgewiesen. Die neue LaunchAgent-**Vorlage** erhält `LTX_MLX_COMPUTE_DTYPE=float16`, sie ändert bei einem Git-Pull **nicht** die bereits installierte Benutzer-PLIST. Der Python-Default funktioniert deshalb auch für bestehende Installationen.

## Aktivierung

Bei einem laufenden Job **nicht** deployen oder den Dienst neu starten.

```bash
cd ~/mlx-web
git fetch origin perf/ltx-mlx-float16-default-20261030
git switch perf/ltx-mlx-float16-default-20261030
git merge --ff-only origin/perf/ltx-mlx-float16-default-20261030
python3 -m pytest -q tests/test_video_mlx_provider.py tests/test_video_mlx_warm_runtime.py
curl -fsS http://127.0.0.1:8060/health | python3 -m json.tool
# Nur wenn status=ready und active_job_id=null:
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-video"
curl -fsS http://127.0.0.1:8060/health | python3 -m json.tool
```

`launchctl kickstart` startet nur den Video-Dienst neu, nicht Web, Agent, Talking Photo oder Bildmodelle. Die bisher aktivierte 0.18.0-Runtime bleibt aktiv. Einen echten T2V-/I2V-Test in Nobby mit Float16 erst nach dem Dienstneustart ausführen.

## Rückfall auf Float32 ohne Codeänderung

`LTX_MLX_COMPUTE_DTYPE=float32` im bestehenden `~/Library/LaunchAgents/de.nobby.mlx-video.plist` unter `EnvironmentVariables` eintragen bzw. den Wert von `float16` auf `float32` ändern, nachdem der Video-Dienst keine Jobs mehr bearbeitet. Vorher die PLIST sichern. Zum Einlesen der neuen EnvironmentVariables muss der LaunchAgent **bootout** und **bootstrap** erhalten; `kickstart` allein lädt geänderte PLIST-Variablen nicht neu.

Für erneutes Float16 den Eintrag wieder auf `float16` setzen oder entfernen. Änderungen am MLX-Nobby-Code, Modellgewichten und anderen LaunchAgents sind für den Rückfall nicht erforderlich.

## Tests

`tests/test_video_mlx_provider.py` prüft den Default, beide Override-Wege, ungültige Werte und die beim tatsächlichen Start an den MLX-Worker bzw. den CLI-Fallback übergebene Umgebung.
