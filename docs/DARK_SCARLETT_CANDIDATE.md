# Dark Scarlett 27B v2.0 – optionaler Chat-Kandidat (18+)

**Status: CANDIDATE / noch kein Hardware- oder Runtime-Kompatibilitätstest.**
MLX Nobby bleibt standardmäßig bei deinem bisherigen Chatmodell. Diese
Integration registriert auf Wunsch nur einen **separaten Modell-Alias**, kein
neues dauerhaft paralleles Modell, keine automatische Modellinstallation und
keinen automatischen Wechsel des globalen Chatservers.

## Quelle / Speicher / Grenzen

- [MLX-Checkpoint](https://huggingface.co/jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp):
  `jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp`.
- Basis Qwen3.8 27B, spezialisiert durch ReadyArt/Dark-Scarlett-27B-v2.0.
  oQ4e mit gemischter Quantisierung, MLX Safetensors, veröffentlichte
  Größe **ca. 17 GB** (Modell-Dateigröße, **nicht** vollständiger RAM-Bedarf).
- Geeignet als *Testkandidat* für erwachsene fiktionale Dialoge/Rollenspiele;
  keine unabhängig verifizierte Überlegenheit gegenüber Qwen3.8.
- Model Card und upstream Nutzungsbedingungen vor dem Download lesen,
  insbesondere 18+, private/nichtkommerzielle Verwendung nach
  Modellanbieter-Bedingungen; nicht ungeprüft in Firmen-/Kundenprojekten.
- Die im Modell eingebetteten MTP-Tensoren sind **keine Garantie**, dass die
  vorhandene MLX-VLM 0.6.17 Runtime sie nutzt. oQ-Kompatibilität,
  Vision/Chat-Template, Warm-up und Speicherdruck bleiben lokal zu verifizieren.
  Niemals den Produktivstart allein anhand des Hugging-Face-Labels freigeben.

## 1. Separaten Alias registrieren (kein Modellwechsel)

```bash
cd ~/mlx-web
git switch main
git pull --ff-only origin main

./scripts/mlx candidate dark-scarlett status
./scripts/mlx candidate dark-scarlett register
./scripts/mlx models
```

`register` nutzt bewusst nur den bestehenden Befehl
`mlx model add dark-scarlett-27b <HF-Repo>`. Es schreibt
`~/.config/mlx-server/models`, ersetzt **keine** vorhandene andere
Aliasbelegung und lässt `~/.config/mlx-server/config` (aktives `MODEL`),
LaunchAgents, Docker und den aktuell laufenden Modellserver unverändert.
Wiederholtes Registrieren des gleichen Kandidaten ist wirkungslos.
Konflikte oder Symlinks werden sicherheitshalber abgelehnt.

## 2. Gewichte nur nach explizitem Opt-in herunterladen

Vorher genügend **freien Datenträgerspeicher** bereitstellen. Download nur
nach Bestätigung der Lizenz/Nutzungsbedingungen:

```bash
./scripts/mlx download dark-scarlett-27b
```

Die Daten landen über den bestehenden Hugging-Face-Cache, nicht im Git-Repo.
Download ist kein Beleg, dass der Checkpoint mit deinem Runtime-Pin läuft.
Bei Kompatibilitätsfehlern **nicht** `mlx-vlm` im produktiven Runtime-venv
spontan aktualisieren; zuerst einen isolierten Kompatibilitätstest machen.

## 3. Bewusst ausprobieren und zurückwechseln

1. Vorher mit `./scripts/mlx model` und `./scripts/mlx status` das **genau
   aktive** Standardmodell/Profil notieren.
2. Alle Chats, Coding- und Medienjobs beenden. Genügend freien
   Unified Memory und RAM-Reserve sicherstellen; es werden **nicht** zwei
   27B-Chatmodelle gleichzeitig als eigene Chatserver gestartet.
3. Erst wenn du einen Modellwechsel willst:

```bash
# ACHTUNG: Schaltet den globalen Chat-Modellserver auf den Kandidaten um
./scripts/mlx model dark-scarlett-27b
./scripts/mlx status
```

Der vorhandene `mlx model`-Wechsel verändert das aktive `MODEL` und
startet den MLX-Modellserver neu. Nur bei Ruhe durchführen. Dass ein Alias
existiert oder ein Download abgeschlossen ist, hat diesen Effekt **nicht**.

Zum Zurückwechseln den zuvor notierten unveränderten Modellnamen bzw.
den bisherigen Modellpfad verwenden:

```bash
./scripts/mlx model "<DEIN_BISHERIGES_MODELL>"
./scripts/mlx status
```

Die bekannten produktiven RAM-/Swap-Grenzen bleiben aktiv. Kein experimentelles
Hybrid-/DFlash-Profil wird eingeschaltet, kein anderes Modell ersetzt oder
automatisch umkonfiguriert. Falls das Modell nicht fehlerfrei lädt, zurück zum
vorherigen Modell und Logs prüfen; die bestehende Runtime nicht blind upgraden.

## 4. Testkriterien statt allgemeinem Wissens-Leaderboard

Für den Vergleich genügen einige *selbst erstellte, volljährige, fiktive*
Chat-Prompts in beiden Modellen: natürliches Deutsch, kohärenter Dialog,
Charakter-/Stiltreue, Konsistenz nach 10+ Turns, Tempo und tatsächlicher
Unified-Memory-Druck. Prüfe auch unerwartete Ablehnungen und die eigenen
Content-/Nutzungsbedingungen. Der bestehende Chat Quality v1 Benchmark
ist eine einfache Regression-Suite, **kein** aussagekräftiger Erotik- oder
Rollenspiel-Leaderboardtest.

## Verifikation ohne laufendes Modell

```bash
python3 -m pytest -q tests/test_model_candidate.py
./scripts/mlx candidate dark-scarlett status
```

GitHub-CI prüft Registrierung und Schutzmaßnahmen synthetisch; ein echter
Kompatibilitäts-, Qualitäts- und Speichertest auf dem Mac steht bewusst aus.
