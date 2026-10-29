# Krea Noct: Kompatibilität und Vergleich mit Juggernaut

Stand **2026-10-29**, Branch `feat/test-krea-noct-20261029`, Basis
`bf6db09e7dcdf3798498fcffbcf30efa41d5377c`.

**Ergebnis: Die geprüfte Noct-V4-Datei ist nicht direkt kompatibel.** Es gibt
keinen neuen Provider, keinen Registry-Eintrag und keinen UI-Schalter für ein
Modell ohne korrekten Ladepfad. Juggernaut XL Ragnarok, Osaurus Qwen Image 2.1,
Qwen Image Edit, Benutzerregistry, Qualitätsprofile und Laufzeiten bleiben
unverändert. Der Vergleich ist vorbereitet, noch nicht gerendert.

## Was geprüft wurde

Der [Autor bietet auf Hugging Face](https://huggingface.co/Noctaluna/Krea2-Noct-Uncensored)
Noct V3/V4 als einzelne ComfyUI-INT8-ConvRot-Safetensors an. Geprüft wurde exakt
`KreaNoct_V4_int8_convrot.safetensors`, Revision
`d93fbcb45e6f6995f2ecdd4edfdb1ef12db6e6e4`: 13.492.706.520 Bytes / 12,57 GiB.
Der Header nennt als Quantisierungsquelle `KreaNoct_V4a_bf16.safetensors`.
Die Modellkarte verweist für BF16/FP8/INT4 auf Civitai. Diese weiteren Dateien
wurden nicht heruntergeladen oder als kompatibel bestätigt; der öffentliche
Civitai-API-Aufruf war hier nicht erreichbar. Daraus folgt keine generelle
Unmöglichkeit eines späteren BF16-Pfads.

Architektur: Krea-2-Turbo, Single-Stream-Diffusion-Transformer mit ungefähr
12,8 Milliarden Parametern, Qwen3-VL-4B-Textencoder und Qwen-Image-VAE.
Das ist eine andere Architektur als SDXL und als FLUX.1 Krea.
[Offizielle Krea-Modellkarte](https://huggingface.co/krea/Krea-2-Turbo).

Der Formatcheck hat nur öffentliche Metadaten und 88.360 Bytes Prefix/JSON-Header
mittels begrenzter HTTP-206-Range-Anfragen gelesen. Ergebnis: 878 Tensoren,
darunter 224 I8-Gewichte und die zugehörigen Skalen-/Quantisierungsmarker.
Die veröffentlichte Voll-Datei-SHA256 ist dokumentiert, mangels Voll-Download
aber nicht unabhängig nachgerechnet. [Exakte Evidenz und Runtime-Hashes](krea-noct-compatibility-2026-10-29.json).

## Technischer Blocker und Speicher

| Vorhandener Pfad | Befund |
| --- | --- |
| MFLUX 0.22.0 / MLX 0.32.3 | `mflux-generate-krea2` und Krea-2-Architektur vorhanden. Der installierte Loader kennt native Float-/Diffusers-Gewichte und MFLUX-gepackte Quantisierung, keine ComfyUI-INT8-ConvRot-Dequantisierung. |
| Diffusers 0.40.0 / PyTorch 2.14.0 | `Krea2Pipeline` vorhanden. Der aktuelle SDXL-Worker instanziiert ausdrücklich `StableDiffusionXLPipeline`; er kann nicht als Krea-2-Provider benutzt werden. In dieser installierten Krea-2-Klasse fehlt außerdem der neuere `FromOriginalModelMixin`-Single-File-Pfad. |
| MLX-Nobby | Kein Krea-2-Familien-/Provider-Vertrag. Der ältere entfernte Krea-Turbo-Eintrag wird nicht wieder aktiviert. |

ComfyUI-INT8 benutzt Skalen und eine passende Rotation der Aktivierungen;
`--quantize 8`, Umbenennen zu `turbo.safetensors` oder einfaches I8→BF16-Casten
reproduziert das nicht. Der aktuelle MFLUX-WeightLoader mappt bzw. castet die
Gewichte ohne diese Operationen.
[ComfyUI-Formatspezifikation](https://github.com/Comfy-Org/comfy-quants/blob/main/docs/formats/int8_tensorwise.md).
Auch der vom Autor empfohlene FP8-Textencoder ist kein automatisch austauschbarer
MFLUX-Textencoder; dessen Krea-Definition überspringt Textencoder-Quantisierung.

Dieser Mac hat **48 GiB Unified Memory**. Die 12,57-GiB-Datei umfasst nur den
Transformer. Für einen BF16-Vergleich wären ungefähr 26,3 GB Transformer plus
8,9 GB Textencoder und VAE, also rund **35–36 GB Gewichte**, einzuplanen;
Aktivierungen, VAE-Dekodierung, Ladezwischenstände und Systemreserve kommen dazu.
Dies ist eine Größenabschätzung, kein gemessener Metal-Peak oder Fit-Nachweis.
Die 12-GB-Grafikkartenangabe der Modellkarte ist keine RAM-Garantie für diesen Mac.

Für eine spätere Integration braucht es einen identifizierten, verifizierten
Noct-Float-/MLX-Export mit vollständigen Encoder-, Tokenizer- und VAE-Komponenten
oder eine separat geprüfte ConvRot-Laufzeit. Anschließend müssen Provider,
Gewichtsformatprüfung, Qualitäts-/Samplerparameter, Auflösungsgrenzen und die
bestehenden Speicher-/Abbruch-/Lifecycle-Verträge angebunden und real geprüft
werden. Aktuell bleibt der Kandidat in der [Testmatrix](image-model-test-matrix.md)
`planned`, nicht `configured` oder `tested`.

## Aktivierung und UI

**Noct ist derzeit nicht aktivierbar und erscheint weder in Neugenerierung noch
in Edit.** Die Modellkarte beschreibt Text-to-Image. MFLUX unterstützt bei
Krea-2 grundsätzlich Stärke-basiertes img2img; daraus folgt keine geprüfte
Noct-Instruktionsbearbeitung. Eine spätere erste Freigabe sollte nur
Neugenerierung anbieten.
[MFLUX-Krea-2-Dokumentation](https://github.com/mflux-community/mflux/blob/main/src/mflux/models/krea2/README.md).

Für die hier gelieferten Prüf-/Vergleichsdateien sind keine Modellinstallation,
Paketupdates, Dienstneustarts oder Web-Rebuilds erforderlich:

```sh
cd ~/mlx-web
git fetch origin feat/test-krea-noct-20261029
git switch feat/test-krea-noct-20261029
python3 scripts/prepare-krea-noct-comparison.py \
  --output-dir ~/mlx-nobby-tests/krea-noct-comparison-20261029
```

Das Zielverzeichnis muss neu sein. Enthalten sind `plan.json`, `scorecard.csv`
und 15 Juggernaut-Anfragen unter `requests/`. Der Befehl startet keine Jobs,
lädt keine Gewichte und erzeugt ausdrücklich keine ausführbare Noct-Anfrage.
Mit `--seeds 42 43 44` lassen sich beide Vergleichsseiten gemeinsam umstellen.

## Konkrete Vergleichsabnahme

1. `plan.json` prüfen: fünf Fälle — Porträt, Ganzkörper, Mischlicht/Haut,
   Sofa mit Fensterlicht und Bett mit Fensterlicht — jeweils drei Seeds
   27102026/27102027/27102028. Prompt und Auflösung sind pro Paar identisch.
   Alle Motive verwenden fiktive erwachsene Personen. Der optionale explizite
   Fall gehört nicht zum Standardvergleich.
2. Einstellungen beibehalten: **832×1216**, keine Hochskalierung, keine LoRAs,
   keine Prompt-Umschreibung, leeres Negativprompt. Juggernaut: 35 Steps,
   CFG 4, DPM++ 2M SDE Karras. Noct-Referenz laut Autor: 8 Steps, CFG 1,
   Euler/Simple. Noct nennt nativ 1024×1536; für den Vergleich wird auf das
   bestehende Juggernaut-/Service-Limit verkleinert. Die bisherigen Modellprofile
   werden nicht geändert. Ein identischer Seed bedeutet bei verschiedenen
   Architekturen nicht identisches latentes Rauschen.
3. Die Juggernaut-Baseline lässt sich **manuell** über den bestehenden nativen
   Image-Service erzeugen. Vorher dessen Bereitschaft und freie Queue prüfen;
   jeden Job einzeln bis zum Terminalstatus beobachten:

   ```sh
   curl --fail-with-body http://127.0.0.1:8030/health
   curl --fail-with-body -H 'Content-Type: application/json' \
     --data-binary @"$HOME/mlx-nobby-tests/krea-noct-comparison-20261029/requests/001-juggernaut-seed-27102026.json" \
     http://127.0.0.1:8030/jobs
   curl --fail-with-body http://127.0.0.1:8030/jobs/JOB_ID
   # Falls nötig: POST /jobs/JOB_ID/cancel
   ```

   Die Job-ID durch die Antwort-ID ersetzen. Ergebnisse einschließlich
   tatsächlicher Parameter und Speicher-/Zeitbelege separat sichern. Diese
   Befehle wurden hier nicht gegen produktive Dienste ausgeführt.
4. Noct-Zeilen bleiben `blocked` und unbewertet, bis der technische Blocker
   behoben und ein echter Smoke-Render erfolgreich ist. Dann den **konkreten**
   Noct-Checkpoint und die tatsächlich verwendete Laufzeit festhalten. Gleiche
   Prompts aus `plan.json` übernehmen; keine Turbo-Basisgewichte als Noct ausgeben.
5. Pro Bild Fotorealismus, Haut, Gesicht, Anatomie, Prompt-Treue und Konsistenz
   von 1 bis 5 bewerten, sichtbare Fehler mit Beispielen notieren. Konsistenz
   zusätzlich über die drei Seeds beurteilen; Modell-/Dateinamen beim visuellen
   Vergleich möglichst verdecken. Einzelergebnisse und Median berichten.
6. Ladezeit, Generierungszeit und gesamte Jobzeit getrennt erfassen. Einen kalten
   Erstlauf und zwei Wiederholungen kennzeichnen; nur tatsächlich wiederverwendete
   Laufzeiten als warm einstufen. Prozess-RSS, MLX-/MPS-Peak, Swap-Änderung und
   Messquelle getrennt eintragen — RSS ist kein GPU-Peak. Fehlende Werte bleiben
   leer. Für die native Jobzeit `finished_at - started_at` verwenden; der
   Speicher des curl-Prozesses misst nicht den Bildworker. Ausgabeformat und
   Kompression ebenfalls festhalten. Bei Speicherfehlern nicht automatisch wiederholen.
7. Nach **jedem** echten Modelltest auch Fehlversuche, Parameter, tatsächliches
   Testdatum und Belege in `docs/image-model-test-matrix.md` nachtragen. Medien
   außerhalb Git behalten. Erst ein erfolgreicher echter Render erlaubt `tested`.

## Ausgeführte Prüfungen

- **224 Backendtests und 52 Untertests bestanden**: Vergleichsgenerator,
  Registrierung/API, MFLUX-Verträge, Bildruntime, Qualitätsprofile,
  Juggernaut-img2img/Ragnarok, Osaurus und MLX-Gen-Edit. Zehn betroffene
  Testdateien, keine unnötige Vollsuite.
- **12 Frontendtests bestanden**, sieben betroffene Testdateien: Generate-/Edit-
  Auswahl, bestehende Modelle, veraltete Auswahl, Parameterübergabe und Dialog.
- Bundle-CLI auf dem Mac ausgeführt: 30 Vergleichseinträge, 15 gültige
  Juggernaut-Requestdateien, Noct blockiert, Bewertungsfelder leer.
- Anfangs scheiterten bestehende isolierte Picker-Tests am nicht mitgeladenen
  `HIDDEN_IMAGE_MODEL_ID` aus dem vorherigen Picker-Fix; ein weiterer Test
  erwartete dessen alte Asset-Version. Nur Test-Fixtures/Erwartung korrigiert,
  kein produktiver UI-Code geändert. Bestehender Starlette/httpx-TestClient-
  Deprecation-Hinweis bleibt bestehen.
- Kein echter GPU-/Modelltest, Download von Tensor-Daten, Deployment oder Reboot.
  Bildqualität, Noct-Renderzeit und tatsächlicher RAM-Peak sind offen.
