# LTX 2.5 in MLX-Nobby: technischer Performancebericht

Stand: 21. Oktober 2026. Zielgerät laut Nutzer: MacBook Pro M5 Max, 48 GB Unified Memory. Lokal gelesenes macOS: 26.6.2 (25G83).

**Ergebnis:** Der produktive MLX-Checkout ist sauber und exakt auf **0.16.3 / ae3b7ea9583db775bd4a1dfb506fb789585021e7** gepinnt. Der größte belegte Rechenanteil liegt in Stage 2. FP16 und Sol block-sparse Attention sind schon installiert. Ein Upgrade allein aktiviert diese Optionen nicht. Die sichersten nächsten Schritte sind bessere Phasenmessung, ein isolierter 0.17.0-Vergleich und begrenzte, phasenabhängige Cacheversuche. Vollständige Modellresidenz ist auf Grundlage der bisherigen RAM-Messung nicht zu empfehlen.

**Umfang und Grenzen:** Ausschließlich lesende Untersuchung von Quellcode, Paketmetadaten, Prozessliste, Modell-Dateimetadaten, Jobmetadaten und vorhandenen Logs sowie Recherche in offiziellen Projektquellen. Keine Inferenz, keine Benchmarks, keine Modellimporte mit GPU-Initialisierung, keine Installation, kein Checkoutwechsel, keine Dienststeuerung und keine Konfigurationsänderung. Neu erstellt wurde nur dieser Bericht. Bestehende unversionierte Projektdateien wurden erhalten. Versionsvergleich anhand der veröffentlichten Releases und ausgewählter Implementierungs-PRs; kein vollständiger lokal ausgecheckter 0.17.0-Diff und kein Laufzeit-Kompatibilitätsnachweis.

**1. Tatsächliche Installation und Architektur**

| Bestandteil | Lokal festgestellt |
| --- | --- |
| MLX-Engine | `~/.local/share/mlx-nobby/ltx-2-mlx`, Remote `dgrauet/ltx-2-mlx` |
| Runtime-Patches | Commitgebundene Patchserie für ae3b7ea ist leer; Checkout ohne lokale Änderungen |
| Inferenz-Python | Engine `.venv/bin/python`, CPython **3.11.15**, Homebrew Python 3.11; isoliertes uv-venv |
| Pakete | `ltx-core-mlx` und `ltx-pipelines-mlx` **0.16.3**, beide editable auf den Engine-Checkout |
| MLX | `mlx` / `mlx-metal` **0.32.2**, `mlx-lm` **0.31.1** |
| Weitere zentrale Pakete | NumPy **2.4.3**, Transformers **5.3.0**, Safetensors **0.7.0**, mlx-arsenal **0.2.4**, huggingface-hub **1.7.1**, Pillow **12.1.1**, tqdm **4.67.3**, tokenizers **0.22.2** |
| PyTorch / PyAV im MLX-venv | Nicht installiert; der native MLX-Pfad benötigt sie nicht |
| Video-Service | LaunchAgent startet `image-venv/bin/python -m uvicorn video_service_dispatch:app`, Port **8060** |
| MLX-Worker | Separater Prozess aus dem Engine-venv, `video_mlx_worker.py`, lokales HTTP **18061**, Parent-Watchdog, Generation-Lock |
| Worker-Lebensdauer | Standardmäßig persistent, standardmäßig 300 Sekunden Idle-Timeout |
| Gewichtslebensdauer | `low_memory=True`: Gemma, DiT, Upsampler und Decoder werden phasenweise freigegeben; kein vollständiger Gewichts-Reuse zwischen Aufträgen |
| Low-RAM | Installierter LaunchAgent setzt `LTX_MLX_LOW_RAM=1`; letzter passender Job bestätigt `low_ram=true`, `worker_mode=persistent` |

Das Root-Projekt `ltx-2-mlx` hat im venv keine eigene Distribution-Metadatei; die CLI stammt aus `ltx-pipelines-mlx`. Ein fehlgeschlagenes `metadata.version('ltx-2-mlx')` wäre deshalb kein Installationsfehler. Checkoutversion, beide tatsächlich installierten Pakete und editable Herkunft stimmen überein.

Zum Zeitpunkt der Prozessaufnahme lief kein `video_mlx_worker.py`, `ltx2_server.py` oder Talking-Photo-LTX-Runner. Das passt zur bedarfsgesteuerten Architektur; es wurde kein Worker gestartet. Der aktuell geerbte Prozess-Environment einer laufenden Generierung konnte deshalb nicht geprüft werden. Im gelesenen Video-LaunchAgent sind weder `LTX2_COMPUTE_DTYPE` noch `LTX2_SOL_TAU` gesetzt. Die Standardpfade sind somit FP32 innerhalb der relevanten DiT-Module und dichte Attention, sofern keine zusätzliche geerbte Konfiguration eingreift.

Der Modellpack ist **gemischt quantisiert**: `quantize_config.json` nennt 4 Bit und Gruppengröße 64 für Transformer-Block-Linears und Gemma-Attention/MLP-Linears. „Q4“ bedeutet weder vollständig vierbittige Komponenten noch FP16 Compute. Dateigrößen: distilled DiT **10,54 GiB**, Textencoder **9,84 GiB**, Connector **3,76 GiB**, Spatial-Upsampler **0,93 GiB**, Conv-VAE-Decoder **0,76 GiB**. Dies sind Dateigrößen, keine gleichzeitigen Resident-Speicherwerte. Dev-DiT und Distillation-LoRA liegen zusätzlich vor und sind für den klassischen A2V-Pfad relevant; sie dürfen nicht als vermeintlich redundante Dateien entfernt werden.

Lokale Belege: [Setup](../scripts/setup-ltx-video-mlx), [Worker](../video_mlx_worker.py), [MLX-Provider](../video_providers_mlx.py), [LaunchAgent-Vorlage](../launchd/templates/de.nobby.mlx-video.plist.template), [Patchbeschreibung](../runtime-patches/ltx-2-mlx/ae3b7ea9583db775bd4a1dfb506fb789585021e7/README.md). Engine-Code unter `packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/` und `packages/ltx-core-mlx/src/ltx_core_mlx/`.

**2. Versionsvergleich und 0.17.0**

Der installierte Commit ist das Release **0.16.3 vom 9. Oktober 2026**. Aktuell als neuestes Release ausgewiesen: **0.17.0 vom 20. Oktober**, vollständiger Releasecommit **62b7651406f8ad4a0b7a3f36a93874a1015d59ca**. Das ist das offizielle Release des Community-Ports; die Modellreferenz von Lightricks und LTX-Desktop haben eigene Versionsreihen. [Releasehistorie](https://github.com/dgrauet/ltx-2-mlx/releases), [Releasecommit](https://github.com/dgrauet/ltx-2-mlx/commit/62b7651406f8ad4a0b7a3f36a93874a1015d59ca).

Für Nobby relevante Änderungen in 0.17.0:

| Änderung | Bedeutung für Nobby |
| --- | --- |
| Bildlatents vor Encoderfreigabe auswerten; A2V-Upsampling vor Freigabe materialisieren | Besonders relevant für I2V und klassisches Talking Photo: verhindert ungünstige Lazy-Graph-Lebensdauern |
| Unfused LoRAs beim Low-RAM-Streaming | Optional präzisere Adapteranwendung ohne erneute Quantisierung bei jedem Block-Bind |
| Stage-1-Ergebnis übernehmen und wiederverwenden | Neue Integrationsmöglichkeit für Preview→Finish und identische Stage-1-Wiederholungen |
| A2V auf DFR-Basis | Neue optionale Pipeline; kein automatischer Ersatz für vorhandene A2V-Modi |
| Audio-Prompt-Relay, Retake-Audio-Korrektur, IC-LoRA-Stage-2-Korrektur | Regressionstests erforderlich, bevor diese Funktionen integriert werden |

Breaking Change: Bei segmentiertem distilled/DFR-Prompt-Relay wird standardmäßig auch Audio-Cross-Attention beeinflusst. `--relay-audio-strength 0` stellt dort das frühere Verhalten wieder her. Der aktuelle Nobby-T2V-Worker übergibt keine Segmente. [0.17.0-Releasehinweise](https://github.com/dgrauet/ltx-2-mlx/releases/tag/v0.17.0).

FP16 kam bereits mit **0.16.0**, Sol sparse Attention mit **0.16.2**, distilled A2V mit **0.16.3**. Sie sind keine neuen 0.17.0-Beschleuniger. Ein pauschaler Performancegewinn des Upgrades für normalen T2V ist aus den Änderungen nicht ableitbar.

**3. Vorhandene Messdaten und ihre Aussagekraft**

Nutzerreferenz: **138,8 s**, 1280×704, 24 FPS, Seed 42, 8+3 Schritte, gemeldeter RAM-Peak 47,0 GB, Swap-Zuwachs 0.

Ein lokal gespeicherter vergleichbarer T2V-Job vom 21. Oktober (`~/.config/mlx-web/video-jobs/e3c24aca6ccffa84ea97f4c5.json`) liefert:

| Messwert | Wert |
| --- | --- |
| Jobzeit `finished_at - started_at` | **138,212 s** |
| Providerzeit | **137,552 s** |
| Workerzeit | **136,858 s** |
| Ressourcenübergabe | **0,596 s**, davon Chat-Stop 0,525 s |
| Ausgabe | **121 Frames**, 24 FPS, **5,041667 s**, 1280×704, Seed 42, Audio vorhanden |
| Worker-Reuse | `false`, trotz aktiviertem Persistent-Modus |
| System-RAM vor / Peak / nach | **46,817 / 46,952 / 38,475 GiB** |
| System-Swap vor / Peak / nach | **14,867 / 14,867 / 14,820 GiB** |

Der passende lokale Job ist eine zusätzliche historische Beobachtung, nicht zwingend exakt der genannte 138,8-s-Benchmark. Promptgleichheit mit der Nutzerreferenz ist unbekannt. Die Framezahl folgt dem Modellraster `8n+1`; deshalb ist „5 Sekunden“ hier tatsächlich 121/24 Sekunden. 1280×704 ist der bestehende rasterangepasste Landscape-Canvas, kein mathematisch exaktes 16:9.

**Die 47 GB sind kein isolierter LTX-Speicherpeak.** `video_service._memory_snapshot()` summiert systemweite aktive, inaktive, wired, komprimierte und speculative Seiten aus `vm_stat`. Die Messreihe enthält bereits den Zustand vor Ressourcenfreigabe. Die Zahl erlaubt keine Subtraktion als Modellbedarf und keine zuverlässige Aussage zur freien Reserve während Stage 2. Swap-Zuwachs 0 bedeutet hier ausdrücklich nicht „Swap unbenutzt“. Bereits ausgelagerte Seiten können weiter Page-ins und Verzögerungen verursachen. Das vorhandene 2-Sekunden-Sampling kann kurze Peaks verpassen.

**4. Pipelineanalyse**

| Phase | Istzustand und Befund | Konsequenz |
| --- | --- | --- |
| Admission / Übergabe | Zentrale Ressourcenkoordination, im passenden Job rund 0,6 s | Gegenüber 138 s geringe Priorität; Schutzmechanismen erhalten |
| Python-/Workerstart | Separates venv; bereits persistent möglich | Nur bei unmittelbar aufeinanderfolgenden Jobs spart der warme Prozess Start-/Importkosten |
| Text-Encoding | Packlokaler Gemma 4 plus Connector; Embeddings werden ausgewertet, anschließend Encoder freigegeben | Exakter Embedding-Cache kann Wiederholungen beschleunigen; Gemma nicht dauerhaft neben DiT/VAE halten |
| Modellladen | Low-RAM mmap-/Block-Streaming; Gewichte pro Block binden und wieder freigeben | Datei-Ladezeit und späteres Paging getrennt messen; schneller `mx.load` allein misst keine vollständige Gewichtsbereitstellung |
| Stage 1 | 8 ancestral Euler-Schritte bei halber Breite und Höhe | Rund 32 s im letzten passenden Logblock |
| Upsampling | Latenter 2×-Spatial-Upsampler, Ergebnis explizit materialisiert | Kein bloßes Pixel-Resize; für bestehende Qualität erhalten |
| Stage 2 | 3 Schritte bei voller Auflösung, eigener Rauschseed-Offset; Audio-Latents werden für Refinement eingefroren | Rund 71–72 s im letzten passenden Logblock; stärkster belegter Rechenanteil |
| Audio-Decoding | Audio-VAE, Vocoder, temporäres 48-kHz-WAV | Dauer nicht separat erfasst; Audiofunktionen erhalten |
| VAE-Decoding | Conv-Decoder, adaptives räumliches/zeitliches Tiling, FFmpeg-Streaming | Letzter passender Block: 40/8 Frames, 768/64 px, Schätzung 10,5 GiB, geloggter Metal-Peak 13,97 GiB |
| Encoding / Mux | FFmpeg `libx264`, CRF 18, yuv420p, AAC für Audio | Encoding und Mux sind zusammen im Streamingpfad; kein Beleg, dass dies der Hauptengpass ist |
| Cleanup | `gc.collect()`, `mx.clear_cache()`, gezielte Gewichtsfreigabe | Notwendige Speichergrenzen; pauschales Entfernen erhöht OOM-/Watchdogrisiko |

Quelle der ungefähren Stagezeiten: letzter 3520→14080-Token-Block in `~/.config/mlx-web/ltx-mlx-runtime.log`. Das Log enthält keine eindeutige Job-ID pro Stage. Die Zuordnung ist anhand Geometrie, Tokenzahl und Reihenfolge plausibel, aber nicht lückenlos bewiesen. Rund **103–104 s Denoising** würden etwa drei Viertel der 136,858 s Workerzeit erklären; die verbleibenden rund **33–34 s** enthalten Encoding, Laden, Upsampling, Decode, Mux und Cleanup. Ihre Einzelzeiten lassen sich nicht seriös nachträglich aufteilen.

Der geloggte Metal-Peak ist ein anderer Messbereich als systemweiter RAM und ohne belegte Resetgrenzen kein isolierter VAE-Phasenpeak. Beide Werte dürfen nicht addiert oder direkt gleichgesetzt werden.

**5. Warum die letzten Schritte länger dauern**

Für 121 Frames entstehen 16 latente Zeitebenen. Stage 1: `16 × 11 × 20 = 3520` Videotokens. Stage 2: `16 × 22 × 40 = 14080`. Audio bleibt bei 126 Tokens. Viermal mehr Videotokens bedeuten etwa vierfachen Aufwand in tokenlinearen Teilen und bis zu sechzehnfachen Aufwand der dichten Video-Self-Attention. Fused Attention begrenzt Zwischenspeicher, beseitigt diesen Rechenaufwand aber nicht.

Die Logs zeigen in Stage 1 etwa **3,8–4,1 s** pro früherem Schritt und insgesamt rund 32 s. Stage 2 benötigt **22,39 s**, anschließend etwa **25 s** und etwa **24 s**. Das ist primär ein **Stagewechsel**, kein stetig immer langsamer werdendes Denoising.

Zusätzlich bricht die ancestral Schleife beim terminalen Sigma aus dem `tqdm`-Iterator aus, bevor dessen Zähler den letzten Schritt übernimmt. Deshalb endet Stage 1 bei `7/8`, Stage 2 bei `2/3`. Der abschließende Stage-2-Wert von **35,86 s/it** entspricht ungefähr der gesamten Stagezeit geteilt durch **zwei gezählte Schritte**; er ist kein Nachweis für einen 35,86-s-Drittschritt. Der Worker-Hook läuft zudem vor der nachfolgenden Materialisierung: Fortschrittszeitpunkte sind keine verlässlichen GPU-Fertigstellungszeiten.

Die moderate reale Streuung innerhalb Stage 2 kann Paging, Speicherkompression, Wärme oder Systemkonkurrenz enthalten. Dafür fehlen synchronisierte Thermik-/Page-in-Daten dieses Laufs; keine dieser Ursachen ist als zusätzliche Hauptursache bewiesen.

**6. Konkrete Optimierungsvorschläge**

| Priorität / Maßnahme | Erwarteter Vorteil | Risiko / Freigabebedingung |
| --- | --- | --- |
| 1: Phasen- und korrekte Fortschrittsmessung | Engpass und tatsächliche Schrittzeiten werden überprüfbar; kein direkter Rendergewinn | GPU-Timing verändert Synchronisation; instrumentierte und normale Läufe getrennt ausweisen |
| 2: 0.17.0 in separater Runtime prüfen | Robustere I2V-/A2V-Lebensdauer, bessere optionale LoRA-Anwendung, Stage-1-Reuse | API-/Audio-Regressionen; kein versprochener pauschaler T2V-Speedup |
| 3: FP16 und BF16 Compute einzeln testen | Kleinere DiT-interne Aktivierungen, potenziell schnellere Attention/FFN | Numerik ändert sich; Bild-, Audio- und Lip-Sync-Abnahme zwingend |
| 4: Begrenzter Cache nur außerhalb VAE-Decode | Weniger Allokationsaufwand ohne Änderung der Rechenmethode | Speicherpeak kann wachsen; unter Low-RAM derzeit absichtlich Cache 0 |
| 5: Exakter Prompt-Embedding-Cache auf CPU/Datei | Spart wiederholtes Gemma-Encoding und ggf. Encoderladen | Nutzen nur bei Cachetreffern; vollständiger Cachekey, begrenzte Größe und Invalidierung nötig |
| 6: Stage-1-Reuse in 0.17.0 | Spart die 8 Stage-1-Schritte bei identischer Stage-1-Aufgabe | Zusätzliche Integration; Änderungen an Eingaben müssen Cache verwerfen |
| 7: Selektiver Gewichts-/Block-Reuse | Weniger wiederholtes Laden, Bind- und ggf. LoRA-Fusionsarbeit | Hohe Speicher-/Lebensdauerkomplexität; erst nach gemessener Reserve |
| 8: Sol sparse Attention | Kann Stage 2 beschleunigen | Approximation verändert Bildinhalt; nur Kandidat nach Qualitätsnachweis |

**Compute-Dtype:** `LTX2_COMPUTE_DTYPE=float16` lässt Q4-Gewichte quantisiert. Attention/FFN einschließlich relevanter Floatparameter rechnen gezielt in FP16; Residualstream und AdaLN bleiben FP32. Ein Finite-Check kann bei Überlauf zurückfallen und kostet selbst eine Synchronisation pro Forward. Upstream berichtet bei **M1 Max/Q8**, anderem Clip, 701→563 s gesamt und 141→107 s pro Stage-2-Schritt. Das ist ein Kompatibilitäts- und Potenzialnachweis, keine Prognose für M5 Max/Q4. BF16 sollte auf dem Zielgerät als eigene Variante verglichen werden. [FP16-Implementierung und Messungen](https://github.com/dgrauet/ltx-2-mlx/pull/171).

**Cache:** Die Pipeline setzt unter Low-RAM beim Konstruktor `mx.set_cache_limit(0)`. Der VAE-Decoder deaktiviert den Allocator-Cache zusätzlich während des Decodings und stellt anschließend den vorigen Wert wieder her. Das schützt vor sehr großen zurückgehaltenen Aktivierungspuffern. `LTX2_VAE_DECODE_KEEP_CACHE=1` ist deshalb kein sicherer globaler Performance-Schalter. Empfohlene spätere Versuchswerte: 0, 256 MiB, 512 MiB, höchstens zunächst 1 GiB für DiT/Text; VAE-Cache weiter 0, Bereinigung an Phasengrenzen erhalten. Cachelimit begrenzt freie wiederverwendbare Allocator-Puffer, nicht die Summe aktiver Modelle. [MLX-API](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_cache_limit.html).

**Synchronisation:** Im aktuellen Streamingpfad wird nach jedem Transformerblock ausgewertet, damit die bisherigen Gewichte freigegeben werden können. Der gemeinsame Block ist schon mit `mx.compile` kompiliert. `LTX2_DIT_EVAL_EVERY` betrifft dagegen den residenten Pfad (Standard 8). Diesen Wert auf 0 zu setzen beseitigt beim Streaming keine Blockbarrieren. Streaming-Evals und Watchdog-Schutz nicht pauschal entfernen. Kandidaten für einen späteren Prototyp sind begrenzte Gruppen mehrerer residenter Blöcke und gezielte doppelte Barrieren; kompatible Bausteine sind vorhanden, ein qualitäts- und speichervalidierter Nobby-Gruppenstreamer ist es noch nicht.

**Persistent Worker:** Bereits vorhanden. Größeres Idle-Timeout hilft nur bei tatsächlich verpasstem Prozess-Reuse, hält allein aber keine Modellgewichte warm. `low_memory=False` würde mehrere große Komponenten gleichzeitig halten und wäre eine andere Speicherstrategie. Sie darf nicht als kleiner Toggle behandelt werden. Erst kleine CPU-Caches, dann gemessener selektiver Reuse, danach allenfalls ein isolierter Test ohne Blockstreaming. Adapterprofile benötigen bei jeder Wiederverwendung eine vollständige Trennung; `_pending_loras=[]` allein entfernt keine bereits fusionierten Gewichte.

**7. Moderne, kompatible Techniken und Grenzen**

Sol ist ein tatsächlich implementierter **MLX-Metal-Port für LTX 2.5 distilled Stage 2**, kein CUDA-Paket. `LTX2_SOL_TAU=1.0,1.25,1.5` steuert die drei Schritte. Video-Self-Attention ab Block 1 wird approximiert; Block 0 bleibt dicht. Der lokale Mindestwert ist 4096 Tokens, den Stage 2 hier überschreitet. Bei Streaming schaltet sparse Attention auf den eager Blockpfad; dadurch kann ein Teil des Kernelgewinns verloren gehen. Upstream misst auf M1 Max/Q8/FP16 **21–36 % kürzere Stage-2-Schrittzeiten**, **12–22 % kürzere Gesamtläufe** und 30–32 dB PSNR zur dichten Ausgabe bei anderen Geometrien. Das ist sichtbare/numerische Abweichung, kein garantierter Qualitätserhalt. [Implementierung, Fallback und Benchmarks](https://github.com/dgrauet/ltx-2-mlx/pull/196).

Stage-1-Resume in 0.17.0 ist besonders interessant, weil es Rechenarbeit **ohne approximiertes Denoising** sparen kann. Der Upstream-Test bestätigt identische Video-/Audiolatents beim Finish aus demselben Stage-1-Ergebnis. Es spart nur Stage-1-Denoising; Promptencoding, Konditionierung und Modellaufbau werden weiter ausgeführt. Cachekey muss zusätzlich zu Shapes Modell-/Adapterrevision, Prompt, Bildinhalt samt Preprocessing, Seed, FPS, Framezahl, Geometrie, Schedule, Dtype, Guidance und Pipelineversion enthalten. Aktuell nur distilled T2V/I2V, kein entsprechender Resume-Vertrag für A2V/DFR/Extend. [Stage-1-API und Validierung](https://github.com/dgrauet/ltx-2-mlx/pull/217).

Unfused Streaming-LoRAs in 0.17.0 vermeiden erneute Quantisierung des Adapterupdates. Das kann Qualität verbessern; Geschwindigkeit hängt unter anderem vom Rang ab. Der lokale Log nennt auch einen rank-768-Adapter: Messergebnisse einer kleinen rank-32-LoRA sind darauf nicht übertragbar. [Streaming-LoRA-Verfahren](https://github.com/dgrauet/ltx-2-mlx/pull/213).

TeaCache wird vom installierten LTX-2.5-**Distilled**-Pfad ausdrücklich abgelehnt. Es ist kein verfügbarer schneller Schalter für den hier untersuchten 8+3-Pfad. TeaCache im klassischen CFG-/A2V-Pfad benötigt eigene Kalibrierung und Qualitätsvalidierung. DFR und Diffusion-VAE sind vorhandene alternative Verfahren, ändern aber Generations-/Decodeverhalten und können zusätzliche Modelle benötigen; für den unveränderten Vergleich zunächst ausklammern.

CUDA-only FlashAttention-, SageAttention-, TensorRT- oder xFormers-Rezepte sind kein belegter Ersatz für den nativen MLX-Pfad. Dense fused SDPA, Blockkompilierung und adaptives VAE-Tiling sind schon integriert. Weitere Quantisierung oder kürzere Schedules sind keine qualitätsneutralen Optimierungen und hier nicht empfohlen.

MLX selbst ist inzwischen bei **0.32.4**, lokal 0.32.2. 0.32.3/0.32.4 enthalten Kernel- und Korrektheitsänderungen. Der hervorgehobene 0.32.4-SDPA-Speicherfix betrifft ausdrücklich pre-M5 und Head-Dimension 512; daraus folgt kein passender M5/LTX-Gewinn. MLX-Upgrade separat testen, weil Sol installierte Steel-Header nutzt. [MLX 0.32.3](https://github.com/ml-explore/mlx/releases/tag/v0.32.3), [MLX 0.32.4](https://github.com/ml-explore/mlx/releases/tag/v0.32.4).

**8. Native MLX Q4 gegenüber Fast / MPS**

| Eigenschaft | LTX 2.5 MLX Q4 | LTX 2.5 Fast / Headless |
| --- | --- | --- |
| Implementierung | Community-Port `dgrauet/ltx-2-mlx` | Lightricks LTX-Desktop, lokaler offizieller MPS-Pfad |
| Lokaler Commit | ae3b7ea, 0.16.3 | **68cd86c15e5fd25f56229ea63c0dbcb0338f7812**, Setup-Pin **v1.2.7**, sauberer Checkout |
| Python / Framework | 3.11.15, MLX 0.32.2 | **3.13.12**, **PyTorch 2.11.0**, NumPy 2.4.2 |
| Gewichte / Rechnen | Q4-Linears, gemischte Komponenten; Standard relevante DiT-Module FP32 | BF16-Checkpoints und BF16-Pipeline |
| Streaming | MLX mmap, gemeinsamer kompilierter Block, Materialisierung je Block | Bei MPS-Streaming **OffloadMode.DISK**, mmap über kleinen Puffer; CPU-Offload würde Unified Memory nicht entlasten |
| Provider / Port | `video_providers_mlx.py`, 18061 | `video_providers.py`, `ltx2_server.py`, 18060 |
| Nobby-Funktionen | T2V, I2V, generiertes Audio; Talking Photo über separaten MLX-Runner | T2V, I2V, Audio; derzeit kein Ersatz für Nobbys MLX-Talking-Photo-Runner |
| Optimierungen | FP16/BF16 Compute und Sol bereits implementiert | Eigene MPS-Patches, Offload-/Runtime-Policy; MLX-Variablen wirken hier nicht |
| Qualitätsvergleich | Quantisierung verändert Numerik | Höhere Gewichtspräzision ist kein pauschaler Beweis besserer Videoqualität |
| Geschwindigkeitsurteil | Passender historischer Lauf rund 138 s | Kein passender gemessener A/B-Lauf in dieser Untersuchung |

„Fast“ ist ein Produkt-/Pipelinename, kein Nachweis, dass MPS auf diesem Gerät schneller als MLX Q4 ist. Gleicher Seed erzeugt zwischen Frameworks wegen unterschiedlicher Zufallszahlen/Numerik keine identische Szene. MPS-BF16-DiT allein umfasst größenordnungsmäßig 44 GB dezimal für 22 Milliarden BF16-Parameter; vollständige Residenz plus Encoder, Aktivierungen und Decoder passt nicht verlässlich in 48 GB.

Lokale Belege: [MPS-Setup](../scripts/setup-ltx-video), [MPS-Provider](../video_providers.py), [Registry](../video_registry.py); im Desktop-Checkout `backend/services/ltx_pipeline_common.py`, `services/fast_video_pipeline/` und `services/patches/`.

**9. Abhängigkeiten und Regressionen in MLX-Nobby**

| Bereich | Abhängigkeit / zu erhaltender Vertrag |
| --- | --- |
| Service und API | `video_service_dispatch.py`, `video_service.py`, Providerdispatcher, Jobpersistenz, Cancel, Fortschritt, Ausgabeprobe und Medienmetadaten |
| T2V | `DistilledPipeline.generate_and_save`, 8+3, feste Geometrie/Framezahl/FPS/Seed, generiertes Audio |
| I2V | Verwaltete Uploads, FFmpeg-First-Frame-Preprocessing, contain/cover, Square/Portrait/Landscape, Encoder-Lebensdauer |
| Audio | Gemeinsamer AV-Transformer, Audio-VAE/Vocoder, 48-kHz-Zwischen-WAV, AAC-Ausgabe; Stage-2-Freeze erhalten |
| Talking Photo direkt | `agent/talking_photo_ltx.py` startet pro Auftrag einen eigenen Prozess über dasselbe Engine-venv und denselben Q4-Pack |
| Talking Photo classic | `A2VidPipelineTwoStage`, **15+3**, CFG 3/STG 1 und Negative Prompt; braucht auch Dev-/LoRA-Komponenten |
| Talking Photo distilled | Explizite Option, `A2VidDistilledPipeline`, **8+3**; klassische CFG-/STG-/Negative-Prompt-Parameter werden nicht übergeben |
| Talking Photo Quality | LTX-A2V plus optionaler MuseTalk-Mac-Lipsync, eigenes Lifecycle-/Cancel-/Audio-Handling |
| Talking Photo lang | Segmentierung, Übergänge, Audio-Padding/Lead-in, Sprecherauswahl und Identität erhalten |
| Ressourcen | `runtime_coordinator.video_runtime`, Memory-Admission und Lease, Image-/Speech-/MuseTalk-Freigabe und Chat-Wiederherstellung |
| Adapter | Standard/uncensored, Profilwechsel und Fehlerpfade dürfen keine Adaptergewichte zum Folgejob übertragen |
| Installation | Commit-Pin, `uv.lock`, editable Pfade und commitgebundene Patchserie gemeinsam behandeln |

Reguläre Videojobs setzen `exclusive_models=True`. Der Talking-Photo-Renderer verwendet denselben Ressourcenkoordinator **ohne** dieses Argument. Diese unterschiedliche Admission-Politik muss bei Cache-/Resident-Änderungen ausdrücklich mitgetestet werden; gleicher Enginepfad bedeutet nicht gleiches Speicherprofil.

Weitere Integrationsbefunde: `video_registry.model_path()` weist jeden MLX-Provider auf den Q4-Pfad, auch wenn das Setup Q8 parallel installieren kann. Ein Q8-Vergleich wäre deshalb eine eigene Erweiterung und kein einfacher Modellwechsel. Die Verfügbarkeitsprüfung kontrolliert nur Marker/Config, nicht vollständige Paket-/Modellkompatibilität. Worker und Provider verwenden private Hooks/Felder (`_stepwise_hook`, `_pending_loras`), die beim Upgrade besonders zu prüfen sind. Tests pinnen außerdem noch 0.16.3/ae3b7ea ausdrücklich.

Paketabhängigkeiten der Engine umfassen MLX, mlx-lm, mlx-arsenal, Safetensors, Hugging Face Hub, NumPy, Pillow und tqdm; über mlx-lm/Encoder auch Transformers/Tokenizer. FFmpeg/ffprobe sind externe ausführbare Abhängigkeiten. In Nobby kommen HTTP, Runtime-Koordination, Speech/TTS und optional MuseTalk hinzu. Kein gemeinsames Upgrade der Nobby-venvs mit dem Engine-venv durchführen.

Relevante vorhandene Tests: `test_video_mlx_provider.py`, `test_video_mlx_warm_runtime.py`, `test_video_runtime.py`, `test_video_progress_counts.py`, `test_ltx_distilled_rollout.py`, `test_video_uncensored_profile.py`, `test_video_benchmark_telemetry.py`, `test_ltx_benchmark_telemetry.py`, `test_talking_photo_ltx.py`, `test_talking_photo_quality_audio.py`, `test_talking_photo_lifecycle.py`, `test_talking_photo_longform.py`, `test_talking_photo_speaker_ltx.py` sowie Talking-Photo-E2E-Tests. Diese Aufzählung ist eine Prüfliste; die Tests wurden in dieser lesenden Untersuchung nicht ausgeführt.

**10. Sicherer Upgrade- und Benchmarkplan – noch nicht ausgeführt**

1. **Reproduzierbare Baseline vorbereiten.** Nutzerreferenzprompt und Medien unverändert festhalten; 121 Frames, 1280×704, 24 FPS, Seed 42, 8+3, Audio, Profil, Decoder und Exportparameter dokumentieren. Engine-/Nobby-SHA, Paketversionen, Modell-/Adapterrevisionen und effektive Optionen erfassen. Große Gewichte nicht unnötig komplett hashen; zunächst lokale Revisionen und Config-/Manifesthashes verwenden.
2. **Messung in einer separaten Arbeitskopie ergänzen.** JSON-Events für Workerstart, Textencoderladen/-rechnen, DiT-Bereitstellung, I2V-Encoding, Stage 1, Upsampling, Stage 2, Audiodecode, VAE/Encoderstreaming, FFmpeg-Abschluss und Cleanup. Job-ID, Stage und tatsächliche GPU-Fertigstellung markieren. Überlappende Decode-/FFmpeg-Zeiten nicht doppelt summieren. CPU-Walltime und synchronisierte GPU-Grenzen getrennt erfassen.
3. **0.17.0 separat installieren, erst nach Freigabe.** Eigenes Runtimeverzeichnis und eigenes venv, vollständiger Release-SHA statt `main`. Bestehenden Modellpack nur referenzieren; kein Modell-Download, kein produktives `setup-ltx-video-mlx` ausführen. Dessen Checkout/Sync/Download-Verhalten ist für einen isolierten Test ungeeignet. Neue commitgebundene Patchbeschreibung anlegen; alte Patchserien nicht übernehmen.
4. **Abhängigkeiten differenzieren.** Neuen Lockfilestand prüfen; prüfen, ob 0.17.0 mit unverändertem MLX 0.32.2 läuft. Falls neue Pflichtabhängigkeiten nötig sind, diese als Teil des Versionsvergleichs ausweisen. MLX 0.32.4 anschließend in einer separaten Variante testen, nicht gleichzeitig als unbemerkte Variable ändern.
5. **Tests vor Generierung.** Imports/API-Signaturen und private Worker-Hooks in der Testumgebung prüfen, vorhandene CPU-/Mocktests durchführen. Keine Tests gegen produktive Health-/Generate-/Reset-Endpunkte, keine testspezifischen Imports, die produktive Registry migrieren oder Worker starten.
6. **Benchmarks erst nach ausdrücklicher Freigabe und in geeignetem Zeitfenster.** Getrennte Ports, Ausgabeverzeichnis und Konfigurationspfade; nur eine Generierung gleichzeitig. Auch ein separater Worker konkurriert um denselben Unified Memory. Solange keine laufenden Dienste gestoppt werden dürfen, vorhandene Prozesse nicht durch Benchmarks oder den Koordinator verdrängen. Wenn ausreichende Reserve fehlt, den Generierungstest verschieben; Ergebnisse unter verbleibender Konkurrenz entsprechend kennzeichnen.
7. **Ein Faktor je Variante**, siehe Matrix. Zuerst Shortlist mit einem Lauf; nur bestandene Kandidaten mit einem Prozessstart-Lauf und drei warmen Folgejobs prüfen. Kalte Runtime bedeutet frischer Prozess, nicht geleerter macOS-Dateicache. Kein `purge`, kein Swapreset und kein Cacheflush des Systems.
8. **Abnahme und Rollback.** Bildqualität, Identität, Bewegung, Details, Flimmern, Texttreue, AV-Synchronität und Talking-Photo-Mundbewegung anhand unveränderter Testmedien vergleichen. Dann erst einen späteren produktiven Wechsel planen. Bei Regression weiterhin alten Runtimepfad und alten Pin verwenden; keine Modell-/Registrymigration nötig. Aktivierung oder Neustart nur in einem separat freigegebenen Wartungsschritt.

| Variante | Änderung gegenüber Kontrolle | Zweck |
| --- | --- | --- |
| A | 0.16.3, MLX 0.32.2, bestehende Optionen | Baseline reproduzieren |
| B | Nur Engine 0.17.0 samt notwendigen Abhängigkeiten | Upgradeeffekt und Funktionsparität |
| C1 / C2 | Auf bestandener Kontrolle nur FP16 / nur BF16 Compute | Numerik-/Geschwindigkeitsvergleich |
| D | Nur begrenzter DiT-/Textcache, VAE-Cache weiter 0 | Allokationskosten gegen RAM abwägen |
| E | Nur exakter Embedding-Cache, Treffer und Miss getrennt | Wiederholungsnutzen |
| F | Nur Stage-1-Resume aus identischer Eingabe | Zeitersparnis und Latentparität |
| G | Nur Sol auf bestandener Compute-Konfiguration | Optionaler Approximationsvergleich |
| H | Nur unfused LoRA bei festem Adapter/Strength | Adapterqualität und Rangabhängigkeit |
| I | Nur MLX 0.32.4 | Frameworkeffekt, Sol-Headerkompatibilität |
| J | MPS Fast mit gleicher Zielgeometrie/Audio/Schedule | Frameworkvergleich, keine Pixelparität erwartet |

Pflichtfälle: T2V mit Audio; I2V in contain und cover sowie Portrait/Square; Talking Photo classic und distilled, direkt und mit bestehendem Quality-/Lipsyncpfad; Longform/Segmentgrenzen; Profil Standard→Adapter→Standard; Abbruch, Fehler und anschließender erfolgreicher Job; drei Folgejobs mit Rückkehr zum Idle-Speicher. MPS-T2V/I2V als Regression separat erhalten.

Pro Lauf: End-to-End-, Provider-, Worker- und Phasenzeiten; Zeit je abgeschlossenem Schritt; MLX active/cache/peak mit dokumentierten Resetgrenzen; Prozess-RSS/physischer Footprint; systemweiter RAM und Compressor; Swap vor/nach, Page-ins/Page-outs; Thermik/Drosselung; effektive Dtypes und Sparse-Kernel-Aktivierung; Frames/FPS/Audiospuren; vollständige Parameter und Qualitätsabnahme. Aktiver Metal-Speicher und Prozess-/Systemwerte separat berichten. Thermik-Messung darf keine neuen störenden Hintergrundlasten oder dauerhafte Dienste erzeugen.

Bei Änderungen ohne beabsichtigte Numerikänderung zuerst Video-/Audiolatents bzw. dekodierte Frames und PCM vergleichen; Containerhash allein ist zu streng oder irreführend. Bei FP16, Sparse oder unfused LoRA sind PSNR/SSIM und Sicht-/Hörvergleich ergänzend nötig, aber kein einzelner Score beweist gleiche Qualität. Bei erkennbarer Verschlechterung Kandidat verwerfen. Erfolgsziel: geringere Medianzeit außerhalb der beobachteten Laufstreuung, keine zusätzliche Speicher-/Swapbelastung, kein OOM/Watchdog und alle vorhandenen Funktionen erhalten. Ein fixer sicherer RAM-Grenzwert muss aus Prozess-/Metal- und Pressuremessungen abgeleitet werden; der bisherige globale 47-GB-Wert genügt dafür nicht.

Das vorhandene [Benchmarkskript](../scripts/benchmark-ltx-video.py) ist eine gute Basis für Job-/Systemtelemetrie, verwendet aber als ältere Referenz **141,5 s vom 30. September**. Für diese Analyse ist **138,8 s** die Nutzerreferenz. `--cold-warm-cold` ruft ausdrücklich den Worker-Reset-Endpunkt auf und ist unter der Vorgabe „keine Dienste stoppen“ ungeeignet. Auch normale API-Generierungen können über den Ressourcenkoordinator Chat/Speech/Image entladen. Das Skript wurde nicht ausgeführt; künftige Freigaben müssen diesen tatsächlichen Ablauf berücksichtigen.

**11. Empfohlene Reihenfolge und erwartbarer Nutzen**

Zuerst Messqualität und Speicherzuordnung herstellen. Danach 0.17.0 getrennt für T2V/I2V/A2V validieren. Anschließend FP16 und BF16 als aussichtsreiche, bereits verfügbare Rechenoptionen prüfen. Begrenztes phasenabhängiges Allocator-Caching und exaktes Embedding-Caching sind die nächsten Kandidaten ohne beabsichtigte Qualitätsänderung. Stage-1-Reuse lohnt sich für identische Preview-/Finish-Aufgaben. Sparse Attention und unfused LoRAs folgen mit eigener Qualitätsabnahme; residenter DiT oder mehrblockiges Streaming erst bei nachgewiesener Reserve.

Eine belastbare M5-Max-Zielzeit ist ohne genehmigte A/B-Messung nicht anzugeben. Als rein rechnerische Sensitivität: 20 % weniger Stage-2-Zeit bei ungefähr 71 s würden rund **14 s** sparen, 20 % weniger gesamtes Denoising bei ungefähr 103 s rund **21 s**. Das sind weder Messresultate noch erwartete Garantien; Gewinne verschiedener Optionen sind nicht einfach addierbar. Die rund 0,6 s Ressourcenübergabe und reiner Workerstart sind gegenüber dem Denoising deutlich kleinere Hebel.
