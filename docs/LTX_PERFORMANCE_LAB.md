# LTX-Performance-Labor: Phasenmessung und isolierter 0.17.0-Vergleich

Stand: 21. Oktober 2026. Feature-Branch: `feature/ltx-performance-lab-v017`.
Grundlage ist der vollständig gelesene [Auditbericht](LTX_2_5_PERFORMANCE_AUDIT_2026-10-21.md).

**Implementierter Umfang.** `ltx_lab/` ist ein ausdrücklich aktiviertes Testwerkzeug. Die produktiven Worker, Provider, LaunchAgents, Modellgewichte und Einstellungen werden nicht umgestellt. `scripts/benchmark-ltx-video.py --isolated` verwendet direkte Testprozesse und kontaktiert weder die Serviceports 8060/18060/18061 noch Reset-/Generate-Endpunkte. Ohne `--execute --approve-gpu` entsteht keine GPU-Generierung. Im Rahmen dieser Umsetzung wurde kein GPU-Benchmark ausgeführt; ein Qualitäts- oder Geschwindigkeitsgewinn ist noch nicht gemessen.

**Lokal aufgebaute Umgebungen.**

| Umgebung | Commit | Python | MLX |
| --- | --- | --- | --- |
| `.ltx-lab/runtime-v0.16.3` | `ae3b7ea9583db775bd4a1dfb506fb789585021e7` | 3.11.15 | 0.32.2 |
| `.ltx-lab/runtime-v0.17.0` | `62b7651406f8ad4a0b7a3f36a93874a1015d59ca` | 3.11.15 | 0.32.2 |

Beide Verzeichnisse sind unabhängige Git-Kopien mit eigenem venv und eigenen editable LTX-Paketen. `git clone --no-hardlinks` und `uv sync --link-mode copy` vermeiden gemeinsame beschreibbare Paketdateien. Die venvs verwenden denselben installierten Python-Basisinterpreter, aber keine produktiven Site-Packages. Alle 38 Runtimepakete kamen offline aus dem bestehenden uv-Cache. Nur der kleine gepinnte 0.17.0-Quellcodestand wurde aus GitHub nachgeladen. Kein Modell- oder Wheel-Download war nötig. Der Lockfilevergleich 0.16.3→0.17.0 ändert nur die vier LTX-Workspaceversionen; unter den installierten Runtimeabhängigkeiten unterscheiden sich ausschließlich `ltx-core-mlx` und `ltx-pipelines-mlx`.

Die vorhandenen Q4-Modellgewichte werden lediglich über ihren bestehenden lokalen Pfad gelesen. Testdaten, Cache und Medien liegen unter dem ignorierten `.ltx-lab/`. Fehlende Modellkomponenten führen zum Abbruch, nicht zum Download. Hugging Face und Transformers arbeiten offline. Geerbte `LTX2_*`-/`LTX_MLX_*`-Optionen und `PYTHONPATH` werden entfernt; nur die protokollierten Profiloptionen werden neu gesetzt.

Die Produktivinstallation unter `~/.local/share/mlx-nobby/ltx-2-mlx` blieb unverändert: HEAD, Git-Status und Hashes von `uv.lock`, `pyproject.toml` und `.venv/pyvenv.cfg` wurden vor/nach der Einrichtung verglichen. Lokaler Nachweis: `.ltx-lab/production-baseline.json`. Dieser Nachweis ist eine gezielte Checkout-/venv-Konfigurationsprüfung, kein vollständiger Hash sämtlicher Binärdateien oder Modellgewichte.

**API-/Pipeline-Kompatibilität.** Beide Versionen bestehen die AST-Prüfung der tatsächlich ausgecheckten Quellen für:

- `DistilledPipeline`: Konstruktor, T2V/I2V-Generierung, 8+3-Parameter, Bildkonditionierung und Stage-Progress-Hook.
- `A2VidDistilledPipeline`: Audioeingabe, 8+3 und geerbter Konstruktor.
- `A2VidPipelineTwoStage`: Audioeingabe sowie die klassischen Negative-Prompt-/CFG-/STG-Parameter; Labprofil bleibt 15+3, CFG 3, STG 1.
- Instrumentierungshooks an Textencoder, Loadern, Samplern, VAE-Generator und FFmpeg-Streaming.
- Compute-Dtype, Sparse-Stage-2-Implementierung und optionales Stage-1-Resume (nur 0.17.0).

Installierte Paketversionen, venv-Prefix und editable Herkunft werden im jeweiligen Interpreter geprüft, ohne MLX zu importieren. Nach später freigegebenem GPU-Start prüft der Runner zusätzlich die tatsächlich importierten Pipelinepfade. Eine statische API-Prüfung beweist keine Renderparität. Talking-Photo-Lipsync mit MuseTalk, Longform, Sprecherauswahl, I2V-contain/cover und Adapterprofile behalten ihre bestehenden produktiven Pfade; der Laborrunner ersetzt diese Abläufe nicht. Deren bestehende CPU-/Mockregressionstests wurden mitgeprüft. Vollständige End-to-End-Qualitätsabnahme folgt erst nach Freigabe.

**Messverfahren.** Die Hooks existieren ausschließlich im Testprozess und werden auch nach Fehlern wieder entfernt. Gemessen werden:

| JSON-Phase | Umfang |
| --- | --- |
| `model_loading` | Pipeline-/DiT-, Textencoder-, Bildencoder-, Upsampler- und Audiodecoder-Lader; gegebenenfalls klassische LoRA-Fusion |
| `text_encoding` | Ausgeführte positive/negative Gemma-/Connectorberechnung |
| `denoising_stage_1` / `denoising_stage_2` | Tatsächlich abgeschlossene Samplerschritte mit evaluierten Video-/Audiolatents |
| `latent_upsampling` | Distilled-Spatial-Upsampling |
| `image_encoding` | I2V-VAE-Encoding |
| `audio_processing` | Audio-VAE/Vocoder, Quellaudioeinlesen/-encoding und WAV-Verarbeitung |
| `vae_decoding` | Arbeit jedes `next()` am Conv-VAE-Tilegenerator einschließlich Materialisierung; auch Generatorabschluss |
| `frame_conversion_and_delivery` | Framekonvertierung, Bereinigung und Übermittlung an FFmpeg; enthält verschachteltes VAE-Decoding |
| `mux_pipe_backpressure` | Frameübergabe, Warten auf vorherige Schreibvorgänge und Writer-Abschluss |
| `mux_session` | Gesamte FFmpeg-Lebensdauer; `self_seconds` isoliert Startup/Drain außerhalb des Frame-Streaming-Aufrufs |
| `decode_mux_stream` | Gesamter Video-Decode-/Exportpfad |
| `generation` | Synchronisierte Pipeline-Walltime |

MLX wird an Phasengrenzen synchronisiert. Zurückgegebene Arrays und VAE-Tiles werden vor Abschluss materialisiert. Der Step-Timer sitzt nach der tatsächlichen Step-Auswertung und zählt den terminalen Schritt mit. Deshalb entsteht keine irreführende 7/8- oder 2/3-Zeitberechnung. Gemessen wird synchronisierte Walltime, keine reine Hardware-GPU-Zeit.

Jedes Event enthält `inclusive`- und `self`-Zeit, Elternphase und Metal-Messwerte. Verschachtelte Zeiten sind nicht additiv. Insbesondere läuft FFmpeg während des Decodings; `mux_session.inclusive_seconds` darf nicht zur VAE-Zeit addiert werden. `mux_session.self_seconds` enthält den verbleibenden Start-/Drain-Walltimeanteil, nicht die gesamte parallel ausgeführte Encoder-CPU-Zeit. `model_loading.self_seconds` vermeidet die doppelte Zählung verschachtelter Loader. mmap-Lader materialisieren nicht absichtlich alle Gewichte: späteres Paging im Streaming bleibt Teil des Denoisings.

Pro Run gibt es genau einen Metal-Peakreset, vor der Generation. Verschachtelte Phasen setzen den Zähler nicht zurück. `peak_since_run_reset_bytes` ist daher ein kumulativer Run-Peak, kein unabhängiger Peak jeder Phase. Active-/Cachewerte, Steps und ein nominelles 500-ms-CPU-Sampling ergänzen ihn. System-RAM, Swap, Compressor, Page-ins/-outs und Prozess-RSS werden getrennt gespeichert; Samples werden den Phasen per Zeitstempel zugeordnet. Kurze Phasen können keine RAM-Samples enthalten (`null`). Prozess-Lifetime-RSS ist ausdrücklich nicht auf den Warm-Run zurücksetzbar. Der Sampler verwendet keine Metal-APIs auf seinem Hintergrundthread.

Instrumentierung, zusätzliche Synchronisation, ausgeführte Tilematerialisierung und CPU-Sampling verändern Laufzeit und gegebenenfalls Speicherverhalten. Nur gleich instrumentierte Varianten direkt vergleichen. Die historische 138,8-s-Referenz bleibt Kontext und ist keine kontrollierte Messung dieses Labors. Importzeit, Pipelinekonstruktion, synchronisierte Generierungszeit und gesamte Kindprozesszeit stehen getrennt im Ergebnis. Kindprozesszeit enthält auch Prüfung und nachträgliche CPU-Medienauswertung.

**Testprofile.** Die Optionen sind in beiden installierten Versionen vorhanden:

| Profil | `LTX2_COMPUTE_DTYPE` | `LTX2_SOL_TAU` | Bedeutung |
| --- | --- | --- | --- |
| `production-control` | `float32` | `off` | Kontrollprofil entsprechend dem bisher ungesetzten Compute-Schalter |
| `bf16-baseline` | `bfloat16` | `off` | Explizite BF16-Compute-Baseline, weiterhin Q4-Gewichte |
| `fp16` | `float16` | `off` | Nur FP16 Compute |
| `sparse` | `bfloat16` | `1.0,1.25,1.5` | Sparse separat gegenüber BF16 |
| `fp16-sparse` | `float16` | `1.0,1.25,1.5` | Optional kombinierte Variante |

BF16-Baseline und Produktivkontrolle sind absichtlich getrennt: der bisherige Q4-Pfad rechnet relevante DiT-Module standardmäßig in FP32. Sparse ist für T2V/I2V und distilled A2V vorhanden, für klassisches A2V wird das Profil vor Start abgelehnt. Tatsächliche Sparse-Callzahl und effektiver DiT-Dtype werden erfasst. Ein Dense-Fallback oder Compute-Fallback macht den Profil-Run ungültig. Zu kleine Testgeometrien können unter der Sparse-Tokenschwelle bleiben. Kein Schalter reduziert Schritte, Auflösung, FPS oder Audioqualität; niedrigere Compute-Präzision und Sparse sind trotzdem erst nach Qualitätsabnahme akzeptabel.

**Ressourcenschutz und aktueller Befund.** Vor dem ersten GPU-Import sowie vor jedem Warm-Run wird lesend geprüft. Erforderlich sind sichtbare Prozesse, normal bestätigter Speicherdruck, lesbarer Swap und standardmäßig mindestens 20 GiB geschätzt verfügbare Seiten (frei + inaktiv + speculative). Die Schätzung ist konservative Admission, keine Garantie oder exakte freie GPU-Speichermenge; RAM-Belegt und verfügbare Seiten überlappen teilweise in ihrer Definition. Der Schwellwert ist über `--min-available-gib` konfigurierbar, mindestens 16 GiB. Aktive LTX-/VLM-Prozesse blockieren den Test, statt dass sie beendet werden. Ein Laborlock verhindert parallele Controller. Während eines Runs führen kritischer Speicherdruck oder mehr als 256 MiB zusätzlicher gesampelter Swap zum Abbruch an der nächsten Python-Phasen-/Schrittgrenze; laufende Metal-Kommandos lassen sich dadurch nicht mitten im Kernel unterbrechen.

Die lesende Ressourcenprüfung am Umsetzungstag ergab: **nicht zugelassen**, zwei konkurrierende VLM-Prozesse, etwa **11,9 GiB** geschätzte verfügbare Seiten, etwa **13,6 GiB** bereits belegter Swap, Pressure normal. Kein GPU-Lauf wurde gestartet und kein Dienst wurde entladen. Eine spätere Freigabe muss die dann aktuelle Ressourcenlage berücksichtigen. Die Umsetzung ist keine solche Freigabe.

**Sichere Kommandos ohne GPU-Generierung**, jeweils aus `~/mlx-web`:

```bash
# Reproduzierbarer Offline-Aufbau, wenn der gepinnte Quellcode lokal vorhanden ist.
python3 -B -m ltx_lab.setup --versions 0.16.3 0.17.0

# Falls nur der Quellcode fehlt: kleine Git-Quelle erlaubt, Pakete weiterhin offline.
python3 -B -m ltx_lab.setup --versions 0.17.0 --allow-source-fetch

# Statische Verträge und installierte Paketpfade prüfen, kein MLX-Import.
python3 -B scripts/benchmark-ltx-video.py --isolated --check

# Lesende Ressourcenprüfung; kein API-Aufruf an produktive Dienste.
python3 -B scripts/benchmark-ltx-video.py --isolated --preflight

# Plan anzeigen, weder Generierung noch Service-Steuerung.
python3 -B scripts/benchmark-ltx-video.py --isolated \
  --profiles production-control bf16-baseline fp16 sparse fp16-sparse --warm-runs 0
```

Fehlt ein gecachtes Paket, bricht `uv --offline` ab. Dann zuerst den konkreten Downloadbedarf prüfen; keinen allgemeinen Online-Sync oder das produktive Setupskript ausführen. Die Laborverzeichnisse sind ortsabhängig (editable Installationen); nach Verschieben des Projekts neu validieren/einrichten.

**Benchmarkkommandos ausschließlich nach Ressourcenprüfung und ausdrücklicher GPU-Freigabe.** Diese Beispiele wurden nicht ausgeführt:

```bash
# Empfohlener erster Lauf: bisherige Compute-Methode in beiden Versionen,
# je ein frischer Testprozess, unveränderte 1280x704 / 121 Frames / 24 FPS / 8+3.
python3 -B scripts/benchmark-ltx-video.py --isolated \
  --versions 0.16.3 0.17.0 --profiles production-control \
  --seed 42 --width 1280 --height 704 --frames 121 --fps 24 \
  --warm-runs 0 --execute --approve-gpu

# Danach auf bestandener 0.17.0-Kontrolle BF16 und FP16 vergleichen.
python3 -B scripts/benchmark-ltx-video.py --isolated \
  --versions 0.17.0 --profiles bf16-baseline fp16 \
  --start-mode both --warm-runs 3 --execute --approve-gpu

# Sparse separat gegen die BF16-Baseline; Kombination optional als eigene Variante.
python3 -B scripts/benchmark-ltx-video.py --isolated \
  --versions 0.17.0 --profiles bf16-baseline sparse \
  --start-mode both --warm-runs 3 --execute --approve-gpu

python3 -B scripts/benchmark-ltx-video.py --isolated \
  --versions 0.17.0 --profiles fp16 fp16-sparse \
  --start-mode both --warm-runs 3 --execute --approve-gpu
```

Standardprompt ist der dokumentierte Sportwagen-im-Regen-Prompt des vorhandenen Benchmarkskripts. Für eine exakte Reproduktion der Nutzerreferenz muss deren ursprünglicher Prompt über `--prompt-file /ABSOLUT/prompt.txt` angegeben werden; dieser wurde nicht aus der Referenz rekonstruiert. Seed, Prompt, Eingabemedien-Hashes, Geometrie, Modell-Config und eine Gewichtsdatei-Metadatenliste werden für sämtliche Varianten identisch gespeichert. Der Manifestvergleich über Größe/mtime ersetzt keinen vollständigen Gewichts-Contenthash.

`--start-mode both --warm-runs 3` erzeugt einen Cold-Run und drei Warm-Runs im gleichen Prozess. `cold` erzeugt entsprechend vier frische Prozesse. `warm` markiert den ersten Lauf als Warmup und danach drei Messungen. Cold bedeutet frischer Pythonprozess, kein geleerter macOS-Dateicache. Warm bezeichnet Prozess-/Pipeline-Reuse; Low-Memory bleibt aktiv und Modellgewichte werden weiter neu geladen. Es gibt keinen Service-Reset.

Für Bild-/Audioabhängigkeiten können zusätzlich isolierte Pipelinefälle geplant werden:

```bash
# Nur Dry-run; --execute --approve-gpu erst nach gesonderter Freigabe ergänzen.
python3 -B scripts/benchmark-ltx-video.py --isolated --versions 0.17.0 \
  --pipeline i2v --image /ABSOLUT/referenz.png --profiles production-control --warm-runs 0

python3 -B scripts/benchmark-ltx-video.py --isolated --versions 0.17.0 \
  --pipeline a2v-classic --image /ABSOLUT/referenz.png --audio /ABSOLUT/sprache.wav \
  --profiles production-control --warm-runs 0

python3 -B scripts/benchmark-ltx-video.py --isolated --versions 0.17.0 \
  --pipeline a2v-distilled --image /ABSOLUT/referenz.png --audio /ABSOLUT/sprache.wav \
  --profiles production-control --warm-runs 0
```

Diese Pipelinefälle verwenden direktes Upstream-I2V/A2V-Preprocessing. Sie führen nicht Nobbys zusätzlichen contain/cover-, Lead-in-/Padding-, Segmentierungs- oder MuseTalk-Ablauf aus. Für A2V muss das Eingabeaudio selbst lang genug für die gewählte Framezahl sein. Die Unterscheidung verhindert eine fälschliche Qualitätsfreigabe der vollständigen Talking-Photo-Funktion anhand eines reinen Pipelinebenchmarks.

**Ergebnisse und Qualitätsvergleich.** Jede Suite erhält ein neues Verzeichnis `.ltx-lab/results/<Zeit>-<ID>/`. Vorhandene Ergebnisse werden nicht überschrieben. Darin liegen `suite.json`, Request-JSONs, Kindprozesslogs, `results.json` und pro Run `result.json`, Video-MP4, aus der Ausgabe dekodiertes PCM-WAV, FFprobe-JSON, Framehashes, erster/mittlerer/letzter PNG-Frame und ein auszufüllendes `quality-review.json`. Ergebnisse enthalten Parameter, Paket-/Quellversionen, Phasenereignisse, sämtliche Steps, RAM-/Swap-Samples und die Qualitätsartefaktpfade. Fehler schreiben soweit möglich ebenfalls Teilergebnisse; Exitcode ist dann ungleich null. Medienauswertung erfolgt nach der gemessenen Generation.

Nach zwei abgeschlossenen, eingabegleichen Runs kann ein CPU-Vergleich erstellt werden:

```bash
python3 -B scripts/benchmark-ltx-video.py --isolated --compare \
  /ABSOLUT/referenz/run-00/result.json /ABSOLUT/kandidat/run-00/result.json
```

Das Ergebnis unter `.ltx-lab/comparisons/<ID>/comparison.json` enthält FFmpeg-PSNR/SSIM, dekodierte Framehash-Gleichheit und PCM-Artefaktgleichheit. Seed-/Prompt-/Inputabweichungen werden abgelehnt. Audio-Metadaten, RMS, Peak und Anteil gesättigter PCM-Samples stehen zusätzlich im Run. Das bewertet die exportierten Codecartifakte, nicht interne Latentparität. Hör- und Sichtprüfung bleibt zwingend; automatische `quality_accepted`-Felder bleiben `null`.

Reviewverfahren: A/B-Zuordnung verdecken, beide Clips bei normaler Geschwindigkeit und nativem Maßstab mehrfach ansehen und auf Kopfhörern hören. Bewegungsqualität, Bildschärfe, zeitliche Konsistenz, Gesichter/Anatomie, Audioqualität und Artefakte getrennt auf derselben 1–5-Skala dokumentieren. Nicht vorkommende Gesichter/Anatomie ausdrücklich als nicht beurteilbar markieren, keinen Score erfinden. Ein Referenzsatz braucht neben dem Sportwagen mindestens Gesicht/Sprache, Hände/Anatomie, feine Texturen und kontinuierliche Kamerabewegung; gleiche Eingaben jeweils über alle Profile verwenden. Lip-Sync, Audioende, Identität und Flimmern an Segmentgrenzen zusätzlich prüfen. Jede sicht-/hörbare Verschlechterung verwirft den Kandidaten. Ein PSNR-/SSIM-Wert allein gibt kein Profil frei.

**Tests und Validierungsstand.** Neue Tests in `tests/test_ltx_lab.py` verwenden Fake-MLX mit tatsächlich verzögerter Auswertung, simulierte Pipeline-/Sampler-/VAE-Module und isolierte Testprozesse. Sie prüfen Phase-/Step-Timing einschließlich terminalem Schritt, exklusive vs. überlappende Zeitanteile, Wiederherstellung der Hooks, Cold-/Warmplanung und vollständige Run-JSONs, Ressourcen-/Freigabesperren, Swap-Stopp, Environmentbereinigung, Profilablehnung, Symlink-/Pfadschutz, Eingabefingerprints und beide real installierten venv-Metadaten. Ein winziger synthetischer FFmpeg-CPU-Test erzeugt und vergleicht 64×64-Video plus Sinusaudio; dies ist keine LTX-Generierung und kein GPU-Benchmark.

```bash
PYTHONDONTWRITEBYTECODE=1 agent-venv/bin/python -B -m pytest \
  tests/test_ltx_lab.py tests/test_video_mlx_provider.py \
  tests/test_video_mlx_warm_runtime.py tests/test_video_progress_counts.py \
  tests/test_video_benchmark_telemetry.py tests/test_ltx_benchmark_telemetry.py \
  tests/test_ltx_distilled_rollout.py tests/test_talking_photo_ltx.py \
  tests/test_talking_photo_quality_audio.py tests/test_talking_photo_lifecycle.py \
  tests/test_talking_photo_longform.py tests/test_talking_photo_speaker_ltx.py \
  tests/test_video_uncensored_profile.py -q
```

Der Repository-Testschutz isoliert Pfadauflösung und Runtime-Leases. Ergebnis des obigen Testumfangs: **150 Tests bestanden, zusätzlich 74 Subtests bestanden**, davon **38 neue Labortests**; keine übersprungenen Tests. Zwei bestehende Deprecation-Warnungen betreffen Starlette/httpx und AnyIO im Talking-Photo-Testclient. E2E-/GPU-Tests wurden nicht aufgerufen. Lokale Nachweise: `.ltx-lab/tests.xml`, `.ltx-lab/compatibility-current.json`, `.ltx-lab/validation-summary.json` und `.ltx-lab/dry-run.json`. Die erneute Prüfung bestätigt `production_unchanged=true`.

**Rollback.** Es gibt aktuell keinen produktiven Upgradezustand zurückzurollen: Produktivpfad, Pin und LaunchAgents zeigen weiterhin auf 0.16.3. Einen laufenden Labcontroller mit Ctrl-C abbrechen; er signalisiert ausschließlich seiner selbst gestarteten Kindprozessgruppe, einschließlich deren FFmpeg-Prozess. Keine `launchctl`-/Service-Reset-/Modelllöschbefehle verwenden. Neue Experimente werden nur über `--isolated` gestartet; den Schalter wegzulassen würde den bisherigen API-Benchmarkpfad verwenden und ist kein Rollbackkommando. Für einen Code-Rollback den Feature-Commit auf dem Feature-Branch rückgängig machen bzw. nach gesichertem Arbeitsstand auf den unveränderten Mainstand wechseln. Testdaten und beide venvs können zur Nachvollziehbarkeit liegen bleiben. Eine spätere produktive Übernahme benötigt eine eigene Entscheidung und ein Wartungsfenster.

**Verbleibende Risiken.** Zusätzliche Synchronisation und CPU-Sampling erzeugen Messoverhead. Statische Verträge und Mocktests können Metal-/Kernel-/Speicherfehler nicht ausschließen. Sparse nutzt interne Steel-Header und kann auf dem Zielgerät zurückfallen; Compute-Präzision kann Bild und Audio verändern. 48-GB-Admission kann durch andere Prozesse während des Runs überholt werden, bestehender Swap kann Paging verursachen. Ein Abbruch an Python-Grenzen schützt nicht vor einem bereits laufenden langen Metal-Kommando. Warm-Reuse nach Fehlern wird nicht versucht; der betroffene Testprozess endet. Qualitätsabnahme und echte T2V/I2V/A2V-Renderparität stehen aus. Es wird kein Profil automatisch übernommen und nichts nach `main` gemergt.
