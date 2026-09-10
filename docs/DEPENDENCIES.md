# Dependencies und Service-Umgebungen

MLX läuft nativ auf macOS/Apple Silicon. Nur die Web-App läuft in Docker/OrbStack.
Der macOS-Agent bleibt die Bridge zum Host; die bestehende Runtime wird weiterhin
über `~/bin/mlx` und `~/.config/mlx-server/config` verwaltet.

## Getrennte Umgebungen und Python-Versionen

Die Services haben absichtlich getrennte Venvs. Insbesondere DiffusionKit und die
aktuelle MLX-Runtime benötigen unterschiedliche MLX-Versionen. Requirements nicht
in einer gemeinsamen Umgebung installieren.

| Umgebung | Manifest | Empfohlene und frisch getestete Python-Version |
| --- | --- | --- |
| `agent-venv` | `requirements/agent.txt` | 3.13.15 |
| `runtime-venv` | `requirements/runtime.txt` | 3.13.15 |
| `embedding-venv` | `requirements/embeddings.txt` | 3.11.15 |
| `image-venv` | `requirements/images.txt` | 3.11.15 |
| `speech-venv` | `requirements/speech.txt` | 3.13.15 |
| `test-venv` | `requirements/test.txt` | 3.13.15 |
| Web-Container | `requirements/web.txt` | 3.13 (`python:3.13-slim`) |
| Optionale separate MFLUX-Umgebung | `requirements/mflux.txt` | 3.13.15 |

Stand 2026-09-10: Alle Manifeste wurden aus leeren Venvs vom öffentlichen PyPI
installiert, auf Apple Silicon (arm64), macOS 26.6.2, mit Python 3.11.15 bzw.
3.13.15. Die Tabelle beschreibt getestete Kombinationen, keine vollständige
Liste aller unterstützten Python-/macOS-Versionen. Die nativen MLX-Imports
benötigen Metal-Zugriff; eine Sandbox ohne GPU-Zugriff reicht dafür nicht aus.
Für MLX 0.32.2 existieren macOS-Wheels ab macOS 14; der gesamte Stack wurde hier
nur auf macOS 26.6.2 getestet. Das Dockerfile legt Python 3.13 fest; die Web-
Dependencies wurden zusätzlich in einem nativen Python-3.13-Test-Venv geprüft,
ohne die Web-App außerhalb Docker zu betreiben oder ein Docker-Image neu zu bauen.

## Requirements und Constraints

Die Service-Manifeste nennen die direkt benötigten Pakete. Embeddings, Images
und Speech binden jeweils `-c constraints/<service>.txt` ein. Die relativen Pfade
werden von pip relativ zur Requirements-Datei aufgelöst.

Constraints sichern die getesteten MLX-/Transformers-API-Kombinationen:

| Constraints | Begründung |
| --- | --- |
| Embeddings: `mlx-vlm==0.7.0`, `transformers==5.17.0` | `mlx-embeddings` importiert `mlx_vlm.utils` und die Transformers-Tokenizer-/Processor-APIs. |
| Speech: `mlx==0.32.2`, `transformers==5.16.1` | Getestete Inferenz-/Tokenizer-Bibliotheken für `mlx-audio==0.5.1`. |
| Images: `mlx==0.17.3`, `torch==2.14.0`, `transformers==5.16.1` | Getestete Import-Kombination des bestehenden DiffusionKit-Providers; bewusst separat vom modernen MLX-Stack. |

Übernommene Pins für zufällig vorhandene HTTP-, NumPy-, SciPy- und Utility-Pakete
wurden entfernt. Diese Pakete werden nur installiert, wenn Upstream-Abhängigkeiten
sie tatsächlich anfordern. Eine Constraint-Zeile allein installiert kein Paket.
Die Manifeste ermöglichen die unten geprüfte Neuinstallation; sie sind kein
vollständiger Hash-/Versions-Lock aller transitiven Abhängigkeiten. Deren genaue
Versionen können bei einer späteren Installation variieren.

### Embeddings

[`mlx-embeddings==0.1.0`](https://pypi.org/project/mlx-embeddings/0.1.0/) ist bereits
die moderne, im Projekt verwendete Lösung. Das veröffentlichte Wheel importiert
`RepositoryNotFoundError` aus dem öffentlichen `huggingface_hub.errors` und bietet
weiterhin `mlx_embeddings.utils.load` und `generate` an. Die alte Version 0.0.1
verwendet den nicht mehr vorhandenen privaten Pfad
`huggingface_hub.utils._errors`; sie gehört nicht zur dokumentierten Installation.
Kein Hugging-Face-Downgrade und kein `sys.modules`-Shim sind erforderlich.

Die finale Neuinstallation löste Hugging Face Hub 1.31.0 und NumPy 2.4.6 auf.
Bibliotheks-/App-Imports und die Verträge von `/health`, `/embedding`, `/embeddings`
wurden geprüft; `model`, `dimensions` (1024) und `vectors` bleiben mit
`agent/knowledge.py` kompatibel. Die API-Prüfung nutzte gemockte Vektoren,
keine Modellinferenz. Die Upstream-Abhängigkeit `mlx-vlm` zieht auch Audio-/Vision-
Pakete nach; diese werden nicht zusätzlich als direkte Projektabhängigkeiten geführt.

### Speech

`requirements/speech.txt` fordert
[`mlx-audio[stt]==0.5.1`](https://pypi.org/project/mlx-audio/0.5.1/) an. Dessen
Paketmetadaten deklarieren `sentencepiece>=0.2.0` und `zstandard>=0.23.0` für das
STT-Extra. Die frische Installation enthält beide (0.2.2 bzw. 0.25.0); keine
zusätzlichen manuellen Installationsschritte sind nötig. Nicht jedes STT-Modell
benötigt beide unmittelbar, sie gehören aber zum ausgewählten vollständigen Extra.
Eine alte Umgebung ohne diese Pakete ist kein Nachweis gegen dieses Manifest.
Der getestete Python-3.13-Resolver wählte NumPy 2.5.3 und SciPy 1.18.1, die laut
Metadaten Python >=3.12 benötigen. Python 3.13 ist die geprüfte Empfehlung.

### Images und optionale MFLUX-CLI

`requirements/images.txt` enthält DiffusionKit 0.5.1. Dessen Metadaten fordern
unter anderem `argmaxtools`, Torch, MLX und Transformers an. Die dadurch
installierten Konverterpakete sind transitive Upstream-Abhängigkeiten.
Der Import von `diffusionkit.mlx.FluxPipeline` funktioniert im frischen Venv.
Core ML Tools warnt dabei vor ungetestetem Torch 2.14.0 und deaktiviert seine
scikit-learn-Konvertierung mit scikit-learn 1.9.0. Der Projekt-Worker verwendet
die MLX-Pipeline, nicht diese Konverter; deren Kompatibilität wird hier nicht
zugesichert. DiffusionKit bleibt ein veralteter, isolierter Legacy-Provider.

[`mflux==0.19.1`](https://pypi.org/project/mflux/0.19.1/) wird separat installiert.
Der vorher dokumentierte Pin 0.33.1 war auf PyPI nicht verfügbar. Alle fünf vom
Projekt benötigten CLI-Befehle sind in 0.19.1 vorhanden; ihre Parser akzeptieren
die vom Adapter erzeugten Argumente. Der nicht unterstützte Schalter
`--no-progress` wurde aus dem Adapter entfernt. Es fand keine Bildgenerierung statt.

`requirements/test.txt` bündelt Agent-, Web-, HTTP-Testclient- und Pillow-Pakete
ohne MLX. Die Python-Tests verwenden `unittest`; die JS-Tests benötigen Node.js.
Eine Node-Version ist im Repository nicht festgelegt.

## Installation

Die folgenden Befehle sind Anleitungen, keine automatisch ausgeführten Schritte.
Im Repository-Verzeichnis ausführen. Vorhandene Venvs weiterverwenden; den
jeweiligen `venv`-Erzeugungsbefehl nur für eine noch nicht vorhandene Umgebung
ausführen. Python 3.11 beziehungsweise 3.13 muss bereits verfügbar sein.

```sh
python3.13 -m venv agent-venv
agent-venv/bin/python -m pip install -r requirements/agent.txt

python3.13 -m venv runtime-venv
runtime-venv/bin/python -m pip install -r requirements/runtime.txt

python3.11 -m venv embedding-venv
embedding-venv/bin/python -m pip install -r requirements/embeddings.txt

python3.11 -m venv image-venv
image-venv/bin/python -m pip install -r requirements/images.txt

python3.13 -m venv speech-venv
speech-venv/bin/python -m pip install -r requirements/speech.txt

python3.13 -m venv test-venv
test-venv/bin/python -m pip install -r requirements/test.txt
```

Die Startparameter und Arbeitsverzeichnisse der nativen Dienste stehen unter
`launchd/templates/`. `scripts/install-launchd.sh` rendert diese Templates für
den aktuellen Rechner. Die MLX-Konfiguration und vorhandene Modellgewichte müssen
bereits eingerichtet sein. Speech benötigt zusätzlich eine vorhandene
FFmpeg-Installation; `FFMPEG_PATH` kann deren Pfad festlegen.

Die Web-App wird ausschließlich über Compose gebaut und gestartet:

```sh
docker compose up -d --build
```

Für die optionale MFLUX-CLI eine separate Python-3.13-Umgebung verwenden:

```sh
python3.13 -m venv mflux-venv
mflux-venv/bin/python -m pip install -r requirements/mflux.txt
```

Der Image-Service sucht die CLI standardmäßig unter `~/.local/bin`. Bei der
obigen separaten Installation muss `MLX_IMAGE_MFLUX_BIN` in seiner Host-Umgebung
auf den absoluten Pfad zu `mflux-venv/bin` zeigen. Paketinstallation lädt noch
keine Modellgewichte; die vorhandenen Image-Provider verwenden lokale Gewichte.

## Prüfergebnisse und lokale Importprüfung

Neu installiert wurden Agent, Runtime, Embeddings, Speech, Images, MFLUX, Web-
Dependencies und die Test-Umgebung. Nach Bereinigung der Constraints wurden
Embeddings, Speech und Images jeweils nochmals aus leeren Venvs installiert.
Alle elf Test-Venvs bestanden `python -m pip check`. Alle finalen Bibliotheks-/
FastAPI-Imports bestanden, ebenso die Runtime-Imports, fünf MFLUX-CLI-Hilfen,
die Parserprüfung der sechs vorhandenen MFLUX-Modelleinträge und 34 relevante
Unit-Tests in der frisch installierten Test-Umgebung.

Nach einer Installation lassen sich die zentralen Imports ohne Modellladen prüfen
(im Repository-Verzeichnis, mit nativem Metal-Zugriff):

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 embedding-venv/bin/python -c 'from mlx_embeddings.utils import load, generate; import embedding_service'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 speech-venv/bin/python -c 'from mlx_audio.stt import load; import sentencepiece, zstandard; import speech.app'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 image-venv/bin/python -c 'from diffusionkit.mlx import FluxPipeline; import image_service'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 runtime-venv/bin/python -c 'import mlx.core, mlx_lm, mlx_vlm'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 mflux-venv/bin/mflux-generate --help
```

Danach in jeder installierten Venv `<venv>/bin/python -m pip check` ausführen.
Die Prüfungen starten keinen Service-Lifespan und laden keine Modelle. Echte
Inferenz, FFmpeg und produktiver Servicebetrieb wurden nicht getestet. Der
vorhandene HTTP-Testclient funktioniert, meldet aber eine Upstream-Deprecation
für `httpx`; das ist kein fehlendes Paket und kein Fehler von `pip check`.

## Environment-Konfiguration

`.env.example` dokumentiert die aktuellen Variablen. Compose verwendet eine
lokale `.env` zur Variablenersetzung; nur ausdrücklich in `docker-compose.yml`
aufgeführte Werte gelangen in den Container. Native Python-Dienste und die
LaunchAgent-Templates laden diese Datei nicht automatisch.

| Variable | Verbraucher / Bedeutung |
| --- | --- |
| `AGENT_URL` | Web-Container: Agent-Adresse, standardmäßig `http://host.docker.internal:8010` |
| `MLX_WEB_PORT` | Compose: lokaler Web-Port, standardmäßig 8090 |
| `MAX_UPLOAD_SIZE_MB` | Web sowie native Upload-Dienste: standardmäßig 250; für native Dienste separat setzen |
| `MLX_ALLOWED_HOSTS` | Zugriffsschutz; Compose erlaubt `localhost,127.0.0.1,::1`, native Defaults zusätzlich `host.docker.internal` |
| `SPEECH_SERVICE_URL` | Agent: nativer Speech-Service, standardmäßig `http://127.0.0.1:8050` |
| `IMAGE_SERVICE_URL` | Agent: nativer Image-Service, standardmäßig `http://127.0.0.1:8030` |
| `MLX_ROUTER_MODEL_PATH` | Agent und LaunchAgent-Installationsskript: lokaler Router-Modellpfad |
| `MLX_EMBEDDING_MODEL_PATH` | Embedding-Service: lokaler Modellpfad, unterstützt `~` |
| `MLX_EMBEDDING_MAX_LENGTH` | Embedding-Service: 1–8192, Standard 8192 |
| `MLX_EMBEDDING_BATCH_SIZE` | Embedding-Service: 1–128, Standard 8 |
| `FFMPEG_PATH` | Speech-Service: expliziter FFmpeg-Pfad, sonst PATH-Suche und Homebrew-Fallback |

Die früheren Web-Environment-Variablen `MLX_URL`, `SPEECH_URL` und `IMAGE_URL`
werden dort nicht mehr gelesen. Die internen MLX-/Speech-URLs werden aus
`AGENT_URL` gebildet. Der Agent liest den nativen MLX-Port aus
`~/.config/mlx-server/config`; Speech und Images verwenden die oben genannten
Host-Variablen. Vorhandene `.env`-Dateien wurden nicht verändert.
