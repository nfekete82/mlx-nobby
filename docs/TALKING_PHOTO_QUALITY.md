# Talking Photo Quality: nativer, reproduzierbarer LTX-A2V-Pfad

## Datenfluss

`Text → Speech-Service → TTS-MP3 → ffmpeg PCM-WAV (16 kHz, Mono, 16 Bit) → End-Padding → LTX-2.5 MLX A2V → MP4`

Standardstimme: Der Request enthält `input` und `language`. ISO-Codes werden ausschließlich im Quality-Pfad auf die von Qwen erwarteten Sprachnamen übersetzt (`de` → `german`, `en` → `english` usw.). Das setzt den richtigen Sprach-Token, ohne Tempo oder Audiosamples zu manipulieren. Wie im ursprünglichen Pfad wird kein `voice`-Override gesetzt. Custom-Voices ergänzen ausschließlich `voice`. Bei `speed=1.0` wird kein Speed-Parameter gesendet. Es gibt keine automatische Anpassung an die Dauer einer anderen Stimme, kein zweites `atempo` und kein Entfernen der Anfangsstille. Eine ausdrücklich über die API angeforderte Geschwindigkeit wird weiterhin einmal an den Speech-Service weitergegeben. Das Talking-Photo-UI sendet `speed=1.0`.

Der Speech-Service erzeugt derzeit MP3. Die vorhandene WAV-Konvertierung verändert nur Format, Sample Rate und Kanäle. Das unveränderte zeitliche Signal bleibt erhalten; die MP3-Kodierung ist natürlich nicht verlustfrei. Voice-Manager-Qualitätsprofile beeinflussen die TTS-Samplingparameter, nicht die Daueranpassung im LTX-Pfad. Diese Einstellungen und andere Speech-/MuseTalk-/Shorts-Funktionen wurden nicht verändert.

## Audio und LTX

Die tatsächliche Samplezahl im WAV bestimmt die Videolänge. Die Anzahl der Frames wird auf das nächste gültige `8n+1`-Raster bei 24 FPS aufgerundet. Nur am Ende wird mit Stille aufgefüllt; keine Sprache wird abgeschnitten oder verlangsamt. Leere, abgeschnittene, falsch formatierte WAVs und Audio ohne aktives Signal oberhalb -45 dBFS scheitern vor dem teuren Rendern. Die Messwerte enthalten den Anteil aktiver 10-ms-Fenster; diese Signalprüfung ersetzt keine Spracherkennung.

Der installierte A2V-Loader liest 16 kHz und expandiert intern auf Stereo. Die encodierten Audio-Latents sind in beiden Stufen eingefroren und conditionieren die Videoerzeugung. Das finale MP4 bekommt wieder das Eingabeaudio, keine aus dem Audio-VAE rekonstruierte Stimme.

Die ursprünglichen Renderwerte bleiben erhalten:

- LTX-2.5 MLX Q4, lokaler Gemma-Encoder aus demselben Modelpack
- 15 Stage-1-Schritte, 3 Stage-2-Schritte, CFG 3.0, STG 1.0
- `low_memory=True`, `low_ram_streaming=True`, TeaCache aus
- Original-Talking-Prompt und ursprünglicher Negative Prompt
- 24 FPS; maximal 10 Sekunden Quellaudio
- Portrait 512×704, Landscape 704×512, quadratisch 640×640

Die installierte Stage-1-Pipeline verwendet zusätzlich `rescale_scale=0.7`, `modality_scale=3.0`, STG-Block 28. Stage 2 verfeinert ohne CFG und verwendet intern Seed + 2. Die Referenz dient als Bildanker im ersten Frame. Diese Runtime-Werte wurden geprüft und nicht geändert.

## Fester Seed und Debug-Artefakte

Die Agent-Prozessumgebung unterstützt:

```sh
LTX_TALKING_PHOTO_SEED=42
LTX_TALKING_PHOTO_DEBUG=1
# Alternativ ein frei gewähltes Debug-Verzeichnis:
LTX_TALKING_PHOTO_DEBUG_ROOT=/absolute/path/to/debug
```

Der Seed wird als Ganzzahl zwischen 0 und 2147483647 validiert. Auch 0 ist gültig. Ohne Variable bleibt die frühere Job-ID-Ableitung erhalten; ungültige Werte erzeugen einen klaren Fehler. `DEBUG_ROOT` aktiviert die Speicherung ebenfalls. Ohne eigene Root liegt sie unter `~/.config/mlx-web/talking-photo/render-debug/<job-id>/`.

Bei einem über launchd gestarteten Agent müssen diese Werte in dessen `EnvironmentVariables` stehen. Eine Shell-Variable oder ein Eintrag in `.env` allein konfiguriert einen bereits laufenden launchd-Prozess nicht. Der LaunchAgent muss nach einer Änderung seiner Umgebung per bootout/bootstrap neu geladen werden; ein bloßes kickstart übernimmt keine geänderte plist-Umgebung. Der Installer bewahrt diese drei Variablen bei einer Neuinstallation und übernimmt ausdrücklich gesetzte Werte. Für reine Codeänderungen genügt `./scripts/mlx agent restart`. Für isolierte Vergleiche ist das nachstehende CLI einfacher und braucht keinen Dienstneustart.

Jeder Debug-Run speichert TTS-Request und TTS-Output, Referenzbild, Quell-WAV, exakt das WAV aus dem finalen `--audio`-Argument, `render.json`, `runner.json`, Log und Output-MP4. `render.json` enthält Seed, Prompt/Negative Prompt, Frames, FPS, Quell- und gepaddete Audiodauer, Pegel, Hashes und den vollständigen Command. `runner.json` speichert die effektiven Pipelineargumente einschließlich Defaults und Messungen direkt am tatsächlich aufgerufenen Audio-Loader. Neue Runs enthalten zudem Paketversionen, Pythonversion sowie Hashes von Pipelinequelle und Modellkonfiguration.

`audio-debug/*.wav` ist weiterhin das Quell-WAV vor End-Padding; `stage=source-before-padding` kennzeichnet diesen Unterschied. Für das echte Conditioning-WAV den Render-Bundle verwenden.

## Regression und Seedvergleich

Eine neue TTS-Ausgabe einmal erzeugen und dann einfrieren:

```sh
test-venv/bin/python scripts/debug-talking-photo-quality.py \
  --image /path/to/portrait.png \
  --text 'Hallo, das ist ein kurzer Test meiner Stimme.' \
  --voice Julia \
  --seeds 42,1234,1337,2026,858797624 \
  --output /path/to/new-comparison
```

Für die Standardstimme `--voice` weglassen. Bestehendes Audio wird mit `--audio /path/to/speech.wav` statt `--text` eingefroren. Das CLI nutzt den echten Projekt-Renderer samt Runtime-Koordination. Es rendert keine parallelen GPU-Jobs.

Zwei identische Wiederholungen:

```sh
test-venv/bin/python scripts/debug-talking-photo-quality.py \
  --image /path/to/portrait.png --audio /path/to/speech.wav \
  --seeds 42 --repeat 2 --output /path/to/new-regression
```

`--prepare-only` friert die Eingaben ohne Rendern ein. `--resume` verwendet ausschließlich die bereits eingefrorenen Dateien, prüft ihre SHA-256-Hashes und überspringt abgeschlossene Videos. Gleicher Text und gleiche Stimme allein reichen nicht: Qwen-TTS kann neu samplen. Für einen kontrollierten LTX-Vergleich ist dasselbe WAV zwingend.

`comparison.json` enthält Conditioning-Audiohashes, MP4-Hashes und Hashes der dekodierten Videoframes (`frames.md5`). Auf identischer Hardware/Runtime lassen sich damit identische Bilder prüfen. Ein deterministischer Seed garantiert keine gute Artikulation; die Vergleichsvideos müssen zusätzlich auf Mundbewegung, Audio-Synchronität und Identität geprüft werden.

## Lokale Untersuchung vom 5. Oktober 2026

Eine weitere geprüfte Fehlerquelle war der Sprachcode: Qwen erwartet im installierten Modelpack `german`, nicht `de`. Mit `de` blieb der deutsche Sprach-Token ungesetzt. Eine frische Standard-Ausgabe wurde auch mit deutscher ASR ungenau erkannt; nach der Quality-lokalen Korrektur bestätigte die automatische ASR wieder den erwarteten deutschen Satz. Die gemeinsame Speech-Service-Logik bleibt unverändert.

Die vollständigen privaten Ergebnisse liegen unter `artifacts/talking-photo-regression/` und werden von Git ignoriert. Dazu gehören historische Job-/WAV-Messungen, lokale ASR-Transkripte, Seedvergleiche und frische Jobs über die reparierte TTS-Orchestrierung. Der Abschlussbericht wird dort als `REPORT.md` gespeichert.

Nachgewiesene Altlasten: Pervin wurde im Speech-Service mit 0.8 und anschließend nochmals mit 0.8 verlangsamt; das frühere Julia-Profil tat dasselbe mit 0.71. Diese Profile, der zusätzliche ffmpeg-Tempo-Pass und das Custom-Voice-Silence-Trimming sind aus dem Quality-Pfad entfernt. Ein älterer Versuch zur Anpassung an Standard-Audiodauer war im aktuellen Produktionspfad bereits nicht mehr vorhanden. Das separate historische Kalibrierungsskript wird nicht von Talking Photo aufgerufen und wendet keine Profile automatisch an.

Die erhaltenen Standard-, Julia- und Pervin-WAVs wurden durch lokale ASR als verständliche Sprache desselben Satzes bestätigt. Der einzige noch gespeicherte abgeschlossene LTX-Job zeigt einen nahezu unverändert geöffneten Mund. Die anderen erhaltenen Talking-Photo-Videos sind MuseTalk-Ausgaben, kein Beleg für einen früher guten LTX-Lauf. Das Originalreferenzbild dieses LTX-Jobs war nicht gespeichert; für die neuen Vergleiche wurde sein erster Frame als festes Testbild extrahiert. Der Vergleich zu diesem historischen Video ist daher kein exakt rekonstruierter A/B-Test.

Zwei Standard-Audio-Runs mit Seed 42 waren sowohl im dekodierten Videoinhalt als auch als MP4 bytegleich. Sie zeigen sichtbare Lippen-/Kieferbewegung. Die Qualität anderer Seeds und frischer Custom-Voice-Runs ist im lokalen Abschlussbericht getrennt dokumentiert. Perfekte phonemgenaue Synchronität wird nicht allein aus Kontaktbögen oder Hashes abgeleitet.
