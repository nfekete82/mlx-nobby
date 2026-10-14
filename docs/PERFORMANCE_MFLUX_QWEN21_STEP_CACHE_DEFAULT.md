# Osaurus Qwen-Image-2.1 Edit: schneller Step Cache als Voreinstellung

## Reale Messung (M5 Max, 48 GB)

Kontrollierter ABBA-Vergleich, gleiches Quellbild, Prompt und Seed,
1024×1024 Pixel, 40 Steps, Guidance 1.0, KV Cache an:

| Lauf | Step Cache | Dauer |
|---|---|---:|
| 1 | aus | 87,48 s |
| 2 | an | 46,08 s |
| 3 | an | 48,78 s |
| 4 | aus | 98,50 s |

Median aus 92,99 s; Median an 47,43 s (**−48,99 % Laufzeit**).
Der Anwender hat die Ausgabe als *fast identisch* eingeschätzt.
Das ist eine subjektive visuelle Sichtprüfung, keine
pixelgenaue oder garantiert qualitätsneutrale Aussage.

## Verhalten

- **Nur** Built-in-Modell `mflux-osaurus-qwen-image-2.1-edit`:
  `step_cache_default=True`, sobald die Registry den neuen
  Built-in-Standard übernimmt.
- Andere MFLUX-, Qwen-, FLUX-, SDXL- und MLXGen-Modelle unverändert.
- Die Option ist im bestehenden Chat unter **Bildeinstellungen → Modelle →
  Qwen Image 2.1 Edit · Osaurus 4-bit** als Checkbox sichtbar.
  Zum Zurückschalten Checkbox deaktivieren und **Konfiguration speichern**.
- Explizit angeforderte Bearbeitungen mit `use_step_cache=false`
  behalten Vorrang. `use_step_cache=true` funktioniert auch bei global
  abgeschalteter Voreinstellung, sofern die installierte CLI das unterstützt.
- Explizites `use_kv_cache=false` verhindert die automatische Aktivierung
  von Step Cache. Aus Sicherheitsgründen überschreiben wir das nicht.
- Unterstützt die lokale MFLUX-CLI keinen `--use-step-cache`-Schalter
  oder keinen `--use-kv-cache`-Schalter, bleibt der alte Laufweg
  automatisch erhalten. Eine **explizite** Anforderung eines nicht
  unterstützten Schalters wird weiterhin als inkompatibel gemeldet.
- Der getestete Cache-Schwellenwert bleibt MFLUX-Standard `0.12`.
  Auflösung, Sampling-Schritte, Quantisierung, Seed, Guidance, Modelle,
  Eingabebilder und sonstige CLI-Argumente werden nicht verändert.

## Rollout / Rücknahme

Nach grünem Review/CI den PR mergen, `~/mlx-web` per
`git pull --ff-only origin main` aktualisieren; den Images-Dienst
**nur im Leerlauf** neu starten:

```bash
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
mlx agent restart
```

Die Bildmodelle bleiben wie zuvor **opt-in** / nur bei vorhandenen
Gewichten aktiviert. Beim ersten Laden der vorhandenen Registry sorgt
die eingebaute Canonicalization dafür, dass das neue Osaurus-Feld
sichtbar wird. Ein später explizit ausgeschalteter Schalter wird
bei weiteren Registry-Migrationen respektiert.

Für vergleichbare Kontrollmessungen weiterhin das opt-in
`scripts/benchmark-qwen21-step-cache.py` verwenden.
**Dieser PR startet selbst keine Bildjobs.**

## Sicherheitsgarantien

Keine Änderung am globalen 90-%-RAM-Admission-Guard,
20-GB-Reserveprinzip, isolierten Bildprozess mit 24-GiB-RSS-Budget,
Timeouts, Cancellation und bestehenden Ressourcensperren. Das Modell
bleibt wie bisher pro Auftrag im separaten Subprozess.
