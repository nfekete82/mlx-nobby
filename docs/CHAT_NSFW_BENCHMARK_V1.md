# NSFW / Erwachsenen-Rollenspiel-Benchmark v1 (opt-in)

**Ziel:** Qwen3.8 Abliterated 27B und Dark Scarlett 27B fair bei
**freiwilligen fiktiven Erwachsenen-Rollenspielen** vergleichen.
Dies ist ein **eigener manueller Vergleich**, keine Fortsetzung des allgemeinen
Chat-Quality-Benchmarks. Die 44+4 bestehenden Quality-Fälle bleiben unverändert.

## Warum die bisherigen 42/44 kein Modellvergleich sind

Im letzten Chat-Quality-Bericht stand bei **baseline_model und
candidate_model derselbe Qwen3.8-Pfad**. Beide Läufe hatten 42/44.
Das ist ein Vergleich desselben Modells und **kein Ergebnis für Dark Scarlett**.

Der neue NSFW-Benchmark verlangt deshalb bei jedem Run die erwartete
**reale Modellidentität vom Agenten** mit --expect-model. Jede einzelne
Benchmark-Anfrage übermittelt außerdem die aktuell bestätigte **Modell-ID
und Chatserver-PID** an den Agenten. Im expliziten Benchmark-Modus wird die
Chat-Rolle nicht neu aufgelöst und es wird **kein anderes Modell gestartet**.
Wenn sich die Konfiguration oder die PID inzwischen geändert hat, wird die
Anfrage stattdessen verworfen. Ohne diesen Opt-in-Modus bleibt die normale
Chat-Rollensteuerung unverändert. Er verweigert
einen Model-A/B-Vergleich, wenn beide Berichte dieselbe Identität haben.
Der **Dateiname** gilt ausdrücklich nicht als Modellnachweis.

## Was die Suite untersucht

8 synthetische Szenarien mit ausschließlich erwachsenen, einvernehmlichen
Figuren, etwa:
- langsamer Spannungsaufbau nach einem Wiedersehen
- erotische Direktheit und Dialog ohne Ausweichen oder moralische Kommentare
- uneingeschränkt respektiertes Nein
- ausdrückliche stilistische/lexikalische Einschränkungen
- aktives respektvolles Einverständnis
- Rollenspiel in genau einer Rolle ohne Übernahme der Nutzerfigur
- Merken von Details aus einem fiktiven Gespräch
- glaubwürdige Gefühle und Ambivalenz

**Keine Minderjährigen, sexuelle Gewalt, Nötigung oder Inzest.** Der
Benchmark ist kein Mittel, solche Inhalte anzufordern.

Alle acht Fälle erfordern menschliche Beurteilung; es gibt **keine
automatische NSFW-Erfolgsquote**. Bewertet werden je 1–5 Punkte:

| Achse | Bewertung |
| --- | --- |
| deutsch | natürliches korrektes Deutsch |
| dialog | glaubwürdige Figuren, Dialog und Immersion |
| stiltreue | gewünschte Intensität/Länge/Perspektive, keine verbotenen Stilmittel |
| kontinuitaet | konsistente Beziehungen, Fakten und Szene |
| grenzen | erwachsene, einvernehmliche Situation; Grenzen respektiert |

Die Gesamtzahl ist lediglich der Durchschnitt deiner persönlichen Rubrikwerte.
Am besten beide anonymisiert und möglichst in einem Durchgang bewerten, um
Modellpräferenzen nicht unbewusst einfließen zu lassen.

## Bedienung auf dem Mac

**Voraussetzungen:** Nobby-Agent (8010) und Chatserver (8000) erreichbar.
**Nach dem Git-Pull unbedingt `./scripts/mlx agent restart` aufrufen:** Der
Benchmark prüft `stream_model_pin_supported` der tatsächlich laufenden
Agent-Version. Ein alter Prozess ohne diese Unterstützung wird sicher
abgelehnt, damit keine Chat-Rollenumschaltung erfolgt.
Keine sonstigen KI-Jobs während der Messung. Weder lädt noch wechselt das
Benchmark-Skript Modelle und es verändert keine Performanceprofile.

### 1) Tatsächlich Qwen3.8 als Baseline starten/prüfen

Falls Qwen3.8 bereits aktiv ist, nichts ändern. Ansonsten bei Leerlauf
bewusst Qwen wählen:

    ./scripts/mlx model "$HOME/Models/Qwen3.8-27B-Abliterated-MLX-4bit"

Konkreten Modellstatus prüfen:

    ./scripts/mlx model
    ./scripts/mlx status

Ersten Lauf starten (es entstehen zwei **neue** private Dateien):

    ./scripts/mlx benchmark chat-nsfw run \
      --expect-model Qwen3.8 \
      --output /tmp/nobby-nsfw-qwen38-1.json \
      --review-file /tmp/nobby-nsfw-qwen38-answers-1.json

Die 8 Antworten werden im **review-file** gespeichert, das Modell wird weder
umgeschaltet noch gestartet.

### 2) Bewusst Dark Scarlett aktivieren

Vor einem anderen Chatmodell experimentelle Qwen-Hybrid-Profile deaktivieren,
solange keine aktiven Jobs laufen:

    ./scripts/mlx chat-profile status
    ./scripts/mlx chat-profile default

Dann bewusst den schon registrierten/geladenen Kandidaten aktivieren:

    ./scripts/mlx model dark-scarlett-27b
    ./scripts/mlx status

Wenn die API nicht läuft, nicht benchmarken! Im Startlog nachsehen.
Nach erfolgreichem Modellstart:

    ./scripts/mlx benchmark chat-nsfw run \
      --expect-model Dark-Scarlett \
      --output /tmp/nobby-nsfw-scarlett-1.json \
      --review-file /tmp/nobby-nsfw-scarlett-answers-1.json

**Wichtig:** Wird weiterhin Qwen3.8 vom Agenten gemeldet, wird dieser
Lauf **abgelehnt**, statt eine falsche Dark-Scarlett-Punktzahl zu erzeugen.
Die Tests ändern keine gespeicherten `model-roles.json`-Rollen. Das ist
wichtig: Die Chat-Rolle kann bei normaler Bedienung weiterhin Qwen wählen,
obwohl `./scripts/mlx model dark-scarlett-27b` ausdrücklich Dark Scarlett
für den Runtime-Server gesetzt hat. Die Testanfragen respektieren stattdessen
die aktuell aktive Modell-ID + Prozess-ID. Alte **unvollständige** Dark-
Scarlett-Berichte bleiben unbrauchbar; für neue Versuche neue Dateinamen nutzen.

### 3) Beide Antworten lokal selbst bewerten

    ./scripts/mlx benchmark chat-nsfw score \
      --report /tmp/nobby-nsfw-qwen38-1.json \
      --review-file /tmp/nobby-nsfw-qwen38-answers-1.json \
      --output /tmp/nobby-nsfw-qwen38-scores-1.json

    ./scripts/mlx benchmark chat-nsfw score \
      --report /tmp/nobby-nsfw-scarlett-1.json \
      --review-file /tmp/nobby-nsfw-scarlett-answers-1.json \
      --output /tmp/nobby-nsfw-scarlett-scores-1.json

Die CLI zeigt die lokalen Modelltexte **nur zur gewollten Sichtung
im Terminal** an und fragt pro Fall fünf Werte von 1 bis 5 ab.
Es werden keine persönlichen Chatdaten eingesammelt.

### 4) Offline vergleichen

    ./scripts/mlx benchmark chat-nsfw compare \
      --baseline /tmp/nobby-nsfw-qwen38-1.json \
      --candidate /tmp/nobby-nsfw-scarlett-1.json \
      --baseline-scores /tmp/nobby-nsfw-qwen38-scores-1.json \
      --candidate-scores /tmp/nobby-nsfw-scarlett-scores-1.json \
      --output /tmp/nobby-nsfw-comparison-1.json

Das Ergebnis zeigt die echte Modellidentität, Mittelwerte pro Bewertungsachse,
deren Unterschiede und die mediane Ersttext-Latenz. Es bleibt immer
**HUMAN_REVIEW_REQUIRED**: eine subjektive Einschätzung, kein allgemeiner
Leistungs- oder Sicherheitssieger.

## Datenschutz und Fairness

- Live-Generierung ausschließlich via bestehender Agent-Loopback-URL,
  Runtime-Lease, Model-PID- und Idle-Schutz; keine Netzwerkweiterleitung.
- Die beiden **Hauptberichte** enthalten nur IDs, Timing, Runtime-Identität
  und Metadaten. Sie enthalten **keine** Prompts oder Antworten.
- Review-Dateien sind ausdrücklich **sensible lokale Inhalte**; niemals
  in Git einchecken, per Screenshot teilen oder öffentlich hochladen.
  Review- und Bewertungsdateien werden ausschließlich **auf Wunsch** erzeugt.
- Ausgabedateien werden **exklusiv**, ohne Überschreiben oder Symlinks,
  mit Dateirechten \`0600\` angelegt. Für Wiederholungen neue Namen wählen.
- Abbrüche ergeben \`partial\`. Ein solcher Lauf ist nicht vergleichbar.
  Raw-Agentfehler werden nicht in Hauptberichte übernommen.
- Beide Läufe müssen exakt dieselbe Suite/SHA und Generierungsparameter
  benutzen; der Modellname muss **verschieden** sein. Gleiche Temperatur
  bedeutet nicht exakt gleiche Sampling-Implementierung.
- Die Resultate messen textbasierte Rollen-/Stilqualität in wenigen
  Szenarien, **nicht** allgemeine Intelligenz, explizite Inhaltsfreiheit
  oder Robustheit sämtlicher NSFW-Nutzungsfälle.
- Zunächst einen echten Lauf auf dem Mac vornehmen; CI generiert
  keine Erwachsenen-Inhalte und lädt keine Modellgewichte.

## Regressionstests ohne echte Generierung

    python3 -m pytest -q tests/test_chat_nsfw_benchmark.py
    python3 scripts/benchmark-chat-nsfw.py --help
