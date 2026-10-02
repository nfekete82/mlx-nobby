# Performance-, Reliability- und Architektur-Audit

Audit vom **1. Oktober 2026**, Ausgangscommit
`2f63e4fd1b40cec0a273b50283b90311164e2ef6`, Branch
`perf/runtime-and-frontend-audit`. Lokaler M5-Max-Workspace mit 48 GB Unified
Memory, Webcontainer auf 8090, Agent auf 8010 und `mlx_vlm` auf 8000.
Aktives Modell: `~/Models/Qwen3.8-27B-Abliterated-MLX-4bit`.

Dies ist ein historischer Messbericht. Modellnamen, lokale Pfade und Branch
bezeichnen die damalige Testkonfiguration, keine Produktvorgaben. Die aktuelle
Diagnoseoberfläche beschreibt [Performance Observatory](PERFORMANCE_OBSERVATORY.md).

## Ergebnis und Gültigkeitsbereich

Fünf gezielte Änderungen wurden umgesetzt:

1. Die selbst auslösende Workspace-Observer-Schleife beseitigen.
2. Gleichzeitige Workspace-Abfragen zusammenfassen und Initialisierung absichern.
3. Automatische Diagnose-Abfragen auf sichtbare Panels beschränken.
4. Die Lock-Reihenfolge für Agent-Modellaufrufe und Image-Prompt-Optimierung
   an den bestehenden Text-Streaming-Pfad angleichen.
5. Explizites deutsches „Ändere keine Dateien“ im vorhandenen Read-only-Pfad
   erkennen, damit ein gelesener Workspace nicht wiederholt neu geplant wird.

Der Vision-Reliability-Fix aus dem Ausgangscommit bleibt erhalten. Modellrollen,
Quantisierung, Media-Intent-/Vision-Routing und Watchdog-Fristen wurden nicht
geändert. Die Runtime-Lease und der Modell-Lock bleiben bestehen.

**Nachgewiesener Gewinn:** Eine isolierte echte Chat-Seite erzeugt nach dem
Start keine periodischen Workspace-Requests mehr. Ihr medianer API-Verkehr sinkt
von **14.946 auf 18 Requests/min**. Der konkurrierende Lock-Test blockierte vorher
in allen fünf Läufen; nachher kommen beide Threads in allen fünf Läufen weiter.

**Finale Hostprüfung nach Benutzer-Reload:** Fünf passive Idle-Fenster mit genau
einem frisch hart neu geladenen Nobby-Tab zeigen **null Workspace-Requests**.
Agent-CPU sinkt gegenüber der passiven Altclient-Serie von **84,56 % auf 0,82 %**
eines Kerns, OrbStack von **189,43 % auf 1,43 %**. Die Gesamt-CPU ist
**87,68–94,81 % idle**. Es gibt keinen verbleibenden Hinweis auf die Request-Schleife
oder ungewöhnliche Nobby-Idle-Last. Der kontrollierte Dienstvergleich und die
Grenzen der Gesamt-Host-/RAM-Vergleichbarkeit stehen unten. Es wird kein belegter
Gewinn an Modell-TTFT, Tokens/s oder Unified Memory behauptet.

## Messverfahren

- Vorher- und Nachher-Läufe verwenden dasselbe aktive Modell, dieselben Rollen,
  Temperatur 0 und maximal 48 Ausgabe-Tokens.
- Textprompt: `Name the two colors red and blue in one short sentence.`
- Vision: synthetisches RGB-Bild, 256 × 256 Pixel, linke Hälfte rot, rechte Hälfte
  blau. Prompt: `Name the two main colors in this image in one short sentence.`
- Webpfad: `POST /api/chat/reliable-stream`. Pro Modalität ein separat erfasster
  erster Lauf und fünf weitere Läufe. Native Vision: fünf zusätzliche Requests
  an `/v1/chat/completions`, `stream: false`, `enable_thinking: false`.
- First transport umfasst SSE-Kommentare; first semantic umfasst ausschließlich
  nichtleeren Assistant-Inhalt oder Reasoning. Sources, Metrics, Heartbeats und
  HTTP-Header gelten nicht als Modelltoken.
- Native `timings.prompt_ms`, `predicted_per_second` und `peak_memory` liefern
  Prefill, Decode-Rate und den gemeldeten MLX/Metal-Speicherpeak. Die vollständige
  native JSON-Antwort liefert **keine** beobachtete Modell-TTFT.
- Median und p95: fünf Läufe, p95 als nearest rank, also hier der größte Wert.
  Diese kleine Stichprobe beschreibt die lokale Streuung, keinen belastbaren
  Lasttest. Initiale Modell-Ladevorgänge werden nicht in Warm-Mediane gemischt.
- Browser: installiertes Chrome in einem eigenen temporären Headless-Profil;
  Steuerung per Chrome DevTools Protocol mit Node-WebSocket, ohne zusätzliche
  Bibliotheken. Fünf Fenster à zehn Sekunden nach drei Sekunden Anlaufzeit;
  Requests über `Network.requestWillBeSent` gezählt.
- Observer-Reproduktion: echtes Browser-DOM und `MutationObserver`, isoliertes
  Workspace-Modul, konstante Antwort mit 10 ms simulierter Netzwerklatenz,
  fünf Fenster à einer Sekunde. Kein Zugriff auf produktive Workspace-Daten.
- Host: fünf zehnsekündige Fenster mit inkrementellem Lesen ab dem aktuellen
  Ende von `agent.log`; Prozess-RSS und kumulierte CPU-Zeit über `ps` alle zwei
  Sekunden, zusätzlich `top`, `vm_stat`, `memory_pressure -Q` und `sample`.
  CPU-Prozentwerte aus CPU-Zeit-Deltas beziehen sich auf einen logischen Kern.
- Laufzeit-Locks: tatsächliche Lease-/Queue-Diagnose plus deterministischer
  Zwei-Thread-Test mit begrenztem 250-ms-Lock-Wait. Kein produktiver Lock wird
  absichtlich für diesen Test festgehalten.

### Reproduzierbare Chat-Messung

Das dauerhafte Werkzeug nutzt ausschließlich die Python-Standardbibliothek,
ändert keine Runtime-Einstellungen und schreibt Ergebnisse nur an den angegebenen
Pfad. Nach einem Fehler bricht es ab, statt weitere Prüfanfragen einzureihen.
Vorher aktive Medienjobs abschließen lassen und alte Nobby-Tabs neu laden.

```sh
python3 scripts/benchmark-chat.py \
  --label audit --runs 5 \
  --native-model "$HOME/Models/Qwen3.8-27B-Abliterated-MLX-4bit" \
  --output /tmp/nobby-chat-audit.json

python3 scripts/benchmark-chat.py \
  --label long-vision --kind vision --image-size 1024 --context-records 4000 \
  --runs 5 --output /tmp/nobby-long-vision-audit.json
```

Der erste Lauf ist ein Warmup, **nicht automatisch ein Cold-Run**. Ein echter
Cold-Run erfordert nachgewiesenen unbeladenen Modellzustand. Der Audit hat die
Modell-Runtime nicht für künstliche Cold-Runs neu gestartet. Der erste
Vorher-Lauf traf auf eine noch nicht resident geladene Runtime; später gab es
einen natürlichen Media-Handoff. Dafür gibt es keine Cold-p95 mit fünf Samples.

Request-Rate ohne vollständiges Lesen des großen Logs reproduzieren:

```sh
python3 - <<'PY'
from pathlib import Path
import time
with Path('agent.log').open('rb') as log:
    log.seek(0, 2)
    for _ in range(5):
        start = time.perf_counter()
        time.sleep(10)
        data = log.read()
        seconds = time.perf_counter() - start
        print('workspace calls/min:',
              data.count(b'GET /api/code/workspaces HTTP') * 60 / seconds,
              'new log bytes:', len(data))
PY
```

## Before / After

### Kontrollierte Browsermessungen

| Messung | Vorher | Nachher |
| --- | ---: | ---: |
| Workspace-Modul, Requests in 1 s, fünf Läufe | 95, 93, 92, 92, 92 | 1, 1, 1, 1, 1 |
| 20 gleichzeitige Workspace-Reads, fünf Läufe | jeweils 20 Requests | jeweils 1 Request |
| Gesamtdauer des 20-Read-Bursts, Median / p95 | 11,1 / 11,4 ms | 11,2 / 11,6 ms |
| Chat-Seite, Workspace-Calls/min, Median / p95 | 14.910 / 15.270 | 0 / 0 |
| Chat-Seite, alle API-Calls/min, Median / p95 | 14.946 / 15.294 | 18 / 324 |
| Geschlossene Diagnose-Panels, Calls in 50 s | Observatory 7, Health 5 | jeweils 0 |
| Gleichzeitige Chat-/Agent-Locks, erfolgreiche Chat-Lock-Acquires | 0 von 5 | 5 von 5 |
| Kontrollierter Chat-Lock-Wait, Median / p95 | 250,907 / 251,866 ms, Timeout | 0,00171 / 0,00179 ms |

Der 250-ms-Wert ist die **Test-Abbruchgrenze**, keine obere Grenze des alten
produktiven Deadlocks. Der neue Mikrosekundenwert beschreibt einen unbelasteten
lokalen Lock, keine erwartete Antwortlatenz des Gesamtprodukts.

Workspace-Calls pro zehnsekündigem Browserfenster:
`2231, 2485, 2473, 2545, 2488` → `0, 0, 0, 0, 0`.
Nachher gab es im ersten Fenster noch 26 Discovery-, 26 Benchmark-History- und
26 Sprachdatei-Abfragen des unveränderten Model-Scout-Startups. Daher der höhere
API-p95. In den weiteren Fenstern verblieben zwei Status-Requests pro zehn
Sekunden und gegebenenfalls die Automation-Notification-Abfrage.

### Chat, Vision und Host

Die erste Nachher-Serie unten erfolgte nach Frontend-Rollout, vor der späteren
Lock-Korrektur, mit weiterhin laufendem alten Chrome-Tab. Sie ist ausdrücklich
keine Messung unter beseitigter Host-Hintergrundlast.

| Messung | Vorher: Median / p95 | Nach Frontend-Rollout: Median / p95 |
| --- | ---: | ---: |
| Text, HTTP-Header | 2,01 / 4,39 ms | 1,71 / 4,03 ms |
| Text, first semantic SSE | 901,92 / 960,62 ms | 1019,96 / 1043,60 ms |
| Text, Gesamtdauer | 1038,52 / 1094,18 ms | 1156,73 / 1175,72 ms |
| Text, Agent-Modell-TTFT laut Metrik | 379,27 / 392,86 ms | 434,52 / 443,04 ms |
| Text, Lease + Modell-Lock-Wait | 11,777 / 15,401 ms | 8,272 / 12,059 ms |
| Vision, first transport | 2,68 / 3,92 ms | 3,58 / 4,88 ms |
| Vision, first semantic SSE | 926,91 / 958,03 ms | 1044,32 / 1075,86 ms |
| Vision, Gesamtdauer | 928,98 / 958,91 ms | 1050,91 / 1079,08 ms |
| Vision, Bridge-Modell-Lock-Wait | 0,001 / 0,004 ms | 0,001 / 0,001 ms |
| Native Vision, Prefill | 166,89 / 168,94 ms | 209,92 / 214,93 ms |
| Native Vision, Decode-Tokens/s | 30,443 / 30,619 | 30,231 / 30,754 |
| Native Vision, gemeldeter MLX-Speicherpeak | 23,692 / 23,692 GB | 23,692 / 23,692 GB |
| Host, alle Agent-Requests/min | 54.240 / 61.919 | 57.596 / 62.643 |
| Host, Workspace-Calls/min | 54.210 / 61.919 | 57.578 / 62.631 |

Die Warm-Inferenz wurde in dieser Serie nicht schneller. Die Änderungen werden
wegen der **separat bewiesenen Request-Reduktion und Deadlock-Vermeidung** behalten.
Die vorhandenen Störlasten und die nacheinander gemessenen Serien erlauben keine
kausale Zuordnung der rund 0,12 s höheren Web-Latenz zum Frontend-Patch.

Der erste Text-Vorher-Lauf dauerte 25,904 s, first semantic 25,763 s;
die fünf warmen Folge-Läufe liegen in der obigen Tabelle. Vision lieferte bei
allen zwölf kurzen Web-Läufen Inhalt und jeweils einen initialen Heartbeat.
Text-Decode-Tokens/s werden nicht als gemessen ausgewiesen: Der Agent-Stream
verwendete bei diesem `mlx_vlm`-Upstream eine **geschätzte** Tokenzahl. Native
Vision liefert dagegen eine tatsächliche Decode-Rate.

CPU aus den etwa 49 s langen Sample-Intervallen:
Agent **74,81 % → 76,24 %**, OrbStack **169,38 % → 173,76 %**. Der alte Browser-Tab
lief in beiden Intervallen weiter. Kein belegter Host-CPU-Gewinn.
Agent-RSS: erster Vorher-Sample 128,86 MiB, nach warmen Aufrufen 267,86 MiB;
in der Nachher-Serie 247,16–247,83 MiB. Auch daraus folgt kein belegter
Memory-Leak oder Memory-Fix. `ps`-RSS und MLX/Metal-Speicher werden nicht addiert.
`memory_pressure` ist ein macOS-Verfügbarkeitssignal und keine exakte
Unified-Memory-Bilanz.

### Passive Hostmessung vor dem Benutzer-Reload (Altclient)

Nach allen fünf Änderungen wurden erneut fünf Fenster à zehn Sekunden ohne
zusätzliche Modell-Benchmarks erfasst. Der alte Chrome-Tab blieb aktiv:
Workspace-Calls/min `59.724; 61.112; 60.327; 61.094; 59.616`, Median **60.327**,
p95 **61.112**. Alle Agent-Calls/min: Median **60.345**, p95 **61.124**.
Agent-PID **17962**: CPU aus Zeit-Deltas **84,56 %**, RSS **390,22–396,12 MiB**;
OrbStack **189,43 %**, RSS **1250,27–1232,23 MiB**. Das bestätigt die weiterhin
aktive Altclient-Last. Der kleine RSS-Anstieg in diesem kurzen Fenster reicht
nicht zur Diagnose eines Leaks und wird nicht als Memory-Verbesserung dargestellt.

Die abschließenden zwei kurzen Vision-Webrequests nach dem fünften Fix lieferten
Inhalt ohne Fehler. Die anschließende Hostprüfung mit neu geladenem Client folgt unten.

### Finaler Whole-Host-Idle-Vergleich nach dem Benutzer-Reload

**1. Oktober 2026, 15:14:50–15:15:41 CEST.** Der Benutzer bestätigte, dass alle
alten Nobby-Tabs geschlossen sind und genau ein frisch hart neu geladener Tab
läuft. Zehn Sekunden zusätzliche Ruhezeit, anschließend fünf passive Fenster
von jeweils 10,037–10,043 s. Keine Inferenz, Tests, zusätzlichen HTTP-Probes,
Dienstneustarts oder Runtime-Änderungen während dieser Messung. Normale
Status-/Notification-Timer und andere Desktop-Anwendungen bleiben aktiv.

Vergleichsbasis ist die unmittelbar vorher dokumentierte passive **5 × 10 s**
Altclient-Serie nach denselben fünf Codeänderungen. Agent **17962**, OrbStack
**920** und Modellserver **79089** bleiben dieselben Prozesse; der anschließende
Status bestätigt dasselbe Modell und `thinking: false`. Die Intervention ist
Schließen der Altclients plus Hard-Reload, kein weiterer Backend-Patch. Das ist
ein Vergleich der Nobby-Idle-Last bei korrigiertem Client, kein vollständig
isoliertes A/B des gesamten Desktops oder verschiedener Backend-Versionen.

| Fenster | Workspace-Requests | Agent-Requests/min | Agent-CPU, ein Kern | OrbStack-CPU, ein Kern | Host-CPU idle | PhysMem used / unused laut `top` |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 0 | 11,95 | 0,80 % | 1,49 % | 91,54 % | 40G / 7173M |
| 2 | 0 | 17,93 | 0,90 % | 1,39 % | 93,78 % | 40G / 7362M |
| 3 | 0 | 17,93 | 0,90 % | 1,49 % | 94,81 % | 40G / 7479M |
| 4 | 0 | 11,95 | 0,70 % | 1,49 % | 87,68 % | 42G / 5414M |
| 5 | 0 | 17,92 | 0,80 % | 1,29 % | 91,70 % | 42G / 5394M |

`top -l 6 -s 10 -n 0` liefert nach Verwerfen der ersten CPU-Anzeige fünf
Intervallwerte. Diese laufen parallel zu den Prozess-/Logfenstern, nicht exakt
an deren Grenzen; `top` und Snapshot-Aufrufe erzeugen selbst etwas Messlast.
Die Hostwerte sind über **18 logische Kerne** normalisiert. Prozess-CPU wird
aus kumulierter CPU-Zeit berechnet, nicht aus dem geglätteten `ps %cpu`:
`100 × (CPU-Sekunden Ende − Anfang) / verstrichene Sekunden`.

| Vergleich | Altclient, passive Vorher-Serie | Ein neu geladener Nobby-Tab |
| --- | ---: | ---: |
| Workspace-Calls/min, Median / p95 | 60.327 / 61.112 | 0 / 0 |
| Alle Agent-Calls/min, Median / p95 | 60.345 / 61.124 | 17,92 / 17,93 |
| Agent-CPU aus gesamtem Zeit-Delta | 84,56 % | 0,82 % |
| OrbStack-CPU aus gesamtem Zeit-Delta | 189,43 % | 1,43 % |
| Agent-RSS, beobachteter Bereich | 390,22–396,12 MiB | 403,70–404,50 MiB |
| OrbStack-RSS, beobachteter Bereich | 1232,23–1250,27 MiB | 998,67–1057,22 MiB |
| `memory_pressure -Q`, Verfügbarkeitssignal | 53–89 % | 87–89 % |
| Gesamt-Host-CPU, Median idle / größter Busy-Wert | kein entsprechender Fünf-Fenster-Baselinewert | 91,70 % / 12,32 % |
| PhysMem-/Swap-/VM-Zähler pro Fenster | nicht in der passiven Baseline erfasst | unten dokumentiert |

Insgesamt **13** Agent-Requests: zehn `GET /api/status`, drei
`GET /api/automations/notifications?limit=50&unread_only=false`. **Kein einziger**
`GET /api/code/workspaces`, keine Diagnose-Panel-Requests und keine Chat-Requests
in 50,201 s. Das Log wächst um insgesamt **944 Bytes**. Die Vorher-Serie enthält
zusätzlich wenige Initialisierungs-Probes; sie erklären den damaligen Sturm nicht.
Die zuvor hohe Agent-/OrbStack-Last verschwindet mit dem Altclient. Das ist ein
belegter Rückgang dieser Prozesslast, keine aus fehlenden Baselinewerten
berechnete Gesamt-Host-CPU-Verbesserung.

**RAM / Unified Memory:** `hw.memsize` = **51.539.607.552 Bytes (48 GiB)**.
`top` meldet während der fünf Intervalle gerundet **40–42G used**, **5394–7479M
unused**, **3981–4808M wired** und **863–868M compressor**; Angaben hier bewusst
in den originalen `top`-Einheiten. Sechs `vm_stat`-Snapshots mit 16.384-Byte-Seiten:
freie Seiten **306.540–448.137**, aktive **1.155.011–1.199.639**, inaktive
**1.133.447–1.177.114**, wired **254.806–311.242**, vom Compressor belegte
**55.202–55.553**. Swap belegt **7065,75 → 7057,75 MiB** von 8192 MiB;
**804 Swapins** (12,56 MiB), **0 neue Swapouts**, keine neuen Pageouts.
Hoher bereits belegter Swap allein ist kein Nachweis aktuellen Speicherdrucks.
Modellserver-RSS bleibt **311,39 MiB**, CPU über die Serie **0,86 %** eines Kerns.
RSS bildet die Metal-/Unified-Memory-Allokation des Modells nicht vollständig ab;
RSS, `top`-PhysMem und der frühere Inferenzpeak werden nicht addiert.

**Restlast und Grenzen:** Größter beständiger Prozess ist WindowServer mit
**28,58–45,41 % eines Kerns** (gesamt 37,19 %), gefolgt von wechselnden Chrome-
und Desktop-Prozessen. Im vierten Fenster entstehen zusätzliche Chrome-Renderer;
das fällt mit dem Anstieg von 40G auf 42G zusammen. Ihre Seitenzuordnung wurde
nicht ermittelt; dieser zeitliche Zusammenhang beweist keine Memory-Root-Cause.
Nobby-Agent und Modellserver bleiben dabei nahezu konstant, Workspace-Requests
bei null. Die Gesamt-CPU bleibt mindestens 87,68 % idle; keine ungewöhnliche
fortbestehende Host-Last verlangt hier einen weiteren Nobby-Fix. Der Desktop war
nicht vollständig kontrolliert. Insbesondere ist **kein belegter RAM-Gewinn**
festzustellen: Agent-RSS liegt sogar etwas höher als vorher. OrbStack-RSS ist
niedriger, aber daraus folgt keine generelle Unified-Memory- oder Leak-Verbesserung.
Eine 50-s-Idle-Stichprobe ersetzt keinen längeren Memory-Soak.

#### Reproduktion der passiven Hostmessung

Nach Hard-Reload nur einen Nobby-Tab offen lassen, keine Chat-/Media-Aufträge
starten und während der Messung keine Tests laufen lassen. Im Repository-Root
folgender Standardbibliothek-Aufruf; er liest das bestehende Log nur ab dessen
Ende und verändert weder Dienste noch Runtime-Einstellungen. Die JSON-Datei
enthält Zeitstempel, vollständige Prozess-/VM-Snapshots, Request-Zähler und die
sechs `top`-Ausgaben. Erste `top`-CPU-Anzeige verwerfen; Prozess-CPU nach obiger
Formel aus jeweils benachbarten Snapshots berechnen. Systemmessung auf macOS
gegebenenfalls außerhalb einer Prozess-/Netzwerk-Sandbox ausführen.

```sh
python3 - <<'PY_IDLE'
import collections, json, pathlib, re, subprocess, time

def capture(*args):
    return subprocess.check_output(args, text=True)

def snapshot():
    return {"at": time.monotonic(),
            "ps": capture("ps", "-axo", "pid,ppid,%cpu,rss,time,comm"),
            "vm": capture("vm_stat"),
            "pressure": capture("memory_pressure", "-Q"),
            "swap": capture("sysctl", "-n", "vm.swapusage")}

time.sleep(10)
out = {"hardware": capture("sysctl", "-n", "hw.memsize", "hw.logicalcpu"),
       "snapshots": [], "windows": []}
with pathlib.Path("agent.log").open("rb") as log, \
        pathlib.Path("/tmp/nobby-idle-top.txt").open("w+") as top_log:
    log.seek(0, 2)
    top = subprocess.Popen(["top", "-l", "6", "-s", "10", "-n", "0"],
                           stdout=top_log)
    before = snapshot()
    out["snapshots"].append(before)
    for _ in range(5):
        time.sleep(max(0, before["at"] + 10 - time.monotonic()))
        after = snapshot()
        data = log.read()
        requests = collections.Counter(re.findall(
            r' - "([A-Z]+ [^\"]+) HTTP/', data.decode(errors="replace")))
        out["windows"].append({"seconds": after["at"] - before["at"],
                               "requests": dict(requests), "log_bytes": len(data)})
        out["snapshots"].append(after)
        before = after
    top.wait()
    top_log.seek(0)
    out["top"] = top_log.read()
pathlib.Path("/tmp/nobby-idle-host.json").write_text(json.dumps(out, indent=2))
PY_IDLE
```

### Lange Vision-Prefills und konkurrierende Workloads

Fünf Web-Vision-Regressionen: 1024 × 1024 Testbild und 4000 Wiederholungen von
`neutral calibration record. ` als inertem System-Kontext; insgesamt **17.297
Prompt-Tokens** laut Upstream. First semantic:
`23,688; 25,047; 29,464; 35,376; 38,728 s`;
Median **29,464 s**, p95 **38,728 s**. Heartbeats: **5, 6, 6, 8, 8**, jeweils sofort
und danach ungefähr alle fünf Sekunden. Alle Antworten benannten Rot und Blau,
kein SSE-Fehler. Native Logs melden Prefill-Raten von
`774,1; 713,4; 603,5; 500,4; 455,9 Tokens/s`. Die zunehmende Dauer wurde nicht
als durch den Frontend-Patch verursacht interpretiert.

Später zeigte die Runtime-Diagnose eine aktive Video-Lease mit rund **221 s**
Alter und zwei wartenden Requests, ältester Wait rund **172 s**. Zusätzliche
Live-Prüfungen erreichten ihren 180-s-Client-Timeout. Diese Ergebnisse werden
nicht in Warm-Mediane aufgenommen. Der zusätzliche Benchmark-Client wurde
beendet; der Video-Job wurde nicht gestoppt. Nach dem Handoff blieb eine
Chat-Lease aktiv, während der Modellserver keine Inferenz mehr ausführte:
Die unten beschriebene Lock-Inversion erklärt die persistierende Blockade.
Ein gezielter Agent-Neustart lud die Lock-Korrektur und löste die alten
blockierten Threads; die Modellserver-PID blieb **79089**. Ein weiterer
gezielter Agent-Neustart war für den fünften, später gefundenen Read-only-Fix
nötig und beendete den eigenen weiterplanenden Regressionstest.

### Finale serielle Live-Regression nach dem Lock-Fix

Alle 18 Requests (Text/Web, Vision/Web, Vision/nativ, je ein erster Lauf
plus fünf Folgeläufe) lieferten Inhalt ohne Fehler. Der offene alte
Chrome-Tab war weiterhin aktiv. Der Modellserver blieb auf PID 79089.
Die neue Serie verwendet das eingecheckte Standardbibliothek-Werkzeug;
SSE-Timings werden am Abschluss des jeweiligen Frames erfasst.

| Messung | Vorher: Median / p95 | Finale Serie: Median / p95 |
| --- | ---: | ---: |
| Text, first semantic | 901,92 / 960,62 ms | 894.92 / 901.59 ms |
| Text, Gesamtdauer | 1038,52 / 1094,18 ms | 1024.89 / 1031.93 ms |
| Vision, first semantic | 926,91 / 958,03 ms | 922.54 / 940.35 ms |
| Vision, Gesamtdauer | 928,98 / 958,91 ms | 928.61 / 943.37 ms |
| Native Vision, Prefill | 166,89 / 168,94 ms | 166.694 / 169.403 ms |
| Native Vision, Decode | 30,443 / 30,619 tok/s | 30.184 / 30.846 tok/s |
| Gemeldeter MLX/Metal-Peak | 23,692 / 23,692 GB | 23.692 / 23.692 GB |

Der erste finale Textlauf nach dem Media-Handoff dauerte **34,969 s**.
Dabei griff der bestehende Text-First-Byte-Watchdog mit automatischer
Agent-Recovery (`chat_first_byte_timeout`, PID 14261 → 14909) und Retry.
Das ist ein einzelner natürlicher Wiederanlauf einschließlich Recovery,
kein reiner Modell-Cold-Benchmark. Der Modellserver blieb unverändert.
Die warmen Mediane sind praktisch wieder auf Ausgangsniveau. Aus den kleinen
Differenzen wird kein belegter Inferenzgeschwindigkeitsgewinn abgeleitet.

Finaler Testsatz: **1189 Python-Tests + 298 Subtests**,
**125 JavaScript-Tests**, alle bestanden. Eine bestehende
Starlette/httpx-Deprecation-Warnung bleibt; keine fehlgeschlagenen Tests.

Die identische ausdrücklich schreibgeschützte README-Anfrage schloss nach dem
fünften Fix in **21,498 s** mit `status: completed` ab. Genau ein erfolgreicher
`code_read`, **ein Modellcall**, korrekter Projektname `MLX nobby`, keine
`patch_required`-Schleife und keine Mutation. Vorher hatte dieselbe Anfrage
nach mehr als 180 s noch keinen Abschluss geliefert.

## Findings

### P0 — F1: Selbst auslösender Workspace-Observer, behoben

- **Symptom:** `GET /api/code/workspaces` dominiert `agent.log`; Agent und Docker
  verbrauchen CPU, obwohl kein Chat erzeugt wird. Loggröße bei Erhebung etwa 9,6 GB.
- **Root Cause:** `agent-task-mode.js` beobachtete alle Header-Attribute.
  `syncWorkspaceState()` schrieb nach jeder Antwort `data-agent-mode` und
  `data-workspace-task-active`; das löste denselben Observer erneut aus, auch
  bei unveränderten Attributwerten. Kein periodischer Workspace-Timer war nötig.
- **Beweis:** echtes Chrome-DOM, konstante Serverantwort: 92–95 Requests/s;
  produktiver Host 39.165–61.919 Workspace-Calls/min in fünf Fenstern.
  Ein macOS-`sample` zeigte unter anderem HTTP-/Python-Verarbeitung und
  `_io_FileIO_write`/Logging im ausgelasteten Agenten.
- **Einfluss:** CPU, HTTP-/Docker-Roundtrips, JSON-Parsing, wiederholte Datei-Lese-
  und Log-Schreibvorgänge; dauerhafte Serverabfragen bei ausgefallener API.
- **Risiko:** niedrig. Workspace-Auswahl/-Wechsel muss weiterhin synchronisieren.
- **Lösung:** Observer nur auf `data-active`, das der bestehende Header-Renderer
  bei Auswahl und Deaktivierung setzt. Eigene Marker nur bei Änderung schreiben.
  Fokus, Wiederanzeigen und Submission prüfen den Server weiterhin.
- **Before:** 92–95 Requests im kontrollierten Einsekundenfenster.
- **After:** genau ein Initial-Request; null periodische Requests der echten
  vollständigen Chat-Seite. Auswahl, Wechsel, Deaktivierung und Fehlerfälle getestet.

### P0 — F2: Invertierte Lease-/Modell-Locks, behoben

- **Symptom:** konkurrierende Agent-/Chat-Prüfungen warten trotz leerem
  Modellserver weiter; Lease-Diagnose zeigt aktive und wartende Chat-Threads.
- **Root Cause:** `MLXProvider.complete()` hielt zuerst `MODEL_RUNTIME_LOCK`.
  Die Rollenauflösung ruft `prepare_chat_runtime()` auf und wartet auf die
  Runtime-Lease. Der Streaming-Worker hielt zuerst die Lease und wartete auf
  denselben Modell-Lock. Der Image-Edit-Prompt-Helfer hatte dieselbe Reihenfolge.
- **Beweis:** begrenzte Zwei-Thread-Reproduktion des vorhandenen Providers:
  fünf von fünf Modell-Lock-Acquires des Chat-Threads laufen in den 250-ms-Timeout.
  Ohne Test-Abbruch/Lease-Freigabe bilden die Locks einen zyklischen Wait.
- **Einfluss:** vollständiger Stillstand statt bloß langsamer Inferenz;
  HTTP-Client-Disconnect beendet einen blockierten synchronen Lock-Wait nicht.
- **Risiko:** mittel. Die Lease umfasst jetzt auch Agent-Inferenz, dadurch kann
  korrekt serielles Warten auf andere schwere Workloads sichtbarer werden.
- **Lösung:** Produktionsfactory injiziert die vorhandene cancellable
  `chat_runtime()`-Lease in den Provider. Reihenfolge: **Lease → Modell-Lock**;
  Halten bis zum Ende des Modellaufrufs. Image-Prompt-Helfer verwendet dieselbe
  Reihenfolge. Cancellation beim Lease-Wait bleibt `ProviderError('cancelled')`.
- **Before:** 0/5 erfolgreich; medianer begrenzter Wait 250,907 ms.
- **After:** 5/5 erfolgreich; beide Threads schließen ab. Separate Regressionen
  für Produktions-Injektion, Cancellation und den Image-Prompt-Helfer.

### P1 — F3: Überlappende Workspace-Reads und Mehrfachinitialisierung, behoben

- **Symptom:** Fokus, Visibility, Observer und Submission können unabhängig
  Workspace-Reads starten; erneutes `mount()` registriert weitere Composer-Handler.
- **Root Cause:** keine gemeinsame In-flight-Promise, Sync-Flag wurde vor dem
  HTTP-Abschluss zurückgesetzt, `mount()` hatte keinen Idempotenz-Guard.
- **Beweis:** fünf kontrollierte Bursts mit je 20 Aufrufen: jeweils 20 Requests.
  Verhaltenstest prüft zusätzlich erneutes Mount und erneute Script-Auswertung.
- **Einfluss:** unnötige Calls/Handler und mögliche überholte Workspace-Anzeige.
- **Risiko:** niedrig. Kein TTL-Cache: spätere Submissions lesen frischen Zustand.
- **Lösung:** nur laufende Reads teilen; Fokus-/Visibility-Bursts zusammenfassen;
  echte Änderungen während eines Reads durch einen nachgelagerten Read beachten;
  Script und Mount einmal installieren.
- **Before:** 20 Requests/Burst; 11,1 ms Median bei 10-ms-Fake-Netzwerklatenz.
- **After:** ein Request/Burst, 95 % weniger Requests; 11,2 ms Median.
  Kein behaupteter Latenzgewinn. Spätere Reads und Fehler-Recovery bleiben frisch.

### P2 — F4: Unsichtbare Diagnose-Panels pollen weiter, behoben

- **Symptom:** Observatory alle 7,5 s und System Health alle 10 s auch bei
  geschlossenen Einstellungen. Observatory-Request kostet median 124,17 ms,
  p95 142,08 ms; Health-Kaltrequest etwa 124,24 ms, Cache-Hits 4,32–7,22 ms.
- **Root Cause:** Timer und Initial-Refresh waren nicht an Panel-/Tab-Sichtbarkeit
  gebunden. Snapshots fragen mehrere Dienste und macOS-Speicherinformationen ab.
- **Beweis:** echte geschlossene Chat-Seite: sieben Observatory- und fünf
  Health-Requests in 50 s. Der neue Verhaltenstest lädt die vollständigen Module.
- **Einfluss:** 14 automatische Diagnose-Requests/min pro unbenutztem Chat-Tab;
  vermeidbare DOM-Neuaufbereitung und native Status-Abfragen.
- **Risiko:** niedrig. Öffnen muss sofort aktuelle Werte anzeigen.
- **Lösung:** automatische Abfragen nur bei sichtbarem Dokument, sichtbaren
  Vorfahren und offenen Einstellungen. Sichtbarkeitswechsel aktualisiert sofort;
  periodische Updates und manuelle Refresh-/Self-Heal-Funktionen bleiben erhalten.
  Observer überwachen nur Vorfahren-Attribute, nicht ihre eigenen DOM-Updates.
- **Before:** sieben bzw. fünf Requests in 50 s.
- **After:** null bzw. null; Verhaltenstests prüfen sofortigen Refresh beim Öffnen,
  normale sichtbare Updates, Hintergrund-Tab, Busy-Deduplizierung und Cleanup.

### P1 — F5: Verneinter Änderungsauftrag führt zu erneutem Planen, behoben

- **Symptom:** Der Live-Read-only-Auftrag „Lies … README.md … Ändere keine
  Dateien“ liest die Datei erfolgreich, produziert danach wiederholt
  `patch_required: rejected` und erreicht den 180-s-Client-Timeout.
- **Root Cause:** Der Mutation-Guard findet das Wort `ändere`, während der
  vorhandene Read-only-Fast-Final-Helfer diese deutsche Verbotsformulierung
  nicht erkannte. Dadurch wurde der bereits vorhandene direkte Abschluss nach
  erfolgreichem `code_read` nicht genutzt.
- **Beweis:** Live-Progress nach dem Lock-Fix: ein erfolgreicher `code_read`
  plus mindestens acht `patch_required`-Rejections; jede erneute Planung löste
  Modellinferenz mit wachsendem, rund 9.200 Tokens großem Kontext aus.
- **Einfluss:** unnötige Modellcalls, etwa 16–22 s pro zusätzlicher Planung
  in den beobachteten Logs; der serverseitige Run läuft nach Client-Timeout
  bis zum vorhandenen Schrittlimit weiter.
- **Risiko:** niedrig. Nur zwei ausdrückliche Verbotsformulierungen ergänzt;
  keine generische Negationsheuristik und keine Änderung am Mutation-/Approval-Guard.
- **Lösung:** `aendere keine dateien` und `keine dateien aendern` im bereits
  vorhandenen, umlautnormalisierten Read-only-Fast-Final-Helfer erkennen.
  Positive Mutationsaufträge und explizite `file_analyze`-Aufträge bleiben
  außerhalb dieses Fast-Pfads.
- **Before:** Live-Client >180 s ohne Abschluss, wiederholte Modellplanung.
- **After:** Verhaltenstest schließt nach gelesener Datei mit genau einem
  Synthese-Call und null weiteren Planner-Calls ab; Live-Ergebnis oben.

## Weitere Befunde — bewusst nicht umgesetzt

| Priorität / Symptom | Root Cause und Beleg / Before | Einfluss und Risiko | Vorgeschlagene Lösung / After |
| --- | --- | --- | --- |
| P1: Vision-Bridge liefert Inhalt erst nach vollständiger Inferenz | `backend/app.py:generate_vision` nutzt `stream: false`; Bridge liest die komplette Antwort. First semantic entspricht näherungsweise Gesamtdauer. Lange Vision: bis 38,728 s, Heartbeats funktionieren. | Große Prefills bleiben dominant. Umbau beträfe den gerade reparierten Vision-Pfad; höheres Reliability-Risiko. | Separate Streaming-Änderung erst mit eigenem Routing-/Timeout-/Disconnect-Audit. Unverändert; kein After-Gewinn. |
| P1: zusätzlicher Router-Call bei normalem Chat | Fünf Vorher-Traces enthalten je `router.classify` und `chat.stream`; Klassifikation etwa 478–541 ms in den warmen Läufen. | Relevanter Anteil der Web-TTFT; Weglassen könnte Intent-/Tool-Routing verschlechtern. | Nur künftig mit belegtem, semantisch identischem Bypass/Cache untersuchen. Unverändert. |
| P2: Model-Scout-Startup mehrfach geladen | Chrome-Vorher-Fenster: je 36 Discovery-, History- und Sprachdatei-Requests; nachher weiterhin je 26. `model-scout-v3.js` plant Mounts über einen breiten DOM-Observer, lädt Copy vor dem Wiring-Guard. | Startup-HTTP-/DOM-Arbeit; unabhängiger Lifecycle-Befund. Änderungen müssen Console-Neuaufbau und Sprachwechsel erhalten. | Separater Mount-Single-flight mit Tests für Panel-Ersatz. Nachher-Burst bleibt dokumentiert; kein Fix behauptet. |
| P2: zwei Workspace-Datei-Reads je Listenrequest | Endpoint ruft `list_workspaces()` und `active_workspace()` auf, beide `_load()`. cProfile: 2000 `_load`/`read_text` bei 1000 Requests; fünf 1000er-Mikroserien median 0,06518 ms/Request. | Bei der Schleife verstärkt, nach deren Beseitigung klein. TTL-Cache birgt veraltete Auswahl-/Verfügbarkeitsdaten. | Ein konsistenter Snapshot wäre möglich; wegen geringer verbleibender Kosten nicht geändert. |
| P3: Config-File-I/O | Isolierte originale `load_config()` auf `~/.config/mlx-server/config`: fünf 1000er-Serien median 0,01883 ms/Call. | Kein relevanter belegter Hotspot; Caching erfordert sichere Invalidierung nach Modell-/Thinking-Änderungen. | Unverändert; keine Cache-Optimierung ohne neuen Befund. |
| P2: vollständige History-/Session-Aufbereitung | `saveSessions()` serialisiert und persistiert alle Sessions; bestehendes `performance.js` begrenzt Save-Bursts auf 500 ms und Content-Render auf einen Animation-Frame. In leeren Browsermessungen kein PUT-Sturm. | Große Histories können aufwendig sein. Kein repräsentativer großer Nutzerverlauf vermessen; Änderungen riskieren Recovery/Revision-Merge. | Erst mit synthetischen und repräsentativen großen Verläufen messen; unverändert, kein quantifizierter After. |
| P2: Vision-TTFT-/Generation-Metriken unvollständig | Bridge erhält nichtstreamende JSON-Antwort; Trace-TTFT `null`, `upstream_connect` umfasst Inferenz, `generation` kann nur lokale Body-/Parsing-Zeit enthalten. | Die kleine Trace-Generation-Zeit darf nicht als Modell-Decode interpretiert werden. | Native `timings` für Vergleiche nutzen; Instrumentierung später gezielt ergänzen. Vorhandene Metriken unverändert. |
| P2: RSS-/Zombie-/Leak-Verdacht | Neun erwartete Listener vorhanden; drei fremde Zombies mit Eltern 1149 bzw. Chrome 73959, keine belegten Nobby-Zombies. Agent-RSS nach Warmup während kurzer Messung stabil. | Kurzzeitmessung schließt langfristige Leaks nicht aus. Fremde Prozesse zu beenden wäre unbegründet. | Kein Kill/Cleanup und keine Leak-Behauptung; längere Soak-Messung bei erneutem Symptom. |

## Architekturprüfung und Grenzen

Die vorhandene Runtime-Lease serialisiert schwere Workloads über Prozess-Lock
und `flock`; das ist bei gemeinsamem Apple-Unified-Memory sinnvoll. Eine lange
Lease während Inferenz ist allein kein Fehler. **Zyklische Lock-Reihenfolge**
war dagegen ein konkreter Korrektheitsfehler. Die Lösung erhält Serialisierung
und bestehende Modellaktivierung, statt parallele schwere Inferenz zu erzwingen.

Text-SSE wird bereits zeilenweise weitergereicht. Der Agent nutzt eine Queue
mit maximal 64 Events und prüft Cancellation bei vollem Puffer. Vision verwendet
seit dem Ausgangsfix Worker-Threads für synchrone Vorbereitung sowie genau einen
laufenden Async-Read mit absoluten Inhaltsfristen. Es wurde kein zusätzlicher
belegter SSE-Puffer-Hotspot gefunden. Knowledge-/Memory-Arbeit und Profile-/Routing-
Calls bleiben eigenständige Kosten; Memory-Middleware besitzt bereits einen
begrenzten Hintergrund-Enrichment-Pfad. Kein pauschales Entfernen dieser Funktionen.

Neun erwartete Dienste waren erreichbar/listening. Der Audit wechselte kein
Modell, startete keine unbenötigten Modelldienste und änderte keine Quantisierung.
Für die Frontend-Validierung wurde ausschließlich der Webcontainer gebaut und
ersetzt. Gezielte Agent-Neustarts luden die Lock- und Read-only-Korrektur; bestehende
prozesslokale Agent-Runs/Approvals überleben einen solchen Neustart nicht.
Der Audit stoppte keinen aktiven Media-Job und löschte/trunkierte keine Logs.

## Regression und Review

- Neue Verhaltenstests: Workspace-Auswahl/-Wechsel/-Deaktivierung, keine
  Observer-Selbstschleife, 20-Read-Deduplizierung, nachgelagerter Refresh,
  frische Submission, Offline-Recovery, einmalige Composer-Handler.
- Neue Paneltests: keine versteckten Requests, sofortiger sichtbarer Refresh,
  Hintergrund-Tab, gleichzeitige Refresh-Auslöser und Observer-Cleanup.
- Neue Read-only-Tests: direkter Abschluss nach `code_read` für deutsche
  Schreibverbote; positive Mutationen und `file_analyze` behalten ihren Pfad.
- Neue Locktests: zwei konkurrierende echte Threads für Provider und
  Image-Prompt-Helfer, Produktions-Lease-Injektion und cancellable Lease-Wait.
- Benchmark-Tests unterscheiden Heartbeats/Sources von semantischem Inhalt,
  unterstützen mehrzeilige SSE-Daten und behalten Fehler/native Timings bei.
- Bestehende Provider-/Image-Payload-Tests nutzen explizite Fake-Leases, damit
  Transport-Unit-Tests keine realen Dienste oder produktiven Locks berühren.
- Vollständiger Python-/JavaScript-Testsatz, Python-/JS-Syntax,
  i18n-Audit, Shell-/JSON-Prüfungen, Docker-Build und `git diff --check`.
  Finale Anzahl und Live-Ergebnisse stehen im Abschnitt oben.
- Tests mit Coordinator verwenden eine eigene temporäre Lock-/State-Namespace.
  Keine Benchmark-Ausgaben oder temporären Logs werden committed.

```sh
PATH="$PWD/test-venv/bin:$PATH" \
MLX_RUNTIME_COORDINATOR_LOCK=/tmp/nobby-audit-tests.lock \
MLX_RUNTIME_COORDINATOR_STATE_DIR=/tmp/nobby-audit-tests-state \
test-venv/bin/python -m pytest -q
node --test tests/*.mjs
git diff --check
git status --short
git diff --stat
```

Finale Wiederholung nach dem Benutzer-Reload und der Berichtsergänzung:
**194 relevante Python-Tests + 81 Subtests** (Workspace, Agent, Provider,
Lock-Reihenfolge, Benchmark und Runtime-/Vision-Reliability) sowie alle
**125 JavaScript-Tests** bestanden. `git diff --check` ebenfalls ohne Befund;
die bestehende Starlette/httpx-Deprecation-Warnung bleibt unverändert.

Offen: ausreichend viele echte
Cold-Runs für eine Cold-p95 und ein längerer Memory-Soak. Diese Resultate werden
nicht als durchgeführt dargestellt. `docs/.last_sync_commit` bleibt unverändert.
