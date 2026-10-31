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
das sind Pixelpuffer, keine Gesamtprognose des Modell-Peaks. Kein zweites Modell
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

CPU-/Integrationstests und kontrollierter GPU-Versuch werden anschließend mit
dem Ergebnis und einer ausdrücklichen Annahme-/Ablehnungsentscheidung ergänzt.
