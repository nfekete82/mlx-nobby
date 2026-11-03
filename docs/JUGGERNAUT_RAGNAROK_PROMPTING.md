# Juggernaut XIII: Ragnarok — lokale Prompt-Wissensbasis

Stand: 2026-11-02. Diese Notizen fassen den Ragnarok-Leitfaden eigenständig zusammen; sie sind **kein** kopierter Seiteninhalt und keine Anweisung zum Nachladen externer Quellen während der Bildgenerierung.

## Verbindliche Quellen / Geltungsbereich

- Modell: Juggernaut XIII: Ragnarok, SDXL, lokale Registry-ID `juggernaut-xl`.
- Modellübersicht (RunDiffusion, aktualisiert 2026-04-09): https://www.rundiffusion.com/juggernaut-xiii-ragnarok
- Ausführlicher Prompt-Guide (RunDiffusion, aktualisiert 2026-10-22): https://www.rundiffusion.com/prompt-guide-for-juggernaut-xiii-ragnarok-by-rundiffusion
- Lokale Implementierung, Qualität und mögliche Abweichungen: `docs/JUGGERNAUT_RAGNAROK_BEST_SETTINGS.md` und `docs/RAGNAROK_SAMPLING_CONTROLS.md`.

Die Prompt-Beratung ist im Chat über die Vorlage **Juggernaut Ragnarok** auswählbar. Die automatische Ausführung im Bilddienst bleibt von der Chatvorlage unabhängig. Weder die Internetseite noch der lange Leitfaden werden als ungeprüfter Systemprompt an den Bilddienst übergeben.

## Prompt-Aufbau (Reihenfolge nach Priorität)

1. **Motiv:** Was oder wer soll zu sehen sein? Hauptmotiv und Anzahl zuerst.
2. **Handlung/Pose:** Was passiert? Welche räumliche Beziehung besteht zu Objekten?
3. **Ort/Umgebung und wichtige Objekte:** Nur Elemente, die das Ergebnis beeinflussen.
4. **Bildmedium/Stil:** Etwa `photograph`, `watercolor painting`, `surreal photo`, `digital illustration`.
5. **Bildaufbau und Perspektive:** `full body`, `wide shot`, `eye level`, `low angle`, `close-up` usw.
6. **Licht/Farbe/Stimmung:** Tageslicht, weiches Licht, Richtung, Kontrast; keine widersprüchlichen Angaben.
7. **Details:** Materialien und Texturen, Kleidung, Zeitperiode, Kultur, Gesichtsausdruck, gegebenenfalls exakt zu druckender Text.

Dies sind die im Guide behandelten Dimensionen: subject, action, environment, object, color, style, mood, lighting, viewpoint, texture/material, time period, cultural elements, emotion, medium, clothing und text. Nicht jede Dimension muss in jedem Prompt vorkommen.

## Qualitätsregeln

- Die erste Aussage trägt das wichtigste Motiv. Action und entscheidende Objekte folgen früh.
- Englisch ist für die Prompt-Ausgabe bevorzugt; natürlich formulierte Sätze **und** tagbasierte Schreibweisen funktionieren. BOORU-Tags sind optional, falls ein Anwender sie ausdrücklich wünscht.
- Kurze, konkrete Prompts sind der Ausgangspunkt. Der Guide empfiehlt ungefähr **höchstens 75 CLIP-Tokens** als praxisnahen Zielwert, keine harte Wort- oder Zeichenobergrenze. Prioritäten nicht zugunsten eines starren Limits verlieren.
- Gewichte (z. B. `(subject:1.2)`) nur auf ausdrücklichen Wunsch oder bei einem erkennbaren Prioritätsproblem und nur dort, wo der Generator sie unterstützt.
- Bei Fotorealismus: `natural skin texture`, plausibles Licht, glaubwürdige Materialien nur wenn passend. Kein automatisches Schönheits- oder „cinematic“-Keyword-Stapeln.
- Bei Aufnahmen von Personen: Kameraabstand, Ausschnitt, Haltung, Kleidung, Anatomie und Objektpositionen konkret statt generisch beschreiben. Fotorealismus nicht mit glamourösem Studio-Look gleichsetzen.
- Schrift: wörtlichen Text früh und in Anführungszeichen nennen. SDXL erzeugt Buchstaben nicht immer zuverlässig.
- Negative Prompts anfangs **leer lassen**; nur dokumentierte, tatsächlich unerwünschte Merkmale ergänzen. Nicht automatisch ganze anatomische oder NSFW-Listen hinzufügen.
- Benutzerangaben, Negationen, Zahlen, Kleidung, Namen, Perspektiven, ausdrücklich gewünschte Stile und Negative Prompts haben Vorrang. Nie `no nudity` oder gegenteilige Stilwünsche ungefragt hinzufügen.
- SFW-Bilder können durch präzise Kleidung und ggf. gezielte negative anatomische Tags stabilisiert werden. Das ist ein Anwendungsfall, kein globaler Standard.
- Bei gestalterischer Beratung eine direkt nutzbare **Positive Prompt**-Zeile, eine optionale **Negative Prompt**-Zeile und knappe Settings liefern. Bei explizitem Wunsch nur nach einem Prompt keinen zusätzlichen Ballast ausgeben.

## Ragnarok-Einstellungen (Leitfaden vs. lokale Umsetzung)

| Parameter | RunDiffusion | MLX-Nobby-Hinweis |
| --- | --- | --- |
| Porträt | 832×1216 | `Ragnarok-Porträt` bei explizit gewähltem Modell |
| Sampler | DPM++ 2M SDE oder DPM++ 2M Karras | Tatsächlich unterstützten Scheduler im Backend prüfen |
| Steps | 30–40 | Standard/Quality je nach laufendem Profil; Benutzerwerte gehen vor |
| CFG | 3–6, niedriger oft realistischer | 4.0 als aktueller Richtwert |
| Negative Prompt | zunächst leer | Nicht automatisch auffüllen |
| VAE | eingebaut | Keine separate VAE erforderlich |
| Hi-Res | 4xNMKD-Siax_200k; 15 Schritte; Denoise 0.3; 1.5× | **Nicht** als bestehendes lokales Feature ausgeben; separate Pipeline erforderlich |

## Beispiel, bewusst kurz

Benutzerwunsch: „Eine Frau Anfang 40 joggt im Park, normales iPhone-Selfie, vollständig zu sehen, natürlich statt Studiobild.“

Positive Prompt:
`Casual full-body iPhone photo of a woman in her early 40s jogging on a park path, natural proportions, ordinary sportswear, eye-level wide framing, soft overcast daylight, realistic skin texture, unretouched snapshot.`

Negative Prompt: *(leer)*

Empfehlung: Ragnarok-Porträt, 35 Steps, CFG 4; Sampler laut aktivem lokalen SDXL-Profil. Die 832×1216-Porträtauflösung ist eine Empfehlung und darf bei ausdrücklich anderem Seitenverhältnis nicht erzwungen werden.

## Architekturgrenze

Die lokale Chatvorlage erzeugt **Beratung und kopierbare Prompts**, nicht eigenmächtig Jobs. Der separate Bildpfad übersetzt den Auftrag semantisch möglichst wortgetreu und bewahrt explizite Optionen; kein unkontrolliertes LLM-Rewrite und kein automatisches Trigger- oder LoRA-Nachladen. In `agent/image_prompt_quality_runtime.py` dürfen bei fotorealistischen Personen lediglich wenige kontextuell passende Hinweise ergänzt werden; lange starre Suffixe und pauschale Negative-Prompt-Listen sind zu vermeiden.

## Regressionen

- Kein stilles Überschreiben von Nutzernegationen oder explizitem Negative Prompt.
- Kein Pflicht-NSFW-Filter in unbeteiligten Prompts.
- Keine Änderungen an Qwen/Flux/Video-Prompts.
- Keine Pflichtänderung der Modellparameter oder automatischer Hi-Res-Schritt.
- Die Chatvorlage und die automatische Bildpipeline müssen getrennt testbar bleiben.
