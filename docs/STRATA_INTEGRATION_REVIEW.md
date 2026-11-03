# Strata → MLX-Nobby: selektive Übernahme (2026-11-02)

**Status:** Erste isolierte Mess-Infrastruktur implementiert, keine Runtime- oder UI-Defaults geändert.

## Entscheidung

Strata verwendet ggml/GGUF, CPU/GPU-Expert-Sharing, GPU-Expert-Cache, SSD-N-Gram-Lookups und eigenes MTP- bzw. Prompt-Lookup-Drafting. MLX-Nobby läuft nativ auf Apple Silicon mit MLX, DFlash2, einem exklusiven Runtime-Koordinator, Speicherschutz und bestehender Benchmark-/Observability-Infrastruktur. **Kein Portieren des Strata-Inferenzkerns.** Nicht vergleichbare Hardware- und Modellkonfigurationen machen Speedup-Aussagen aus der Strata-Dokumentation für MLX-Nobby nicht übertragbar.

## Kandidaten und Priorität

| Priorität | Strata-Idee | MLX-Nobby-Maßnahme | Freigabe |
|---|---|---|---|
| P0 | Hardware-/Modell-Fit vor Start | Bestehende RAM-/Swap-Watchdogs und Lease-Reserve mit **erklärbarem, read-only** Fit-/Peak-Speicherbericht ergänzen; nicht zusätzlich blockieren | Peak-Memory- und Swap-Nachweis für Chat/Video-Handoff; keine Regression der 90-%-Grenze |
| P0 | Automatischer Vergleich / Tuning | Reproduzierbarer A/B-Lauf über bestehendes `benchmark-chat-latency.py`; optionaler Strata-Vergleich mit `benchmark-strata-comparison.py` | Idle-Host, gleiche Profile, p50/p95, Tokenzahlen, Quality-Baseline, kein Default-Wechsel |
| P1 | Adaptive Drafter-Wahl (MTP / DFlash2 / Prompt-Lookup) | **Nur als MLX-Experiment** mit messbaren Akzeptanzraten und Fallback; bestehende DFlash2-/APC-/Hybrid-Experimente berücksichtigen, nicht parallel eine zweite Draft-Pipeline bauen | Vergleich von Korrektheit, TTFT, warmen Folgeturns, Code, Long-Context; kein Qualitätsverlust |
| P1 | Preset / Plan / Launch Diagnose | Read-only „Was passiert beim Modellstart?“-Preview (Peak-RAM, Context, model ID, handoff, geplante Dienste) vor *explizitem* Start | Kein automatischer Download, Stop oder Model-Switch |
| P2 | Prompt-Lookup-Drafting | Nur testen, falls MLX-Serve drafterseitige Integration ohne doppelte KV-Verwaltung ermöglicht | Messbarer Nettogewinn bei wiederholtem Code ohne Qualitätsabweichung |
| Nicht übernehmen | CPU/GPU-Expert-Sharing, GGUF-Engine, SSD-N-Gram-Tabelle | Nicht direkt auf Apple MLX übertragbar; separate Engine erhöht RAM-/Swap-Druck | Nur unabhängiger neuer Proof-of-Concept |
| Schon vorhanden | OpenAI-kompatible API, Observability, DFlash2/Benchmarks, RAM-Schutz | Bestehende Funktionalität verbessern statt duplizieren | — |

## Erster konkreter Schritt: lokaler A/B-Vergleich

`scripts/benchmark-strata-comparison.py` ist ein **opt-in**, auf Loopback beschränktes Hilfsprogramm; kein Produktionspfad. Es verwendet die drei bereits definierten Profile (short / long / coding) und die vorhandene Mess- und Validierungsfunktion aus `scripts/benchmark-chat-latency.py`.

```bash
python3 scripts/benchmark-strata-comparison.py \
  --mlx-url http://127.0.0.1:8000 --mlx-model YOUR_MLX_MODEL \
  --strata-url http://127.0.0.1:8080 --strata-model YOUR_STRATA_MODEL \
  --profile coding --samples 5 --output /tmp/strata-mlx-ab.json
```

Beide Dienste müssen **vorher** verfügbar sein; der Test kann durch API-Aufrufe ein Modell lazy-loaden. Strata muss nicht installiert werden, um MLX-Nobby weiter zu betreiben. Der Test läuft nicht automatisch. Er verändert keine Ports, Defaults oder laufenden Dienste. Er vergleicht grob Laufzeiten, **nicht** die Modellqualität. Bei unterschiedlicher Tokenisierung/Generationslänge oder ohne Server-Timing sind direkte Aussagen eingeschränkt.

### Nicht nachgemessen

Keine lokalen Apple-Silicon-Läufe, keine validierte Verbesserung von Tokens/s, TTFT oder Bild-/Videoqualität. Insbesondere sind Stratas dokumentierte 1,6–1,8x für dessen MTP auf dessen Engine **keine** MLX-Nobby-Prognose.

### Quellen

- Strata [README](https://github.com/Niko1221/Strata/blob/main/README.md), [Architektur](https://github.com/Niko1221/Strata/blob/main/docs/HOW_IT_WORKS.md), [Launcher/Tuning](https://github.com/Niko1221/Strata/blob/main/docs/TERMINAL_LAUNCH.md), [MIT-Lizenz](https://github.com/Niko1221/Strata/blob/main/LICENSE)
- MLX-Nobby [Performance Observatory](PERFORMANCE_OBSERVATORY.md), [Hybrid-Experimente](EXPERIMENTAL_HYBRID_APC_DFLASH.md), [Runtime-Leases](RUNTIME_LEASE_DIAGNOSTICS.md), [Benchmarks](../scripts/benchmark-chat-latency.py)

Die Implementierung übernimmt Ideen und API-Nutzung, keinen fremden Engine-Code.
