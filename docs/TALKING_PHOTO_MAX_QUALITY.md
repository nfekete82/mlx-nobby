# Talking Photo: Maximale Videoqualität (30+3)

## Qualitätsstufen

| Einstellung | API `engine` | Backend | Stage 1 | Stage 2 |
| --- | --- | --- | ---: | ---: |
| Schnell | `ltx-distilled` | LTX A2V Distilled | 8 | 3 |
| Hohe Qualität | `ltx` | LTX A2V Classic | 15 | 3 |
| Maximal (experimentell) | `ltx-max` | LTX A2V Classic | 30 | 3 |

**Maximal** ist eine erhöhte Sampling-Schrittzahl im vorhandenen Modell, **kein**
Wechsel auf Q8 oder höhere Pixelauflösung. Die Bildabmessungen werden weiterhin
von `target_dimensions` begrenzt (Porträt 512×704, Querformat 704×512, quadratisch
640×640); die tatsächlich ausgegebene Auflösung hängt vom internen LTX-Raster ab.

Die längere Berechnung kann Detail-/Bewegungsqualität beeinflussen, garantiert
aber **keine** bessere Gesichtstreue, Lip-Sync oder Schärfe. Die neue Option
bleibt bewusst *opt-in*; bestehende Nutzer erhalten weiterhin Distilled,
oder ihre gespeicherte 15+3-Auswahl.

## Technische Umsetzung

- API nimmt ausschließlich `ltx-distilled`, `ltx`, `ltx-max` an;
  beliebige freie Schrittzahlen werden **nicht** akzeptiert.
- `ltx-max` ruft denselben Classic-Renderer mit
  `--stage1-steps 30 --stage2-steps 3` auf.
- `stage_1_steps`, `stage_2_steps` und `engine` stehen in Jobmetadaten
  und Diagnostik. Für Longform bleibt die Einstellung auch pro Segment erhalten.
- Browser speichert den zuletzt gewählten Modus im vorhandenen
  `mlxTalkingPhotoQualityEngine`-Schlüssel; bei nicht verfügbarem Storage
  oder unbekanntem Wert ist Distilled der Fallback.
- Talking Photo nutzt weiterhin die **separat konfigurierte LTX-Runtime**
  des Agent-Diensts, sofern keine entsprechende Umstellung erfolgt.
  Die Video-Runtime 0.18.0 unter Port 8060 wird dadurch **nicht** verändert.

## Validierung

1. CPU-Tests für API-Schema/Dispatch, Renderer-Argumente,
   sichere Preset-Validierung, Kurz- und Longform, UI und Speichern.
2. macOS GitHub Actions Python/Node, Docker-Validierung und Chromium.
3. Auf dem Mac in Talking Photo ein kurzes eigenes Porträt bei identischem Text,
   Seed und Stimme mit `ltx` (15+3) und `ltx-max` (30+3) erzeugen.
   Ausgaben visuell auf Identität, Mundbewegung und Bildartefakte vergleichen.
   Danach Peak RAM/Swap/Metal und Laufzeit prüfen.

Der Produktiv-Änderung ist eine **UI- und Backend-Preset-Funktion**, kein
automatisches Modellupdate. Bei Performance-Problemen zurück auf
„Hohe Qualität“ oder „Schnell“ schalten.
