# Chat Quality v1 – Abschluss des ersten Mac-Baselineschritts

**Status: abgeschlossen als Testwerkzeug, kein weiteres allgemeines Modell-
Leaderboard geplant.** Der ursprüngliche Chat-Quality-v1-PR
[#302](https://github.com/nfekete82/mlx-nobby/pull/302) wurde bereits
gemergt. Das Werkzeug bleibt als optionaler Regressionstest bestehen.

## Beobachtete Ergebnisse (vom Anwender bereitgestellte lokale Ausgaben)

| Messwert | Vollständiger Durchlauf A | Vollständiger Durchlauf B |
| --- | ---: | ---: |
| Tatsächliche Modellfamilie | Qwen3.8-27B Abliterated MLX 4-bit | **dieselbe** Qwen3.8-27B-Variante |
| Automatisch korrekt | 42/44 = 95,45 % | 42/44 = 95,45 % |
| Deutsch / PHP / JavaScript / SQL | je 8/8 | je 8/8 |
| Logik/Arithmetik | 7/8 | 7/8 |
| Kontexttreue | 3/4 | 3/4 |
| Erstes sichtbares Content-Zeichen p50 | 186,194 ms | 186,329 ms |
| Gesamtdauer p50 | 341,809 ms | 335,368 ms |
| Erstes Content-Zeichen p95 | 246,229 ms | 234,678 ms |
| Gesamtdauer p95 | 4179,001 ms | 4243,923 ms |
| Manuelle Review-Aufgaben | 4 unbearbeitet | 4 unbearbeitet |

**Wichtig:** Obwohl die zweite Ausgabedatei im Namen „qwen36“ enthielt,
weist ihr Bericht ausdrücklich **Qwen3.8** als aktives Modell aus.
Daher gibt es **keinen** Qwen3.8-gegen-Qwen3.6-Vergleich. Die beiden
Läufe zeigen nur eine hohe Reproduzierbarkeit dieses **kleinen**
synthetischen Testsatzes für dasselbe Modell und die damaligen Einstellungen.

In beiden Läufen sind exakt die Fälle `logic-profit` (Erwartungswert
`60`) und `context-chain` (Erwartungswert `Schublade`) falsch
klassifiziert. Weil der Hauptbericht die rohen Modellantworten nicht
speichert, lässt sich daraus **nicht** ableiten, ob es inhaltliche Fehler
oder lediglich Verletzungen des strengen `{"answer":"..."}`-Protokolls
waren. Keine Score-Korrektur ohne Antwortbelege.

## Entscheidung

1. Baseline und reproduzierbaren `run`/`compare`-Befehl im Repository
   behalten; keinen globalen Intelligenz-Score daraus ableiten.
2. Das Testwerkzeug gilt als **implementiert und getestet**. Es wird nicht
   zum eigenständigen großen Leaderboard-Projekt ausgebaut.
3. Bei künftigen *konkreten* Modellwechseln kann `chat-quality compare`
   weiter als schnelle Regression dienen, sofern beide tatsächlichen
   Modellidentitäten in den Reports überprüft werden.
4. Spezialisierte Modellvarianten benötigen eigene, passend bewertete
   Testfälle und separate Kompatibilitäts- und Qualitätsprüfungen.
5. Keine Einträge in den dauerhaften Model-Evaluations-Entscheidungen
   erzeugen: Vergleiche mit anderen Modellen sind durch diese Ergebnisse
   nicht begründet.

Die erfassten Daten sind gerundete, vom Nutzer gezeigte **Summen**.
Private Mac-Pfade, persönliche Texte oder lokale rohe Antwortdateien werden
nicht in Git eingecheckt. Für tatsächliche Generalisierbarkeit und
Produktionsqualität ist dieser Testsatz zu klein.
