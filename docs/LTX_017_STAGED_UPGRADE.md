# LTX 2.5 MLX: abgesicherte 0.17.0-Stufe (opt-in)

Stand 21.10.2026. Der produktive Checkout bleibt auf **0.16.3** (`ae3b7ea9583db775bd4a1dfb506fb789585021e7`).
Die neue 0.17.0-Auswahl ist im Video-Provider implementiert, **aber nicht eingeschaltet**. Sie verändert weder Gewichte,
Live-Dienste, LaunchAgents noch bestehende lokale Laborarbeiten. Keine GPU-Generierung wurde durch diesen Git-Commit ausgelöst.

## Version auswählen

Standard: kein Schalter oder `LTX_MLX_ENGINE_VERSION=0.16.3` → bestehender
`~/.local/share/mlx-nobby/ltx-2-mlx`-Checkout mit den bisherigen `LTX_MLX_*`-Optionen.

**Ausschließlich nach bestandenem A/B-Test und in einem freigegebenen Wartungsfenster:**
`LTX_MLX_ENGINE_VERSION=0.17.0` im *Video-Service-Prozess* setzen (beispielsweise über die
vorhandene LaunchAgent-Umgebung). Der Video-Provider verwendet dann ausschließlich
`~/mlx-web/.ltx-lab/runtime-v0.17.0`, samt dessen eigener `.venv`.
Vor jedem Worker- und CLI-Start erfolgt eine CPU-seitige Prüfung:
- exakter Upstream-Pin `62b7651406f8ad4a0b7a3f36a93874a1015d59ca`;
- sauberer Git-Checkout und bestehende Distilled-/I2V-/A2V-API-Verträge;
- beide installierten LTX-Pakete in Version 0.17.0 mit korrekter Editable-Herkunft;
- Interpreter und CLI müssen zur **isolierten** Runtime gehören.

Andere Pfade/Pins werden abgelehnt statt stillschweigend auf 0.16.3 zurückzufallen.
Die genaue Engineversion erscheint im Availability-Status. Bestehende
Low-RAM-/Q4-/8+3-/Audio- und Worker-Modi bleiben unverändert.
`scripts/setup-ltx-video-mlx` bleibt absichtlich auf der produktiven 0.16.3 gepinnt.

**Rollback:** Den Schalter `LTX_MLX_ENGINE_VERSION` wieder entfernen (oder auf 0.16.3
setzen) und erst bei inaktiver Video-Jobqueue den Video-Service regulär neu starten.
Keine Checkouts löschen, keine Modellgewichte ändern. Ein Wechsel zur Laufzeit ohne
Neustart des Video-Service ist nicht vorgesehen. Talking Photo / separate MLX-Runner
sind ausdrücklich **nicht** durch diesen Schalter umgestellt.

## Genau ein geplanter GPU-A/B-Vergleich

Die beiden unabhängigen Runtimeverzeichnisse sind laut Laborbericht vom 21.10. bereits eingerichtet.
Vor der GPU-Freigabe sicherstellen, dass keine aktiven Chat-, Video- oder anderen Modelljobs
laufen und die vorhandene konservative Ressourcenprüfung besteht. Sie wird nicht umgangen.
Der folgende eine Durchlauf nutzt je einen **kalten** 5-Sekunden-T2V-Clip,
gleichen Prompt/Seed/Geometrie/Audio, gleichen FP32-Compute-Pfad und Q4-Gewichte:

```bash
cd ~/mlx-web &&
python3 -B scripts/benchmark-ltx-video.py --isolated --preflight &&
python3 -B scripts/benchmark-ltx-video.py --isolated \
  --versions 0.16.3 0.17.0 --profiles production-control \
  --seed 42 --width 1280 --height 704 --frames 121 --fps 24 \
  --warm-runs 0 --execute --approve-gpu
```

Die CLI prüft vor dem Ausführen die Ressourcen und lässt Produktionsports, Modelle
und LaunchAgents unangetastet. `--approve-gpu` ist eine bewusste lokale Freigabe;
der GitHub-Commit führt den Befehl **nicht** aus. Ergebnisse liegen unter
`.ltx-lab/results/` (nicht versioniert).
Dauer, Peak-RAM, Swap, Phase 2, Bildqualität, Audio und Fehler müssen ausgewertet werden.
Bei fehlgeschlagenem Admission-Check **nicht** den Schutzschwellwert senken,
nicht automatisch produktive Modelle entladen und nicht in Schleifen erneut testen.

**Go/No-Go:** Eine funktions- und qualitätsverträgliche 0.17.0-Probe sowie
genügend Reserven sind Voraussetzung für die spätere produktive Umschaltung.
Diese Stufe ist Vorbereitung/opt-in-Code, kein belegter Speedup.

Bezug: [Performance-Labor](LTX_PERFORMANCE_LAB.md), [Cold-Ressourcenbericht](LTX_COLD_COMPARISON_2026-10-21.md).
