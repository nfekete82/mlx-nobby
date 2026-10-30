# LTX Identity Lock – kontrollierter 9-Sekunden-Pilot (2026-10-30)

## Beobachtetes Problem

30 s/1080p können mit zehn isolierten 3-Sekunden-Blöcken auf dem M5 Max
bei begrenztem Speicher erfolgreich gerendert werden. Da bisher jeweils nur
der letzte Videoframe zum nächsten Abschnitt weitergereicht wird, kumulieren
jedoch Veränderungen von Gesicht, Haaren, Kleidung und Proportionen.

## Technischer Ansatz (experimentell)

* **Keine Änderung der RAM-Architektur:** weiterhin 3 Sekunden bzw. 73 Frames
  pro 1080p-Segment, Worker-Neustart, 20-%-Grenze und Checkpoint/Resume.
* Bei I2V mit Originalbild: Beginn von Segment N mit dem **letzten Bild von
  Segment N-1** (expliziter \`replace\`-Anker auf Frame 0), zusätzlich das
  **ursprüngliche Nutzerbild als weicher \`guide\`-Anker** an Frame 0.
  Der ursprüngliche Entwurf setzte den Guide bei Frame 36: Das konnte
  die Pose mitten im Segment zurückspringen lassen.
* Weiche Guide-Stärke 0.30 (zulässig 0.10–0.60); **kein Hard Replace**
  innerhalb des Clips, damit die Person nicht zur Anfangspose zurückspringt.
  **Wichtig:** Bei LTX-MLX v0.18 ignoriert \`image=\` den ersten Frame,
  sobald \`images\` belegt ist. Der Provider muss deshalb das vorangehende
  Schlussbild ausdrücklich in die \`images\`-Liste aufnehmen.
* Mit Identity Lock bleibt der Seed für alle Segmente unverändert;
  der Folgeprompt betont Gesichtszüge, Haare, Kleidung und natürliche Bewegung.
* Standardmäßig aktiv für segmentiertes **Bild-zu-Video mit Originalbild**.
  Ohne Originalbild (reines Text-zu-Video) hat Identity Lock keine Wirkung.
  Per Video-API lässt sich das Verhalten über
  `"identity_lock": false` abschalten und mit
  `"identity_strength": 0.30` kalibrieren.
* Vorab geprüft wird die native Keyframe-Unterstützung von
  `ltx-2-mlx`; bei fehlender Funktion fail-closed statt stillem Fallback.

Die native LTX-MLX-Schnittstelle kennt `image=` (Frame 0) und
`images=[ImageConditioningInput.at(...)]` (weitere Keyframes). Es wird
keine neue Face-ID/LoRA vorgetäuscht. Weiches Bild-Conditioning ist **kein
Identitätsbeweis**: Es kann sich weiterhin Gesicht, Pose oder Kleidung
verändern. Wiederholte Pose-Anker können die Bewegung beeinflussen.

## Kurztest

Im Chat: eigenes Porträtbild hochladen, `Video → maximale Qualität
(1080p) → 9 Sekunden · 1080p-Kurztest` wählen, Prompt für ruhige,
kontinuierliche Bewegung nutzen. **Nicht** zuerst 30 s rendern.

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/feat/ltx-identity-lock-9s-20261030

python3 -m pytest -q tests/test_video_segmented.py tests/test_video_long.py \
  tests/test_video_mlx_provider.py tests/test_video_mlx_warm_runtime.py \\
  tests/test_ltx_018_rollout.py
node tests/test_video_job.mjs

# Erst nach Abschluss anderer laufender Videogenerierungen:
mlx video restart
mlx agent restart
docker compose up -d --build --no-deps mlx-web
```

Vergleich für I2V auf identischem Bild, Prompt und Seed:
`identity_lock: true` gegen `false`, gleiche Auflösung und Länge.
Frames bei t=0, 2.9, 3.1, 5.9, 6.1, 8.9 s visuell vergleichen:
Gesichtsstruktur, Frisur, Alter, Augen-/Nasen-/Mundform, Kleidung und
Schnittsprünge. Ein weiterer 9-s-Pilot mit
`identity_strength: 0.20` kann bei zu starker Rückkehr zur Ausgangspose
helfen.

### Grenzen

Die 9-s-Dauer wird nur für 1080p bei 24 fps angeboten. Der Default bei
5–20 s bleibt unverändert. 30/60 s nutzen nach wie vor den begrenzten
Segmentmodus. Kein automatischer Face-Embedding-Check oder Retry:
Dafür wären eine validierte Identitätsmetrik und eine konservative
Fehlalarm-Schwelle nötig, bevor wir lange GPU-Läufe automatisch wiederholen.
Die CI-Tests sind CPU-Mocks; native GPU-Qualität muss auf macOS geprüft werden.
