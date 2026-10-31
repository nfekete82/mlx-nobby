# LTX I2V: Ursachen eingrenzen und Bildkonditionierung isoliert prüfen

Datum: 31.10.2026 (Europe/Berlin). Branch:
`feat/ltx-i2v-cause-isolation-20261031`, Basis `641cb2c1` / PR #389.
Die bestehende Pipeline und ihre Ergebnisse stehen im
[vorherigen Bericht](LTX_QUALITY_REPORT_2026-10-31.md).

## Phase 1: vorhandene Medien, ausschließlich CPU

Analysiert wurden alle **482 nativen Frames** der vorhandenen A/B-Videos:

- A: `672e1f3cbada8eff4e6b456b.mp4`, Ausgangsstand mit CRF-10-Zwischenclips.
- B: `b6731ecfcbbf3114a32b5c01.mp4`, verlustfreie Zwischenclips / genaue Uhren.

Kein neues GPU-Video und kein VAE-Modell wurden in Phase 1 geladen. Pro Frame
lief Apple Vision ausdrücklich auf CPU; Bildanalyse verwendet NumPy, Pillow,
SciPy und FFmpeg. Die originale PNG-Datei, die nativen Frames und Kontaktbögen
liegen ausschließlich lokal unter `artifacts/ltx-quality-causes-20261031/`.

Die Zuordnung erfolgt nach **Frame-Index relativ zum ersten Bild**, nicht nach
dem verschobenen Container-PTS von A. Initialsegment: n=0–144 (145 Frames,
t=0–6,0 s); erste Verlängerung n=145–192 (6,0417–8,0 s); zweite Verlängerung
n=193–240 (8,0417–10,0 s). Ein zusätzliches Displayintervall für den inklusiven
Startframe ist berücksichtigt.

### Augen, Pupillen, Blinzeln und Bewegung je Abschnitt

| Abschnitt | A | B | Einordnung |
| --- | --- | --- | --- |
| 0–6 s | Beidseitig geringe Augenöffnung n=24–64 (41 Frames / 1,708 s), erneut n=102–122 (21 Frames / 0,875 s) | Dieselben beiden Intervalle | Der lange erste Lidschluss und das spätere zusammengekniffene Lächeln existieren **vor jedem Extend**. |
| 6–8 s | Ruhiges Lächeln / geringe Kopfbewegung; keine entsprechende beidseitige Schließung erkannt | Kurzer Kandidat n=169–171 (3 Frames / 0,125 s), im nativen Bildstreifen sichtbar | Unterschiedliche Bewegungsfortsetzung bei ähnlicher Gesamtpose. Kein abrupt neu entstehender Identitätswechsel am Schnitt. |
| 8–10 s | Längerer Kandidat n=213–229 (17 Frames / 0,708 s) | Zwei kurze einseitig/wechselnd zusammengekniffene Bewegungen; beidseitige Kandidaten n=197 (1 Frame) und n=223–229 (7 Frames / 0,292 s) | Mimik und Augenablauf unterscheiden sich. Die Ein-Frame-Detektion ist kein verlässlich erkannter Blink. |

Die Intervalle sind **heuristische Kandidaten**, keine objektive Diagnose von
natürlichem Blinzeln: beide rollkorrigierten Augenöffnungen müssen unter 45 %
ihres jeweiligen 90. Perzentils im Abschnitt liegen. Die Kontaktbögen zeigen
unabhängig davon den langen ersten Lidschluss und die lächelnde Verengung.
Lächeln, zusammengekniffene Augen, Blickrichtung und Detektorfehler beeinflussen
die Schwelle. Ein kurzer Lidschluss ist kein ausreichender Qualitätsbeweis.

Die Pupillen sind in den offenen nativen Frames sichtbar; bei geschlossenen
oder sehr schmalen Augen ist weder ihre tatsächliche Form noch ihre Lage durch
diesen Detektor zuverlässig bewertbar. Pupillenmittelpunkte werden relativ zur
Augenkontur dokumentiert, aber nicht als Form- oder Identitätsmetrik gewertet.
Es wird kein automatischer Nachweis einer korrekten Iris/Pupille behauptet.
Die Bildstreifen erlauben eine visuelle Kontrolle ohne Schärfung/Retusche.

Gesichtsproportionen bleiben in den inspizierten Bildern insgesamt ähnlich;
Kopfneigung, Lächeln und Mundöffnung verändern erwartbar Augenabstand im
Bild, Nasen-/Mundrelationen und sichtbare Zahnform. Diese Bewegungen werden
nicht als Drift wegnormalisiert. Es gibt keine ausreichende Evidenz, dass
beide Verlängerungen die Identität systematisch stärker verändern als das
Initialsegment. Im Abschnitt 6–8 s ist B etwas bewegter als A; höhere zeitliche
SSIM bei A ist hier kein Qualitätsgewinn, sondern kann geringere Bewegung
widerspiegeln.

Eine Korrektur zur bisherigen Geometrieauswertung: axisparallele Augenhöhe/
-breite hängt stark von der Kopfneigung ab. Die neue Auswertung projiziert auf
die Verbindung der Augenmittelpunkte und deren Senkrechte. Ein Rotationstest
prüft, dass reine Kopfneigung keine künstliche Änderung der Öffnung erzeugt.
Das ist keine vollständige 3D-Posekorrektur; Yaw/Perspektive bleiben Störgrößen.

Innerhalb der Abschnitte (jeweils ohne eingehenden Join) betragen die medianen
SSIM-Werte A/B: **0,94034/0,94036**, **0,99753/0,99672** und
**0,99676/0,99610**. Diese Helligkeitswerte werden nicht als Gesichtsqualität
interpretiert. [Abschnittsstatistik](ltx-i2v-cause-evidence/existing-segments.json).

### Bildgeometrie vor dem Modell

Das Original ist RGB, 1097×1434, ohne eingebettetes ICC-Profil und ohne
EXIF-Rotation. Die bestehende `contain`-Vorbereitung ergibt 704×920 Bildinhalt
auf 704×1280 mit jeweils 180 schwarzen Zeilen oben/unten. Für Stage 1 wird das
auf 352×640 mit entsprechend halbiertem Inhalt reduziert. Es gibt an diesem
Foto keinen Befund für eine verlorene EXIF-Rotation, falsche ICC-Konvertierung,
eine grobe Seitenverhältnisverzerrung oder ein abgeschnittenes Gesicht. Die
32/64-Pixel-Raster und die begrenzte effektive Augenauflösung bleiben relevant.
[Quellgeometrie](ltx-i2v-cause-evidence/source-geometry.json).

### Nachgewiesen und nicht nachgewiesen

**Nachgewiesen:** Der auffällig lange erste Lidschluss entsteht im Initialsegment.
Extend und erneutes VAE-Encoding des späteren Kontexts können nicht seine
Ursache sein. Der Lidschluss ist keine Frame-Duplikation: die vorhandenen Videos
haben keine exakten benachbarten Duplikate, die Bewegung läuft weiter.

**Nachgewiesen:** Die unveränderte native Aufbereitung komprimiert das bereits
vorbereitete PNG nochmals mit H.264 CRF 18 / 4:2:0. Eine CPU-Probe führt genau
die gepinnten NumPy/Pillow/FFmpeg-Funktionsdefinitionen per AST aus und lässt
MLX-Importe, Tensor- und VAE-Funktionen weg. Gegenüber CRF 0 entstehen:

| Aufbereitungsstufe | SSIM CRF 18 gegen CRF 0 | Luma-MAE | Detailindikator CRF 18 / 0 |
| --- | ---: | ---: | ---: |
| 352×640 für Stage 1 | 0,996871 | 0,415061 | 190,570 / 196,351 |
| 704×1280 für Stage 2 | 0,992576 | 0,591265 | 85,397 / 88,084 |

Der RGB-MAE des vollen vorbereiteten Bildes beträgt 0,910854 bei CRF 18 und
exakt 0 bei CRF 0. Native CRF 0 bedeutet hier **keine Rekodierung**, nicht eine
H.264-RGB-Konversion mit verlustfreiem Encoder. Der Detailindikator ist die
Laplacian-Varianz; auch Rauschen beeinflusst ihn.
[CPU-Aufbereitungsevidenz](ltx-i2v-cause-evidence/image-preprocessing.json).

Schon Frame 0 unterscheidet sich vom vorbereiteten Original: Ganzbild-SSIM
A/B etwa 0,953595/0,953602, mit identischer Gesichts-ROI etwa
0,936698/0,936681. Diese Werte enthalten **zusammen** Aufbereitung,
VAE/Konditionierung und Ausgabe-/Transportkodierung; sie isolieren den VAE
nicht und sind keine Gesichtsqualitätsbewertung.
[Frame-0-Pixelvergleich](ltx-i2v-cause-evidence/initial-frame-pixel-comparison.json).

**Nur Hypothese:** Dieser kleine zusätzliche Bildverlust verursacht relevante
Augenfehler während der späteren Bewegung. CRF 18 passt zur Trainingsverteilung;
mehr erhaltene Pixel können sogar schlechtere Modellresultate ergeben.

**Aus Quellcode belegt, Qualitätswirkung nicht isoliert:** Initiale I2V
konditioniert ein einziges Replace-Bild auf Frame 0, zunächst bei halber und
erneut bei voller Auflösung. Die anschließende Bewegung erzeugt das Modell.
Die Video-VAE und die halb aufgelöste Generierung können feine Merkmale ändern;
ihre jeweiligen Beiträge sind ohne separate Latent-/VAE-Messungen nicht
kausal getrennt. Ebenso bleibt der Einfluss von Q4-Gewichten und Prompt offen.

**Aus Quellcode belegt, Qualitätswirkung nicht isoliert:** Extend kodiert den
Kontext nochmals im VAE. Das kann spätere Details beeinflussen, erklärt aber
nicht den frühen Lidschluss. Die beiden vorhandenen Videos sind kein
Latent-Carry-gegen-VAE-Rekodierung-Experiment.

## Phase-2-Entscheidung und Opt-in-Vertrag

Der vorgeschlagene Latent-Carry-Umbau wird **nicht** vorgezogen: Ein vorwiegend
bei den Verlängerungen entstehender Fehler ist nicht belegt. Stattdessen prüft
ein kleiner isolierter Versuch die initiale Bildaufbereitung.

Explizit über die bestehende Video-API: `payload.i2v_image_crf = 0`.
Ohne diese Angabe bleibt die native Standardeinstellung erhalten. Zulässig nur
für ein einzelnes Standard-Rolling-I2V mit dem gepinnten 0.18-Worker; T2V,
segmentierte/multiple Bilder, alternative Runtime oder CLI-Fallback sind
abgewiesen. Die native CLI erhält keinen erfundenen Schalter.

Der Worker ersetzt ausschließlich den bisherigen `image=`-Kurzaufruf durch
**einen** nativen `ImageConditioningInput.replace(path, 0, 1.0, crf=0)`.
Die gleiche aufgelöste Eingabe erreicht nativ Stage 1 und Stage 2. Es gibt keinen
zusätzlichen Guide, keinen späteren Pose-Anker und keinen neuen Identitäts- oder
Negativprompt. Seed, Auflösung, Schritte, Rolling-Kontext und Audiopfad bleiben
gleich. Der erste Ausgabeframe wird nicht nachträglich mit dem Original ersetzt.
[CPU-Vertrag mit der tatsächlich installierten Klasse](ltx-i2v-cause-evidence/native-contract.json).

### Speicher, Audio, Checkpoints und Fallback

Ein bereits vorhandener Frame-0-Ersatz wird lediglich mit anderem Bild-CRF
beschrieben. Anzahl und Größe der Konditionierungs-Token wachsen nicht; halbe
und volle VAE-Auflösung bleiben 352×640 und 704×1280. Die reine RGB-Kopie
704×1280×3 belegt etwa 2,58 MiB, die halbe Float32-Kopie ebenfalls etwa 2,58 MiB;
das sind Pixelpuffer, keine Gesamtprognose des Modell-Peaks. Ein voller
Float32-Pixelpuffer benötigt etwa 10,31 MiB, das entsprechende BF16-Tensor
etwa 5,16 MiB; diese Formen existieren bereits im Standardpfad. Bei 145
Initialframes entstehen 19 zeitliche Latents: Stage 1 hat 19×20×11 = 4.180
Videotokens, Stage 2 19×40×22 = 16.720. Der Versuch fügt keine
Keyframe-Guide-Tokens hinzu. Kein zweites Modell
wird parallel geladen; derselbe Low-RAM-Worker und dieselben aktiven
Systemspeicher-/Swap-Grenzen gelten weiterhin.

Audio und 25-Frame-Extend ändern sich nicht. Für einen künftigen Latent-Carry
müssten **beide** räumlichen Video-Kontexte und der exakt passende Audio-Kontext
persistiert und gegen Runtime, Modell, Latentform, Zeitraster, Seed, Prompt und
Quellhash geprüft werden. Das wird durch diesen I2V-Versuch weder ersetzt noch
als implementiert ausgegeben.

Der Opt-in-Wert ist Teil des bestehenden Checkpoint-Fingerprints. Standard-
`None` wird kanonisch wie ein bisher fehlendes Feld behandelt; alte Standard-
Checkpoints und Resume-Anfragen bleiben kompatibel. Ein Wechsel zwischen
Standard und Experiment darf keinen Checkpoint wiederverwenden. Die bisherige
Transport-/Conditioning-Version wird für den Standardpfad nicht geändert.
Native Runtime-Dateien und Modellgewichte werden nicht verändert.

CPU-/Integrationstests und die beiden kontrollierten GPU-Versuche sind unten
mit Ergebnissen und ausdrücklichen Annahme-/Ablehnungsentscheidungen dokumentiert.

## Ergebnisse der zwei neuen GPU-Versuche

Das Budget ist ausgeschöpft: **zwei vollständige neue Videos, null fehlgeschlagene
Generierungsversuche, null GPU-Retries**. Beide nutzten denselben installierten
LTX-2.5-Q4-Checkpoint, dieselbe unveränderte gepinnte Runtime, dasselbe Original,
denselben Nutzerprompt und Seed 0, 704×1280, 24 FPS und 8+3 native Distilled-
Ancestral-Schritte pro Abschnitt (CFG nicht anwendbar).

| Variante | Bestehende Vergleichsbasis | Versuch 1: initiales Bild-CRF 0 | Versuch 2: Textführung aus |
| --- | --- | --- | --- |
| Video-ID | `b6731ecfcbbf3114a32b5c01` | `4b46644eefe0c229ff0c6412` | `f56615b625f61f177bd42125` |
| Job-ID | `cb0127c78f871c3878512788` | `1a5c36b2c257a912fcf29bf5` | `cf06686b4e2819f004233ccd` |
| Initiales Bild-CRF | native 18 | **0** | native 18 |
| Weiche Textführung | an | an | **aus**, `identity_lock=false` |
| Frame-0-Bildanker | vorhanden | vorhanden | vorhanden |
| Renderzeit | 420,956 s | 418,473 s | 433,791 s |
| Geringe Augenöffnung im Initialsegment, erstes Fenster | 41 Frames / 1,708 s | 43 Frames / 1,792 s | **20 Frames / 0,833 s** |
| Zweites Fenster im Initialsegment | 21 Frames / 0,875 s | 21 Frames / 0,875 s | **7 Frames / 0,292 s** |
| Kandidaten in 6–8 s | 3 Frames | keine | 4 und 2 Frames |
| Kandidaten in 8–10 s | 1 und 7 Frames | 8 Frames | keine |
| Median benachbarte SSIM, Gesamtvideo | 0,986028 | 0,961117 | 0,981764 |
| SSIM am ersten Join | 0,987769 | 0,986250 | 0,947629 |
| SSIM am zweiten Join | 0,991920 | 0,992206 | 0,990881 |

Die Augenfenster verwenden dieselbe oben dokumentierte Heuristik; sie sind keine
validierte Blinkzählung und kein alleiniger Akzeptanzwert. Eine Sekunde lang
enger geöffnete Augen kann mit Mimik zusammenhängen. Ein einzelnes Video pro
Variante erlaubt keine statistische Aussage über andere Seeds oder Personen.

**Versuch 1 – Ergebnis und Entscheidung:** CRF 0 erhält die Eingangspixel besser,
verkürzt aber den langen frühen Lidschluss nicht. In den nativen Gesichtsbildern
ändert sich die Mimik – unter anderem weniger starke Mundöffnung –, ohne eine
nachgewiesene bessere natürliche Augenbewegung. Der Frame-0-Gesichts-SSIM zum
vorbereiteten Original in derselben festen ROI beträgt ungefähr 0,936090,
gegenüber 0,936681 in der Vergleichsbasis: auch dort kein sinnvoller Gewinn.
**Als Lösung des Augen-/Bewegungsproblems verworfen; keine Default-Änderung.**
Der API-only-Code bleibt auf dem Forschungsbranch ausschließlich als explizites,
nicht freigegebenes Experiment für reproduzierbare Tests.

**Versuch 2 – Ergebnis und Entscheidung:** Ohne die automatischen Textzusätze
öffnen sich die Augen im ersten Abschnitt früher wieder. Der spätere Lidschluss
beim Lächeln ist kürzer. Das ist auch in den nativen Bildstreifen sichtbar,
nicht nur in einem aggregierten Score. Kopfbewegung, Lächeln und Mimik bleiben
erhalten; es wurde kein Gesicht eingefroren und kein späterer Ausgangsbild-
Anker gesetzt. Proportionen und breite Gesichtszüge wirken im geprüften Material
ähnlich; perfekte Pupillenform oder biometrische Identität sind weiterhin nicht
nachgewiesen. Der verbleibende erste Ablauf mit ungefähr 0,83 s geringer
Augenöffnung ist noch kein Beweis für natürliches kurzes Blinzeln.

Der niedrigere SSIM-Wert des ersten Join in Versuch 2 ist **kein isoliert
nachgewiesener Schnittsprung**. Die benachbarten Werte n=143/144/145/146 sind
0,9456 / 0,9482 / 0,9476 / 0,9504: die stärkere Änderung beginnt vor der Grenze
und setzt sich danach fort. Eine feste native Gesichts-ROI ergibt für die
Paare 143→144 / 144→145 / 145→146 etwa 0,8614 / 0,8646 / 0,8635. Das geprüfte
native Bildpaar 144/145 zeigt keinen eindeutigen abrupten Identitätswechsel.
Mehr Bewegung und Veränderungen von Licht/Details sind nicht automatisch ein
Fehler. Eine rein metrische Rangliste würde diesen positiven früheren
Lidablauf übersehen.

**Begrenzter positiver Befund für Versuch 2**, geeignet für manuelle Prüfung
mit diesem Original und Seed. Keine automatische Freigabe, keine Behauptung
einer generell stabileren Gesichtsidentität. Der vorhandene Opt-out ist bereits
pro Job wählbar; der Standard `identity_lock=true` bleibt unverändert.

Die Ein-Faktor-Experimente ändern jeweils nur eine Variable gegenüber der
Vergleichsbasis. In Versuch 2 bleibt der **Nutzerprompt** identisch, die
effektiven Modellprompts ändern sich jedoch im Initialsegment **und** bei den
Verlängerungen. Der Effekt im ersten Segment kann nicht vom späteren Extend
verursacht sein; Effekte späterer Abschnitte lassen sich nicht auf eine einzelne
Promptphase zurückführen. Weder ein einzelnes Wort noch der VAE als eigentliche
Ursache des langen Lidschlusses sind damit identifiziert.
[Effektive Prompt-Hashes](ltx-i2v-cause-evidence/controlled-conditioning-factors.json).

### Technische Validierung und Speicher

Beide neuen Videos besitzen **241 Frames bei 24 FPS**, 704×1280, null exakte
benachbarte Duplikate und null PTS-Anomalien. Video und Audio beginnen bei null
und enden bei 10,041667 s. Audio-Konditionierung, Rolling-Fenster und Sample-
Uhren wurden nicht umgebaut. Bei geänderten Textprompts kann sich auch der
**generierte Audioinhalt** ändern; Stream-Timing belegt keine semantische
Lippensynchronität.

Reale Chromium-Wiedergabe über die produktive Web-Video-API bestand für beide
neuen MP4s einschließlich aller sieben Sprungpositionen. Die Browserprüfung
bestätigt Dekodierung/Wiedergabe, nicht die Natürlichkeit der Bewegungen.

| Speicherbeobachtung | Bild-CRF 0 | Textführung aus |
| --- | ---: | ---: |
| Externe 2-s-Samples | 194 | 201 |
| Niedrigste beobachtete aktive Verfügbarkeit | 67 % | 58 % |
| Niedrigster beobachteter Headroom | 26,16 GiB | 21,84 GiB |
| Beobachteter Swap, erstes→letztes Sample | 9,71→9,71 GiB | 9,71→9,69 GiB |
| Speicherdruck | normal | normal |

Die externen Monitore beginnen ungefähr 29–31 s nach Jobstart; sie decken etwa
390 bzw. 404 s ab, nicht lückenlos das ganze Videojob-Leben. Die unveränderten
internen aktiven RAM-/Swap-Guards galten auch vor diesem externen Messfenster.
Zwei-Sekunden-Sampling kann kurze Spitzen übersehen. Die Aufnahme zu
Modellzulassung zeigte jeweils 88 % Verfügbarkeitsabschätzung nach dem regulären
exklusiven Ressourcenwechsel. Es gab keinen parallelen schweren Modellstart,
keine Schwellenlockerung und keinen Speicherabbruch. Einzelne Laufzeiten sind
keine belastbare Geschwindigkeitsrangfolge.

[GPU-/Abschnittsmesswerte](ltx-i2v-cause-evidence/gpu-comparison.json) ·
[Speicherprotokoll-Zusammenfassung](ltx-i2v-cause-evidence/memory-summary.json) ·
[CRF-0-Wiedergabe](ltx-i2v-cause-evidence/crf0-production-playback.json) ·
[Textführung-aus-Wiedergabe](ltx-i2v-cause-evidence/guidance-off-production-playback.json).

### Tests, Stand und nächster Schritt

- **63 bestanden**: Opt-in-Vertrag, API, native Factory/Worker-Payload,
  Rolling/Segmentierung, alter Standard-Fingerprint und Resume-Kompatibilität,
  Provider und Worker-Wiederverwendung. Die neun Experimenttests wurden nach
  Ergänzung des Tests gegen Zustandsübernahme nochmals bestanden.
- **76 bestanden**, zehn Subtests bestanden: weitere API-/Resume-/Langvideo-
  und Edit-Verträge; unveränderte Deprecation-Warnung im Testclient.
- **6 bestanden**: Bildanalyse/Benchmark einschließlich Kopfrotation,
  Abschnittszuordnung und explizitem Detektorausfall.
- Erforderlicher JavaScript-Videojob-Test: bestanden. Keine Frontend-Änderung;
  die bekannten allgemeinen Collection-/Browser-Fixture-Probleme des vorherigen
  Berichts wurden nicht fachfremd umgebaut oder als grün ausgegeben.

Tests überschneiden sich; Zahlen nicht zu einer eindeutigen Testanzahl addieren.
[Maschinenlesbare Testergebnisse](ltx-i2v-cause-evidence/tests.json).

Native Runtime und Modellgewichte wurden nicht geändert. Der Videodienst ist
wieder frei, Web-Health ist `ok`. Agent und Webcontainer wurden nicht für eine
Qualitätsfreigabe umgestellt. Das Laden des Video-Codes erfolgte nur im
Leerlauf für die expliziten Versuche; beide normalen Standardwerte bleiben
bestehen. [Abschlusszustand](ltx-i2v-cause-evidence/final-state.json).

Lokale, private Artefakte:

- `artifacts/ltx-quality-causes-20261031/phase1.html`: vorhandenes A/B abschnittsweise.
- `artifacts/ltx-quality-causes-20261031/comparison/index.html`: bestehende
  Vergleichsbasis plus beide neuen Versuche, Videos/Originale/native Einzelbilder.
- `.../dense/`, `.../crf0-dense/`, `.../guidance-off-dense/`: alle nativen Frames,
  rollkorrigierte Landmark-Beobachtungen und feste Bildstreifen je Abschnitt.

Die Hypothese „Verlängerungen sind die vorwiegende Ursache“ wird durch dieses
Material nicht gestützt. Deshalb ist kein unbewiesener Latent-Carry-Pfad
implementiert worden. Der gezieltere nächste Versuch wäre eine getrennte,
knappe Promptführung für initiale I2V und Bewegungsfortsetzung oder eine isolierte
VAE-/Stage-1-Rekonstruktionsmessung mit demselben Foto. Die Beiträge von
Bild-VAE, halb aufgelöster Denoising-Dynamik und einzelnen Promptbestandteilen
bleiben offen. Dafür wäre ein neues ausdrücklich begrenztes Testbudget nötig;
jetzt wird kein drittes GPU-Video gestartet. Der neue PR bleibt Draft und
enthält keine automatische Merge- oder Qualitätsfreigabe.
