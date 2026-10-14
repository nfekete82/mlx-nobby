# Qwen Image 2.1 Edit — kontrollierter Step-Cache-A/B-Test

Der Profilvergleich zeigt bei drei 1024×1024-Edits mit **40 Steps**
89,84 / 91,29 / 93,24 Sekunden. Rund 75–79 Sekunden davon liegen
innerhalb der beobachteten tqdm-Fortschrittsphase. Die frühere 59-s-Reihe
hatte keine verifizierten identischen Einstellungen; sie ist daher
**kein** Beweis für eine Regression.

MFLUX kann bei Qwen 2.1 Edit Text-/Bildpräfixe mit KV Cache
standardmäßig wiederverwenden. Ein **zusätzlicher Step Cache** kann
Transformer-Blöcke überspringen. Der Step Cache verändert die Rechenausgabe
potenziell; er ist **kein** qualitätsneutraler Beschleunigungsmodus.
Wir aktivieren ihn nicht global.

## Voraussetzungen

- Lokaler Mac mit laufendem Nobby-Bilddienst auf
  `http://127.0.0.1:8030`, Osaurus Qwen Image 2.1 Edit aktiviert.
- Während des Benchmarks keine anderen Bild-/Video-/KI-Schwerlastjobs.
- Ein quadratisches Bild mit mindestens 1024×1024 Pixeln (PNG, JPEG oder WebP)
  in `~/.config/mlx-web/images` oder einem der vom Service erlaubten
  Upload-/Attachment-Ordner. Die Quelle wird nicht verändert.
- Den exakt gleichen Bearbeitungsprompt für alle vier Läufe wählen.

## Vorprüfung (erzeugt **keine** Bilder)

```bash
cd ~/mlx-web
./image-venv/bin/python scripts/benchmark-qwen21-step-cache.py \
  --source "$HOME/.config/mlx-web/images/DEIN-1024-BILD.png" \
  --prompt "Ändere nur die Farbe des Pullovers in Blau; Rest identisch." \
  --seed 42
```

Anschließend mit exakt denselben Parametern und zusätzlichem `--run`
starten. Vier Bildjobs werden strikt **nacheinander** über den
vorhandenen nativen `/jobs`-Endpoint ausgeführt:

1. Step Cache **aus** (KV Cache explizit an)
2. Step Cache **an** (threshold 0.12, KV Cache an)
3. Step Cache **an** (threshold 0.12, KV Cache an)
4. Step Cache **aus** (KV Cache an)

Alle vier verwenden dasselbe Quellbild, denselben Prompt, Seed,
1024×1024 Pixel, 40 Steps, Guidance 1.0 und das Profil `quality`.
Der native Dienst übernimmt unverändert die bestehenden RAM-/Memory-
Schutzmechanismen, Subprozessbegrenzungen und die Auftrags-Sperre.

Ergebnis: `artifacts/performance/qwen21-step-cache-ab.json` (nur lokal,
Dateirechte 0600). Der Report enthält Zeiten, unkritische Einstellungen
und lokale Pfade zu den fertigen Bildern für einen **manuellen**
A/B-Bildvergleich; keine Prompts, Quellbildpfade, Chat-IDs oder Bilddaten.
Das Skript lädt keine Dateien herunter, löscht keine Bilder und
ändert keine persistenten Modell- oder Serviceeinstellungen.

Optionen: `--cycles 2` führt acht Läufe in zwei ABBA-Zyklen aus.
`--threshold 0.12` ist der MFLUX-Standard. **Keine** aggressiveren
Schwellwerte zur Produktionsvorgabe machen, bevor visuelle Unterschiede
und eine zweite Messreihe bewertet wurden.

## Auswertung

Der Report meldet `cache_on_change_pct` nur, wenn beide Arme dieselben
beobachteten Schritte, Abmessungen, Guidance, Referenzbildanzahl,
KV-Cache-Einstellung, Low-RAM-Einstellung und Cachegröße besitzen.
Negative Prozentwerte bedeuten eine schnellere Ausführung mit Step Cache.
Bei wechselndem Memory-Modus oder fehlenden Messdaten zeigt er
`comparable: false` und keinen unbegründeten Speedup.

Anschließend die Bilder besonders auf Text, Gesichter, feine Details,
Kanten und die genaue Einhaltung der Bearbeitungsanweisung vergleichen.
Eine visuell schlechtere Ausgabe ist **kein** Erfolg, selbst wenn
der Benchmark schneller läuft. Bilder mit gleichem Seed müssen bei
unterschiedlichem Cache-Modus nicht pixelgleich sein.

## Grenzen und Sicherheit

- **Explizite Zustimmung** durch `--run`; Default ist Dry-Run.
- Stoppt nach dem ersten Fehler, startet keine parallelen Jobs.
- Läuft der Native Job bei einem Client-Timeout noch, wird er **nicht**
  automatisch gelöscht oder abgebrochen. Vor Wiederholung im Nobby-UI
  prüfen, ob der Auftrag abgeschlossen wurde.
- Nur Loopback-HTTP, kein öffentlicher Endpoint, keine Cloudnutzung.
- Der Script-Pfad nutzt `image-venv`, weil zur Quellbildprüfung Pillow
  erforderlich ist.
- Tqdm-Timestamps sind beobachtete Ausgabe, keine exakten GPU-Events.
- Vier Läufe sind ein kleiner lokaler Vergleich, keine Garantie einer
  stabilen Beschleunigung auf anderen Rechnern oder Konfigurationen.
