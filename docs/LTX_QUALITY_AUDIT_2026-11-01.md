# LTX-2.5: Gesichtsqualität, Ursachen und lokale Integration

Testdatum **2026-11-01 CET**, Apple M5 Max / 48 GiB Unified Memory.
Branch `feat/ltx-quality-audit-20261101`, Basis `ef7b43e9` aus Draft-PR #392.
**FULL bleibt Standard. Keine natürliche Gesichtsverbesserung durch MINIMAL
nachgewiesen; keine automatische Freigabe oder Änderung der Inferenzdefaults.**

## Vergleichbarkeit und Budget

Die gelieferten FULL-/INITIAL_OFF-Videos stammen **nicht** vom angegebenen
Originalfoto. Das wurde anhand gespeicherter Jobs und tatsächlicher Bildbytes
verifiziert. Die beiden Referenzuploads haben verschiedene Dateinamen, aber
identische Bildbytes und Pixel. Ihr längerer Prompt unterscheidet sich ebenfalls
vom angegebenen Originalprompt. Beide Gruppen werden getrennt bewertet.

| Gruppe | Ausgangsbild | Datei-SHA256 | Prompt-SHA256 |
| --- | --- | --- | --- |
| Original | 1097×1434, `65fcb5f594e4.png` | `4296d2d80c753633525d6dded18d3d7d95fa876585ca894273c6d2b0273e17d6` | `390aa121ffc4ea2da6f62ca3ea6b1227209936ac08cc2f73de406036e902e4c1` |
| Referenz | 580×800, `c215160edd8e.png` / `156836c50d5d.png` | `0f53aad73356d2e3615e4b20097f8142c9240a87c08930259f8bccf704a07742` | `40f0db3e16c875ce8dc3526326730863ddc1c2e59603c14e3861744f719f4c55` |

Neue FULL/MINIMAL-Originaljobs unterscheiden sich im gesamten Payload nur in
`face_guidance`. Dasselbe gilt für Referenz-FULL/MINIMAL. Referenz-INITIAL_OFF
verwendet den anderen, bytegleichen Uploadnamen. Alle Videos: Standard-Profil,
704×1280 Hochformat, 24 FPS, Seed 0, 8+3 native distilled Schritte pro Fenster,
6+2+2 s Rolling, 25 Frames Video-/Audiokontext, `contain`, ursprüngliche
CRF-18-Bildkonditionierung. Keine zusätzliche negative Textführung.

| Fall | Job | Lokale MP4 unter `~/.config/mlx-web/videos/` | Generierung |
| --- | --- | --- | ---: |
| Original FULL, neu | `eaa599eb9c44f61aafd735bc` | `ed9ace71c353194b897ff259.mp4` | 432,724 s |
| Original MINIMAL, neu | `54922fc180e98e3d2ed148af` | `4377033c7cf8d80a9655b161.mp4` | 443,190 s |
| Referenz FULL, vorhanden | `06a5e54fa06a1a8f44854d8d` | `135299cdf68b03aa7cc5d4df.mp4` | 413,125 s |
| Referenz INITIAL_OFF, vorhanden | `a9f6d6aa0141c02dded76e66` | `9078b2b7580404e272bbd5f7.mp4` | 429,881 s |
| Referenz MINIMAL, neu | `aa792f485fe23d2824e54e1b` | `9e30f5a855891ddf1becf6ea.mp4` | 438,735 s |

**Drei** neue vollständige Videos, keine Generierungswiederholungen; das vierte
Video wird nicht verbraucht. Zusätzlich zwei Ein-Frame-VAE-Diagnoseversuche:
ein Abbruch vor VAE-Gewichteladen und eine erfolgreiche volle Rekonstruktion.
Keine 6-s-Diffusionsproben oder weiteren GPU-Experimente. Ein anfänglicher
Admission-Check wartete wegen einer belegten Lease vor dem ersten POST; das war
kein eingereichter oder fehlgeschlagener Render.

## Nativer Vergleich: 0–6 / 6–8 / 8–10 Sekunden

CPU Vision untersucht jeden der 241 nativen Frames. Die Abschnitte enthalten
Frames 0–144, 145–192 und 193–240. Durch das inklusive Anfangsbild liegen die
ersten neuen Frames tatsächlich bei 6,041667 und 8,041667 s. Nachfolgend stehen
**Längen beidseitiger Niedrigöffnungs-Kandidaten in Frames**, nicht validierte
Blinkzahlen. Der bestehende Grenzwert ist 45 % der jeweiligen Segment-p90-
Augenöffnung. 24 Frames entsprechen einer Sekunde.

| Fall | 0–6 s | 6–8 s | 8–10 s |
| --- | --- | --- | --- |
| Original FULL | **41 / 21** | 3 | 1 / 7 |
| Original MINIMAL | **44 / 14** | **17** | 5 |
| Referenz FULL | 5 / 5 / 4 | 9 | 1, am Videoende |
| Referenz INITIAL_OFF | 6 / 4 / 4 | **15** | 6 / 5 |
| Referenz MINIMAL | 9 / 4 / 5 / 2 | 6 / 4 | 5 / 4 |

Die JSON-/HTML-Auswertung enthält außerdem eine einheitliche Schwelle über die
ganze Zeitachse und die erste beobachtete Wiederöffnung. Deshalb können deren
Fenster geringfügig von der Segmenttabelle abweichen. Grenzüberschreitende
Intervalle werden dort durchgehend betrachtet, offene Enden ausdrücklich markiert.

**Original, 0–6 s:** FULL schließt die Augen sichtbar ungefähr bei 1,0–2,7 s
(41 Frames = 1,708 s), lange vor Extend. Ein weiterer Schluss bzw. starkes
Zusammenkneifen begleitet das sich entwickelnde breite Lächeln. MINIMAL verlängert
den ersten Schluss auf 44 Frames = 1,833 s, obwohl der spätere Kandidat kürzer
wird. Das Lächeln bleibt geschlossener und weniger ausgeprägt. Eine geringere
Bewegungs-/Residualmetrik wäre hier kein überzeugender Qualitätsgewinn.

**Original, 6–8 s:** Kontinuierliche Kopfneigung und Mimik bleiben in beiden
sichtbar; MINIMAL fügt einen wesentlich längeren Schluss bei Frames 166–182
hinzu (0,708 s). FULL zeigt in diesem Abschnitt einen kurzen Kandidaten.
**8–10 s:** Beide haben kurze Öffnungsänderungen. Die exakten nativen Übergänge
144→145 und 192→193 zeigen keinen deutlichen Gesichtsreset. Kleine Augen-/Iris-
und Texturänderungen bleiben; Bildproportionen ändern sich auch gewünscht durch
Lächeln und Pose. Das ist keine biometrische Identitätsfreigabe.

**Referenz, 0–6 s:** FULL zeigt kurze Blinzelkandidaten und einen kontinuierlichen
Ausdruck. INITIAL_OFF liefert kein eindeutig besseres Gesamtbild. MINIMAL
verlängert den ersten Kandidaten von 5 auf 9 Frames und verändert die Mimik.
**6–8 s:** INITIAL_OFF schließt länger als FULL; MINIMAL hat zwei kürzere
Intervalle. **8–10 s:** MINIMAL hat zwei weitere Schließfolgen, während FULL in
den geprüften Folgen einen gleichmäßigeren, weiterentwickelten Ausdruck zeigt.
Keine Variante belegt einen relevanten, durchgängigen Vorteil bei Augen,
Kopfbewegung, Mimik, Farbe und Übergängen zugleich. Die vom Nutzer bevorzugte
FULL-Referenz wird nicht aufgrund einer Einzelmetrik abgewertet.

Alle Frames enthalten eine einzelne hinreichend konfidente Gesichtsdetektion.
Das beseitigt keine Landmarkfehler. Pupillenänderungen werden nur zwischen
benachbarten Frames mit Konfidenz ≥0,8, Augenöffnung ≥0,15 und vorhandener
Pupillendetektion berechnet. Es gibt keine Iris-Segmentierung und keine
Ground-Truth für Blickrichtung. Vision-Yaw/Roll ist hier grob quantisiert;
kontinuierliche Augenlinienwinkel und Gesichtsmittelpunktbewegung werden separat
gezeigt. Mimik-/Poseänderungen werden nicht automatisch als Identitätsfehler gezählt.

## Nachgewiesen, eingegrenzt und offen

| Befund | Evidenz und Grenze |
| --- | --- |
| Langer Lidschluss entsteht vor Extend | Nativer FULL-Originalverlauf und MINIMAL-Gegenprobe. Rolling ist als alleinige Ursache ausgeschlossen. |
| Gesichtstext beeinflusst Bewegung/Mimik | Gleiche Payloads bis auf FULL/MINIMAL; Ausdruck und zeitlicher Verlauf ändern sich. Kein Nachweis, dass jedes detaillierte Augenwort generell schädlich ist. |
| Räumliche VAE-Rekonstruktion verliert Details | Isolierte volle Ein-Frame-Rekonstruktion mit identischer Eingabe-ROI, ohne Denoiser und finalen Codec; siehe unten. |
| Halbaufgelöste Stufe hat weniger Bildinformation | Native Quellen: Start bei 352×640, danach gelernte Latent-Vergrößerung und Refinement auf 704×1280. Der isolierte Anteil an Augenfehlern ist **nicht gemessen**. |
| Extend rekodiert erzeugten Kontext | Native `extend_distilled.py` kodiert Video bei halber und voller Auflösung und den passenden Ton erneut. Daraus folgt ein möglicher Driftpfad; dessen isolierte visuelle Stärke ist **nicht bewiesen**. |
| Keine offensichtlichen harten Gesichtsresets an den geprüften Grenzen | Native Join-Paare und dense Folgen. Kein Beweis für perfekte kontinuierliche Identität. |
| Quantisierung/Sampling kann Details begrenzen | Architektur plausibel; kein kontrollierter BF16-/anderer-Scheduler-Vergleich. Daher Hypothese. |

Die frühere CRF-0-Probe aus dem [Ursachenbericht](LTX_I2V_CAUSE_ISOLATION_2026-10-31.md)
verbesserte die Pixelvorverarbeitung, beseitigte den frühen Lidschluss aber nicht.
Sie wird nicht wiederholt. Weder CRF 0 noch MINIMAL oder INITIAL_OFF wird als
Standard übernommen. Keine Augenrekonstruktion, Face-Restoration, Frame-Blends,
Farbanpassung oder zusätzliche posebindende Fotoanker.

### Isolierte VAE-Probe

Das unveränderte Original wurde wie im Provider als verlustfreies 704×1280-
Contain-PNG vorbereitet: Inhalt etwa 704×920, oben/unten je etwa 180 Pixel Rand.
Native Bildvorverarbeitung komprimiert bei CRF 18, resizt bilinear und normalisiert
zu BF16. Genau dieser VAE-Eingabetensor wird als `input.png` gespeichert.
Native ImageConditioner-/Conv-Decoder-Blöcke laden dieselben lokalen Gewichte
wie die Pipeline, jeweils nacheinander. Die Rekonstruktion wird direkt als PNG
exportiert; es gibt weder Denoising noch einen finalen H.264-Schritt.

Erfolgreich bei 704×1280: Latent `[1,128,1,40,22]` BF16,
**0,789 s** Worker inklusive Laden/Encode/Decode/Export, nativer Metal-Peak
**4,799 GiB**. Im festen nativen Gesichtsrechteck: Luma-SSIM **0,9520**,
MAE **1,8604**, Laplacianvarianz **75,88→63,16**. Sichtbar glattere Textur und
feinere Augendetails; die Augen bleiben offen. Dies misst Rekonstruktionsverlust,
keine Verbesserung der generierten Qualität. Die Ein-Frame-Probe kann weder
zeitliches VAE-Verhalten noch die Ursache des mehrsekündigen Lidschlusses erklären.

Die zuerst versuchte Halbprobe brach beim PNG-Export wegen einer falschen
`.clip()`-Array-API **vor Encoder-/Decoder-Laden** ab. Korrigiert zu `mx.clip`,
mit einem winzigen nativen Tensor geprüft; anschließend nur noch die volle Probe.
Keine halbaufgelöste Rekonstruktion und kein exakter Wall-Zeitwert des Fehlversuchs
werden behauptet. Encoder-/Decoder-Hashes und Messwerte:
[VAE-Evidenz](ltx-quality-audit-evidence/vae-reconstruction.json).

### Latent Carry: Entscheidung für diese Runde

Kein experimenteller Carry-Modus wird hinzugefügt: Das dominante Originalproblem
ist bereits im Initialsegment vorhanden. Der bestehende Rolling-Fallback und
seine Checkpoint-/Cancel-/Resume-Pfade bleiben unverändert.

Technisch ist Carry mit zusätzlicher Adapterarbeit denkbar. Native `_Carry`
benötigt **halbe und volle** Videotokens plus Audiotokens. Ein nachträgliches
räumliches Verkleinern voller Latents ersetzt nicht das korrekte Stufe-1-Signal.
Beide Stufen pinnen Kontext; Ton muss zu Frame-Rate, Tokenanzahl und zeitlichem
Ursprung passen. Latents dürfen nicht unabhängig vom passenden Audiokontext
fortgesetzt werden. Künftige Checkpoints müssten Runtime/Modell/Adapterversion,
beide Formen/Dtypes, Ton, Zeitbasis, Seeds/Parameter und Inhalts-SHA256 binden.

Die kleinen Kontext-Tensoren allein sind nicht das Speicherproblem: Modellgewichte,
Denoising-/VAE-Aktivierungen und Materialisierung dominieren. Ein späterer Versuch
müsste Grenzen vor dem Laden prüfen, Carry auf Disk schreiben, alte Zustände
freigeben und denselben Memory-Watchdog verwenden. Die gepinnte Runtime wird
für diese unbewiesene Hypothese nicht verändert. Zusätzliche Originalbildanker
könnten Pose und Mimik einfrieren und erhöhen den Kontext; keine Freigabe ohne
isolierten Bewegungsvergleich.

## Ganze Pipeline, Profile und Technikvergleich

Native Runtime **0.18.0**, sauberer HEAD
`b82b97e3d000e01361f8cfcb745244b15b89a521`; lokales
`dgrauet/ltx-2.5-mlx-q4`, LTX-2.5 distilled 22B, Q4/group64-Linear-Gewichte.
Keine Downloads oder Änderungen an Modellen, Runtime und Sigma-Tabellen.
Alle normalen Profile verwenden dieselben nativen 8+3 ancestral Schritte.
CFG/STG sind kein wirksamer Regler dieses distilled-Pfads. Native Generate-NAG
mit negativem Prompt ist nicht gleichbedeutend mit Unterstützung im Extend-CLI;
dieser lehnt negative Prompts/CFG/manuelle Schrittzahlen ab. Deshalb keine
scheinbar wirksamen globalen Expertenregler.

Der native optionale Diffusion-VAE-Decoder ist für Generate vorhanden, wird aber
im installierten Extend-CLI nicht entsprechend konfiguriert. Ein globaler
Rolling-Schalter dafür wäre ungetestet und inkonsistent. Er bleibt aus.

Rolling transportiert Zwischenvideo als CRF 0/yuv420p und Ton als ALAC;
die finale H.264-CRF-10/AAC-Ausgabe entsteht einmal mit expliziten Frame-/Sample-
Clocks. Native Generierung selbst verwendet weiterhin ihren eigenen Codec.
Das frühere [Technik-A/B](LTX_QUALITY_REPORT_2026-10-31.md) bewies korrigierte
Containerzeiten und Zwischenpixel-Erhaltung, keine perfekte Gesichtsqualität.

Alle fünf aktuellen Videos: **241 Frames, 704×1280, 24 FPS, 10,041667 s**, A/V-
Start und Enddifferenz **0**, keine exakten Nachbarduplikate oder PTS-Anomalien.
Das ist keine semantische Lip-Sync-Messung. Es gibt keine Sprachreferenz in dieser
Runde; Talking Photo und T2V erhalten keine neue Qualitätsfreigabe.

| Metrik | Original FULL | Original MINIMAL | Referenz FULL | Referenz MINIMAL |
| --- | ---: | ---: | ---: | ---: |
| Join 144→145 Luma-SSIM | 0,987769 | 0,982718 | 0,982178 | 0,982954 |
| Join 192→193 Luma-SSIM | 0,991920 | 0,991356 | 0,966017 | 0,963351 |
| Median registrierter Gesichts-Luma-MAE | 2,764 | 2,649 | 3,208 | 3,447 |
| Median benachbarter Gesichtsregion-Delta-E76 | 0,583 | 0,571 | 0,870 | 0,768 |

SSIM verwendet das vorhandene explizite 282×512-Analyseraster; Frames/Crops und
Duplikathashes bleiben nativ. Translation-Registrierung verwendet normalisierte
128×128-Luma-Ausschnitte, keine Optical-Flow- oder Identitätsschätzung. Farbpatches
sind approximative Wangen-/Stirnregionen, keine validierte Hautsegmentierung.
Kleinere Residuen/Farbänderungen können weniger Bewegung bedeuten. Kein
zusammengesetzter Qualitätsscore und keine automatische Rangfolge.

## Implementierte Integration und Tests

- Erweiterung der vorhandenen CPU-Benchmark-Pipeline: dense Augen/Pupillen,
  Proportionen, Bewegung/Registrierung, Farbe, Unsicherheit, Zeitbasis und
  SHA-gebundene Wiederverwendung. `face_guidance` wird im Basisbericht erfasst.
- Lokales synchrones HTML mit fünf Videos, gemeinsamen Steuerelementen,
  nativer Framewahl, Originalen, Zeitreihen und Segment-/Grenzansicht:
  **`artifacts/ltx-quality-20261101/comparison/index.html`**.
  Private Medien/Geometrie werden nicht committet.
- Explizites VAE-Diagnoseskript mit Pin-Prüfung, ausschließlich lokalen
  Gewichten, Health-/Queue-Prüfung, exklusiver Lease, unverändertem 20-GiB-
  Load-Reserve, Prozess-Ownership und Zwei-Sekunden-RAM-/Swap-Watchdog.
- UI zeigt reale Ausgabegrößen: Schnell 1024×576, Standard 1280×704,
  Maximale Qualität 1920×1088, jeweils im Hochformat getauscht. Vorschau nur
  T2V, 384×256 / 8 FPS / 1+1 Schritte. Keine 4K-Behauptung oder nachträgliches
  Ausgabe-Upscaling. Das interne gelernte Latent-Upsampling ist Teil der nativen
  Zweistufen-Generierung.
- UI: validierter Seed 0…2147483647, Fortsetzung Auto oder expliziter Rolling-Test.
  Rolling begrenzt auf 10 s / 540p oder 720p; inkompatible 1080p/Vorschau gesperrt.
  9 s bei 1080p und 30/60 s nutzen bestehende RAM-sichere Segmente, andere lange
  Längen die bisherige automatische Fortsetzung. Keine neue 1080p-GPU-Abnahme.
  Gesichtstextführung liegt im Expertenbereich und bleibt experimentell.

| Prüfung | Ergebnis |
| --- | --- |
| Geforderte Rolling/Segmented/I2V-Python-Suiten | 44 bestanden |
| Erweiterte Provider/Long/Runtime/Memory/Lifecycle inkl. VAE-Schutz | 157 bestanden, 15 Subtests; eine bestehende Starlette-Deprecation |
| CPU Benchmark-/Gesichtsdiagnostik im vorhandenen Image-Venv | 11 bestanden |
| Desktop/Mobil: Seed-Validierung, opt-in, Raster und Fortsetzung | 3 bestanden |
| JS Videojob, Medienqualität, Playback-Preservation, Edit-Recovery | bestanden; Playback 2 und Recovery 5 Einzeltests |
| Privates HTML mit fünf echten Videos | synchrones Playback, sieben Seeks und native Framewahl bestanden |

Ein bestehender Medienqualitäts-JS-Test erwartete veraltete Dauerlisten ohne
60 s/1080p-9 s; auf die bereits unterstützten Listen korrigiert. Die bekannten
allgemeinen Collection-Fehler (`mlx_agent`, fremde untracked LTX-Lab-Telemetrie)
und HTTP-501-Probleme der allgemeinen Browserfixture werden nicht als gelöst
behauptet. Fokussierte Browserprüfungen liefern nur den fehlenden Discovery-
Endpunkt vor Navigation nach und behalten strikte Konsolenprüfungen.

## Ressourcen, Grenzen und Abnahme

| Neuer Render | Beobachtete Samples / Abdeckung | Minimum aktiv verfügbar | Swap Anfang→Ende |
| --- | --- | ---: | ---: |
| Original FULL | 113 / letzte 225,9 s; Beginn 207,6 s nach Start | 66 % | 4,53→4,50 GiB |
| Original MINIMAL | 221 / 443,8 s | 57 % | 4,49→4,44 GiB |
| Referenz MINIMAL | 219 / 439,8 s | 54 % | 4,44→4,43 GiB |

Alle beobachteten Druckwerte normal. Die Gesamtmessung einschließlich Chat-
Handoff erreicht bei MINIMAL zunächst 41/40 %; das ist nicht der aktive
Video-Peak. FULL besitzt keinen vollständigen Peak-Monitor. Zwei-Sekunden-
Samples können kurze Peaks verpassen; die VAE-Probe dauerte unter einer Sekunde,
ihr nativer Metal-Peak wird deshalb separat angegeben. Swap sank insgesamt;
keine Grenze wurde angehoben oder abgeschaltet. Die CPU-Auswertung lief teils
während der Videojobs; Laufzeitdifferenzen sind kein sauberer Speed-Benchmark.

**Abnahmeentscheidung:** FULL behalten; experimentelle Modi bleiben opt-in.
MINIMAL löst den dominanten frühen Fehler nicht und ist als Standardänderung
abgelehnt. Keine allgemein überlegene natürliche Gesichtsqualität bewiesen.
Weitere Seeds, Motive, Sprache, Hände/Ganzkörper und 1080p-Qualität sind mit
dieser Runde nicht abgedeckt. Zusätzliche Renders ohne neue Hypothese werden
nicht gestartet. Messverbesserungen werden nicht als visuelle Freigabe verkauft.

Vollständige aggregierte [Vergleichsdaten](ltx-quality-audit-evidence/comparison.json),
[VAE-Messung](ltx-quality-audit-evidence/vae-reconstruction.json) und
[Testmatrix](image-model-test-matrix.md). Lokaler Rollout und abschließende
Produktionswiedergabe werden nach erfolgreicher Prüfung unten ergänzt.
