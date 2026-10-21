# Kontrollierter Cold-Vergleich 0.16.3 / 0.17.0: Ressourcenbefund

**Ergebnis: Beide Benchmarks wurden nicht gestartet.** Die unveränderte Ressourcenprüfung lehnt den Start aus zwei unabhängigen Gründen ab: zwei vorhandene VLM-Prozesse und weniger als 20 GiB geschätzt verfügbarer Speicher. Es gab keine Unloads, Prozesssignale, Dienststopps, Konfigurationsänderungen, Downloads oder GPU-Benchmarkläufe. Der Branch bleibt `feature/ltx-performance-lab-v017`; `main` wurde nicht verändert.

Die [Labordokumentation](LTX_PERFORMANCE_LAB.md) wurde zuerst vollständig gelesen. Messaufnahmen erfolgten am **21. Oktober 2026 um 11:32:02 und 11:33:19 Uhr Europe/Berlin**. Der aktuelle Bericht verwendet die zweite, vollständige Aufnahme; die Werte sind Momentaufnahmen und keine laufende Reservierung der Ressourcen.

**Maschinenlesbare Nachweise.**

- [Vergleichsergebnis und geplante Parameter](../.ltx-lab/diagnostics/20261021-113319/comparison.json)
- [Vollständige Ressourcenaufnahme einschließlich GET-Antworten](../.ltx-lab/diagnostics/20261021-113319/resources.json)
- [Erste Ressourcenaufnahme](../.ltx-lab/diagnostics/20261021-113202/resources.json)
- Je Prozess liegt im jeweiligen Diagnoseverzeichnis eine `vmmap-<PID>.txt`-Datei.
- Der ausgeführte, ausschließlich lesende Diagnosecode liegt lokal unter `.ltx-lab/diagnostics/resource-probe.py`.

Diese Artefakte liegen absichtlich im ignorierten Laborverzeichnis. Sie werden nicht automatisch veröffentlicht oder ins Repository aufgenommen. Das JSON enthält für beide Versionen `status=not_started_resources_failed`, keine Renderartefakte und `null` für sämtliche nicht gemessenen Benchmarkwerte.

**Systemspeicher und Pressure, zweite Aufnahme.**

| Messgröße | Wert | Bedeutung |
| --- | --- | --- |
| Physischer Speicher | 51.539.607.552 Bytes = **48 GiB** | `hw.memsize` |
| System-RAM belegt | 50.231.574.528 Bytes = **46,782 GiB** | Bestehende Labordefinition aus `vm_stat`, einschließlich inaktiver und komprimierter Seiten |
| Geschätzt verfügbar | 15.601.254.400 Bytes = **14,530 GiB** | Freie + inaktive + speculative Seiten, unveränderte Admission-Definition |
| Erforderliche Schätzung | **20 GiB** | Es fehlen gegenüber diesem Testschwellwert rund **5,47 GiB** |
| Compressor | 15.557.967.872 Bytes = **14,490 GiB** | Bereits physisch durch den Compressor belegte Seiten |
| Swap belegt | 14.423.812.997 Bytes = **13,433 GiB** | Bereits vor einem möglichen Benchmark vorhanden |
| Swapänderung während der zweiten Diagnose | **0 Bytes** | Zeitraum rund 2,54 Sekunden; keine Aussage über einen LTX-Lauf |
| Memory Pressure | **1 = normal** | `kern.memorystatus_vm_pressure_level` |
| `memory_pressure` Availability-Indikator | **60 %** | Eigenständige macOS-Schätzung; nicht identisch mit der Laborsumme verfügbarer Seiten |
| Thermik | Keine aufgezeichnete Thermal-/Performancewarnung | `pmset -g therm`; kein Temperaturmesswert |

RAM-belegt, geschätzt verfügbar und Compressor dürfen nicht einfach addiert oder voneinander abgezogen werden: Inaktive Seiten und unterschiedliche macOS-Bilanzierungsregeln überlappen. Normaler Pressure hebt die konservative 20-GiB-Bedingung nicht auf. Die höhere Availability-Schätzung von `memory_pressure` wurde ausdrücklich nicht benutzt, um den Laborcheck zu umgehen.

**Prozesse und Modellresidenz.** Physischer Footprint und Graphics-Mappings stammen aus `vmmap -summary`; dessen M/G-Ausgaben sind gerundet. RSS allein unterschätzt bei diesen Prozessen den GPU-/komprimierten Speicher erheblich. Footprints, Graphics-Mappings, RSS und systemweiten Swap nicht summieren.

| Rolle / Port | PID | Physischer Footprint | Graphics-Mapping `IOAccelerator` | Beobachteter Zustand |
| --- | --- | --- | --- | --- |
| Chat / 8000 | **89892** | **15,8 GiB**, Peak 15,9 GiB | **15,5 GiB** | Dark-Scarlett-27B-oQ4e geladen; `in_flight=0`, Requestqueue 0 |
| Router / 8040 | **69237** | **3,1 GiB**, Peak 4,0 GiB | **2,9 GiB** | Qwen3.5-4B-MLX-4bit geladen; `in_flight=0`, Requestqueue 0 |
| MuseTalk / 8070 | **802** | **9,8 GiB**, Peak 11,1 GiB | **9,2 GiB** | MPS-Modelle seit Prozessstart geladen, ein gecachter Avatar; keine belastbare Active-/Loaded-Telemetrie im Health-Vertrag |
| Agent / 8010 | 69125 | 80,6 MiB | Kein entsprechender großer Eintrag | Dienst aktiv |
| Embedding-Service / 8020 | 69326 | 36,7 MiB | Kein entsprechender großer Eintrag | Dienstprozess aktiv; keine Embedding-Inferenz angefordert |
| Speech / 8050 | 69349 | 141,4 MiB | Mapping 10,2 MiB; resident rund 4 MiB | ASR/TTS/Clone alle `loaded=false`, `active_generation=false` |
| Image-Service / 8030 | 69378 | 73,9 MiB | Kein entsprechender großer Eintrag | `loaded=false`, kein SDXL-Worker, kein aktiver Job |
| Video-Service / 8060 | 69429 | 42,3 MiB | Kein entsprechender großer Eintrag | Bereit, kein aktiver Job; kein LTX-Inferenzworker in der Prozessaufnahme |
| MLX-Serve / 11234 | 69452 | 10,0 MiB | Mapping 1088 KiB; resident 32 KiB | `/props`: `reason=no_model`, `active_bytes=8`, `peak_bytes=16` |

Zusätzlich war im allgemeinen Prozesscheck ein kleiner `multiprocessing.resource_tracker`-Hilfsprozess der Speech-Runtime sichtbar (PID 71763, Parent 69349, RSS rund 4,9 MiB). Er ist kein eigener Modellworker. Es wurden keine laufenden SDXL-, nativen LTX- oder LTX-Desktop-Generierungsprozesse gefunden. Die Dienstprozesse blieben erhalten.

Chat hatte seit seinem jüngsten Start noch keine Requests bearbeitet. Router meldete fünf abgeschlossene Requests und keine laufenden Requests. Das belegt Inaktivität nur zu den beiden Messzeitpunkten; es reserviert weder Chat noch Router gegen neue Anfragen. Während der ersten Prozessprüfung wurde ein bereits laufender normaler Chat-Start über `scripts/mlx start` sichtbar. Dieser wurde von dieser Untersuchung nicht ausgelöst.

**Metal-/GPU-Speicher: verfügbare und nicht verfügbare Messwerte.**

Die AGX-Treiberstatistik der zweiten Aufnahme meldet:

| Zähler | Bytes | GiB |
| --- | --- | --- |
| `Alloc system memory` | 33.721.270.272 | **31,405** |
| `In use system memory` | 1.005.830.144 | **0,937** |
| `In use system memory (driver)` | 0 | 0 |

Dies sind systemweite Treiberzähler mit eigener Semantik, keine prozesslokalen MLX-Allocatorwerte. Insbesondere ist `In use system memory` nicht die Summe geladener Modellgewichte. Die GPU meldete im zweiten Treibersnapshot 22 % Device Utilization; die VLM-Metriken meldeten gleichzeitig keine laufenden Inferenzrequests. OS-/andere GPU-Aktivität ist dadurch nicht ausgeschlossen.

Die Graphics-Mappings aus `vmmap` liefern eine zusätzliche prozessbezogene GPU-Speicherbilanz, aber ebenfalls keine exakten Werte von `mx.get_active_memory()` oder `mx.get_cache_memory()`. Diese aktuellen Allocatorzähler sind für die laufenden VLM- und MuseTalk-Prozesse über die untersuchten lesenden Statusendpunkte nicht verfügbar. Ein MLX-Import in einem separaten Diagnoseprozess würde nur dessen eigene Werte liefern und wäre hier irreführend; Code wurde auch nicht in produktive Prozesse injiziert. Router `/metrics` enthält lediglich einen **historischen** letzten Inferenzpeak von 3.828.825.772 Bytes; dies ist kein aktueller Allocator-Snapshot.

**Exakte Gründe für die Ablehnung.** Der ausgeführte `ltx_lab.telemetry.preflight()` liefert unverändert:

```json
{
  "allowed": false,
  "reasons": [
    "Competing LTX/VLM process present; services will not be stopped",
    "Less than 20 GiB estimated available memory"
  ],
  "competing_process_count": 2,
  "min_available_gib": 20
}
```

Die zwei direkten Prozessblocker sind **PID 89892 (Chat)** und **PID 69237 (Router)**. MuseTalk wird vom aktuellen argv-Filter nicht als VLM gezählt, ist aber ein großer zusätzlicher Speicherverbraucher. Sein Speicher darf nicht wegen des kleinen RSS oder eines erfolgreichen Health-GET als freigegeben angesehen werden.

Außerdem ist der Prozessguard strenger als eine Residenzprüfung: Er lehnt jeden `-m mlx_vlm server`-Prozess ab, selbst wenn ein Soft-Unload dessen Gewichte vollständig entfernt hat. Deshalb kann ein Entladen allein mit dem unveränderten Guard noch keinen Benchmark ermöglichen. Diese Grenze wurde nicht geändert; weder Speichergrenze noch Prozessprüfung wurden übersprungen. Ein späterer dienstbewahrender Ablauf müsste zunächst verlässlich leere, inaktive VLM-Runtimes erkennen können und weiterhin alle Speichergrenzen einhalten. Das ist eine gezielte Änderung der isolierten Admission-Logik, kein bereits vorhandener oder freigegebener Ausnahmeparameter.

**Vorhandene Freigabemöglichkeiten – keine davon aufgerufen.**

| Ziel | Vorhandener Mechanismus | Auswirkungen / Eignung |
| --- | --- | --- |
| Chat | `POST http://127.0.0.1:8000/unload` | Entfernt Modell-/KV-/Vision-Caches, beendet interne Generationworker und ruft GC/MLX-Cachefreigabe auf. Serverprozess und HTTP-Dienst bleiben bestehen. Nächste Inferenz benötigt erneutes Laden. Momentan sinnvollster Kandidat; tatsächlicher RAMgewinn erst nach Messung bekannt. |
| Router | `POST http://127.0.0.1:8040/unload` | Gleicher Soft-Unload-Vertrag, Server bleibt erhalten. Routerfunktion benötigt beim nächsten Request wieder Laden. Nur nach eigener ausdrücklicher Freigabe. |
| Speech | `POST http://127.0.0.1:8050/unload` | Löscht ungenutzte ASR-/TTS-/Clone-Referenzen und MLX-Cache; verweigert bei aktiven Requests mit HTTP 409. Bereits entladen, deshalb kein nennenswerter zusätzlicher Gewinn zu erwarten. |
| Image | `POST http://127.0.0.1:8030/unload` | Kann SDXL-Workerprozesse beenden und MLX-Serve-Bildmodelle entladen. Nicht generell prozessbewahrend. Aktuell bereits entladen; kein Eingriff erforderlich. |
| MLX-Serve | Modellbezogenes `POST /v1/unload-model` | Bereits kein Modell resident; kein nennenswerter Gewinn. `/props` wurde als Statuspfad ohne Cold-Load geprüft. |
| Video | `POST /runtime/mlx/reset` am Video-Service | Stoppt gegebenenfalls den Idle-LTX-Workerprozess. Kein reines Gewichts-Unload; aktuell ohnehin kein Worker gefunden. Nicht aufgerufen. |
| MuseTalk | **Kein Unload-Endpunkt im installierten Server** | Health enthält weder `loaded` noch `active_generation`. Der vorhandene Koordinator behandelt diese ältere Schnittstelle als `unload_supported=false` und gibt die rund 9,8 GiB nicht frei. Ein sicherer neuer Unload-Vertrag erforderte eine eigene Implementierung und Aktivierungsplanung. Ein Serverstopp ist unter der geltenden Vorgabe keine Option. |

Vor einem freigegebenen Chat-/Router-Unload müssen `in_flight` und Queue erneut geprüft und neue Aufträge währenddessen vermieden werden. Der VLM-Endpunkt besitzt im gelesenen Handler keine mit Speech vergleichbare explizite HTTP-409-Idle-Sperre. Seine internen Worker werden beendet; es handelt sich nicht um einen wirkungslosen Cache-Purge. Ein normaler Nobby-Video-Handoff ist hier kein zulässiger Ersatz: `runtime_coordinator.video_runtime()` verwendet für Chat `scripts/mlx stop`, das den LaunchAgent per `launchctl bootout` stoppt. Dieser Weg wurde nicht betreten.

`torch.mps.empty_cache()` oder `mx.clear_cache()` in einem neuen Prozess können die referenzierten Gewichte fremder Prozesse nicht entladen. Kein RAM-Purge, kein Swapreset und keine Erhöhung von Speicherlimits wurden vorgenommen.

**Geplanter kontrollierter Vergleich.** Identisch für beide Versionen: Q4-Pack, distilled two-stage, 1280×704, 121 Frames bei 24 FPS (tatsächlich 5,041667 s), Landscape-Label 16:9, Seed 42, 8+3 Schritte, Audio aktiviert, Low-Memory-/Low-RAM-Streaming, ein frischer Prozess je Version, ausschließlich sequenziell. Der eingefrorene Prompt ist der bestehende Sportwagen-im-Regen-Standardprompt und steht vollständig im JSON. Es wurde nicht behauptet, dass er der unbekannte Originalprompt des historischen 138,8-s-Laufs ist.

Parameterpräzisierung vor einem späteren Start: Das ausdrücklich genannte Profil `production-control` entspricht im implementierten Labor `LTX2_COMPUTE_DTYPE=float32`, Sparse aus. **„BF16 / Standard“ bezeichnet dort nicht dasselbe Profil.** Für explizite BF16-Berechnung existiert `bf16-baseline`. Ein Wechsel wurde nicht stillschweigend vorgenommen. Die Nichtausführung beruht bereits unabhängig davon auf den Ressourcen; vor dem tatsächlichen Vergleich muss die beabsichtigte Compute-Einstellung eindeutig feststehen.

| Vergleichswert | 0.16.3 | 0.17.0 |
| --- | --- | --- |
| Status | Nicht gestartet: Ressourcenprüfung fehlgeschlagen | Nicht gestartet: Ressourcenprüfung fehlgeschlagen |
| Gesamtlaufzeit / Stage 1 / Stage 2 | Nicht gemessen | Nicht gemessen |
| VAE / Audio / Muxing | Nicht gemessen | Nicht gemessen |
| Peak RAM / Metal / Swapzuwachs des Benchmarks | Nicht gemessen | Nicht gemessen |
| Warnungen / Fehler des Generierungspfads | Nicht ausgeführt | Nicht ausgeführt |
| Renderqualität / Medienartefakte | Keine Ausgabe, nicht bewertbar | Keine Ausgabe, nicht bewertbar |

**Erhalt der Produktivinstallation.** Nach der Diagnose stimmen HEAD, Git-Status sowie die zuvor erfassten Hashes von Lockfile, Projektdatei und venv-Konfiguration der produktiven LTX-Installation weiterhin mit `.ltx-lab/production-baseline.json` überein (`production_unchanged=true`). Kein produktiver Code und keine produktive Konfiguration wurden editiert. Die Untersuchung hat ausschließlich Statusdaten gelesen und Labor-/Berichtsdateien geschrieben. Für reine Diagnose und Dokumentation war kein erneuter GPU-/Integrationstest erforderlich.

**Nächster sicherer Schritt.** Zunächst über den gewünschten Compute-Pfad und den Umgang mit der prozessbasierten Guard-Grenze entscheiden. Ein tatsächlich freigegebener Gewichts-Unload sollte auf einen benannten Dienst begrenzt sein, danach Gesundheitszustand/PID, belegte Gewichte, RAM/Swap und Pressure erneut prüfen. Für weitere Dienste ist eine eigene Freigabe erforderlich. Solange der Guard fehlschlägt, bleibt die Benchmarkausführung gesperrt; ein Geschwindigkeits- oder Qualitätsurteil zwischen 0.16.3 und 0.17.0 wäre derzeit erfunden.
