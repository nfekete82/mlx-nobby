# LTX-2.5 MLX 0.18.0 — isolierter Rollout

Stand: 28.10.2026. **Keine automatische Umstellung der laufenden Installation.**
Upstream: [dgrauet/ltx-2-mlx v0.18.0](https://github.com/dgrauet/ltx-2-mlx/releases/tag/v0.18.0), exakter Commit
`b82b97e3d000e01361f8cfcb745244b15b89a521` (23.10.2026).

## Grundprinzip

- `~/.local/share/mlx-nobby/ltx-2-mlx` bleibt die stabile 0.16.3-Runtime.
- `~/.local/share/mlx-nobby/ltx-2-mlx-v0.18.0` ist das **separate** Staging-Ziel.
- Die bestehenden Q4/Q8-Modellgewichte unter `~/.local/share/mlx-nobby/models` werden **geteilt** und **nicht erneut heruntergeladen**.
- Die bestehende Video-LaunchAgent-Vorlage bleibt absichtlich auf dem stabilen Pfad. `scripts/setup-ltx-video-mlx` bleibt ebenfalls auf 0.16.3 gepinnt.
- `video_mlx_compat.image_conditioning_inputs` verwendet auf 0.18.0 `ImageConditioningInput.at()`, auf 0.16.3 den vorhandenen Konstruktor. Das konservative Keyframe-Preflight erkennt beide Paketlayouts ohne MLX zu laden.
- Die vorhandene Distilled-Pipeline (Q4, 8+3 Schritte, Low-RAM) wird nicht automatisch auf DFR, Dev, Q8, `--refine-audio`, Retake oder Extend umgestellt. `--refine-audio` ist nur für `generate --two-stage`, **nicht** für `--distilled`, verfügbar.

## 1. Repository aktualisieren und Tests ausführen

Arbeiten auf `feat/ltx-mlx-018-safe-rollout-20261028` in `~/mlx-web`.
Vor jedem Branchwechsel sicherstellen, dass keine *versionierten* Änderungen vorliegen.
Unversionierte Benchmarks und lokale LTX-Lab-Dateien nicht löschen.

```bash
cd ~/mlx-web
git fetch origin feat/ltx-mlx-018-safe-rollout-20261028
git switch -c feat/ltx-mlx-018-safe-rollout-20261028 --track origin/feat/ltx-mlx-018-safe-rollout-20261028
python3 -m pytest -q tests/test_ltx_018_rollout.py tests/test_video_mlx_provider.py tests/test_multi_image_video.py tests/test_video_mlx_warm_runtime.py tests/test_ltx_distilled_rollout.py
```

Wenn der Branch schon existiert: `git switch feat/ltx-mlx-018-safe-rollout-20261028` und `git merge --ff-only origin/feat/ltx-mlx-018-safe-rollout-20261028` statt `git switch -c`.

## 2. Neue Runtime parallel installieren

```bash
cd ~/mlx-web
bash scripts/stage-ltx-video-mlx-018
```

Voraussetzungen: Apple Silicon, `git`, `uv`, `python3`, bereits eingerichtetes `ltx-2.5-mlx-q4`-Pack mit `.mlx-nobby-ready`.
Das Staging-Skript überprüft die Release-Pin, installiert die Umgebung mit `uv sync --frozen`, prüft die CLI-Unterbefehle und importiert die API (ohne Video-Generierung).
Es greift **nicht** auf den laufenden Video- oder Agent-Dienst zu.

## 3. Vergleich unter identischen Bedingungen

Nicht auf dem laufenden Produktivdienst testen. Nach erfolgreich abgeschlossener Staging-Installation:

```bash
MODEL="$HOME/.local/share/mlx-nobby/models/ltx-2.5-mlx-q4"
STABLE="$HOME/.local/share/mlx-nobby/ltx-2-mlx/.venv/bin/ltx-2-mlx"
STAGE="$HOME/.local/share/mlx-nobby/ltx-2-mlx-v0.18.0/.venv/bin/ltx-2-mlx"
PROMPT="Slow cinematic camera move across a desert fortress at sunset, natural motion"
mkdir -p "$HOME/.local/share/mlx-nobby/ltx-bench-018"
for VERSION in stable 018; do
  if [ "$VERSION" = stable ]; then CLI="$STABLE"; else CLI="$STAGE"; fi
  echo "=== $VERSION ==="
  time "$CLI" generate --distilled --model "$MODEL" --prompt "$PROMPT" \
    --width 704 --height 480 --frames 97 --frame-rate 24 \
    --seed 12345 --stage1-steps 8 --stage2-steps 3 --low-ram \
    --output "$HOME/.local/share/mlx-nobby/ltx-bench-018/${VERSION}.mp4"
done
```

**Wichtig:** Diese Befehle rechnen zwei echte GPU-Jobs. Erst ausführen, wenn genügend Zeit und Speicher verfügbar sind. Die Unterschiede bei Bildqualität und Audio sind visuell/akustisch zu prüfen; Laufzeitunterschiede nicht ohne mehrere Wiederholungen als allgemeine Beschleunigung interpretieren.

Optional Talking Photo direkt mit dem Staging-Python und eigenen kurzen WAV-/Bild-Testdateien prüfen:

```bash
"$HOME/.local/share/mlx-nobby/ltx-2-mlx-v0.18.0/.venv/bin/python" \
  scripts/ltx-talking-photo-a2v.py --help
```

Dieser Smoke-Test startet keine Generierung. Einen echten A2V-Vergleich erst mit gültigem Quellbild und passendem WAV (16 kHz) durchführen.

## 4. Umschalten — nur nach bestandenen GPU-/Browser-Tests

Der Video-LaunchAgent wird **nur bei explizitem** `--apply` geändert.
Vorher prüft das Skript den exakten 0.18.0-Commit, den installierten CLI, das laufende Video-Service-Health und `status=ready`.
Es erstellt ein Backup des LaunchAgent-PLIST und versucht bei einem Neustartfehler die vorherige Datei wiederherzustellen.

Vorschau ohne Änderung:

```bash
python3 scripts/switch-ltx-video-runtime --to 018
```

Aktivieren (erst nach Benchmark und Testclip):

```bash
python3 scripts/switch-ltx-video-runtime --to 018 --apply
```

Zurück auf stabil:

```bash
python3 scripts/switch-ltx-video-runtime --to stable --apply
```

### Talking Photo ist ein separater Prozess

Der Video-LaunchAgent (`8060`) und der Agent (`8010`) sind getrennte Prozesse. Der Agent wird durch die Video-Umschaltung **nicht** verändert und verwendet ohne separate Konfiguration weiterhin den stabilen Runtime-Pfad. Das ist ein absichtliches Sicherheitsmerkmal: Talking Photo erst getrennt testen und später gezielt migrieren, um funktionsfähige Sprache/Portrait-Generierung nicht versehentlich zu unterbrechen.

## 5. Breakage-/Feature-Liste (0.16.3 → 0.18.0)

- `ImageConditioningInput` ist ab 0.18.0 eine immutable Dataclass aus `utils.types`, die weiterhin durch `utils.args` re-exportiert wird. `.at/.replace/.guide` ersetzen direkte Konstruktor-Aufrufe.
- `keyframe` CLI und `KeyframeInterpolationPipeline` wurden entfernt. Mehrbild-Video bleibt über `generate --distilled --image ...` möglich. Für die neue nicht-destillierte Two-Stage-Interpolation nutzt Upstream `--image ... guide --refine-audio`.
- `ltx_core_mlx.utils.video` wurde entfernt; Nobby verwendet dieses Modul derzeit nicht im geprüften Video-Worker.
- Audio-Relay bei Prompt-Relay-Segmenten verhält sich ab 0.17.0 anders; bestehende Standardgenerierung ohne Segmente ist davon nicht betroffen.
- DFR-Pipelines und Audio-Refinement sind **vorhandene Upstream-Funktionen**, noch keine freigeschalteten Nobby-UI-Funktionen.

## Akzeptanzkriterien

CPU-Test-Suite grün; Staging-CLI und API imports grün; ein Distilled T2V/I2V-Test in beiden Versionen; Mehrbild-Keyframes ohne API-Fehler; Talking Photo A2V mit bestehender Pipeline; keine Speicherdrossel oder abweichende Bildgeometrie; ein Klick-Rollback möglich.

**Keine automatische Aktivierung, kein Modell-Download, kein erzwungener Merge in `main`.**
