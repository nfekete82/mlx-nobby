# Kontextoptimierung: automatische, nichtdestruktive Komprimierung

## Ausgangslage

Der bisherige Schalter **Automatische Komprimierung** sendete ab 80.000
Zeichen den Verlauf an `/api/chat/compact` und ersetzte anschließend
`session.messages` (inklusive der sichtbaren Chat-Historie und Persistenz)
durch **eine** System-Zusammenfassung und die letzten zwölf Nachrichten.
Dadurch konnten ältere Nachrichten, Anhangsbezüge und editierbare Details
verloren gehen. Bei weiteren langen Runden wurde erneut komprimiert.

## Neue Ausführung

* Der vollständige sichtbare und persistierte Chatverlauf bleibt **unverändert**.
* Ab 80.000 Textzeichen und mindestens 20.000 Zeichen älterer Geschichte
  wird die schon vorhandene lokale Zusammenfassungs-API aufgerufen.
* Nur einfache Textgespräche ohne Coding-Blöcke, Dateianhänge, Jobs oder
  Tool-Ergebnisse sind zulässig. Das ist bewusst konservativ; riskante
  Kontexte behalten den gesamten Wortlaut.
* Das Ergebnis ist nur verwendbar, wenn die Antwort strukturell vollständig
  ist, ihr jüngster Zwölf-Nachrichten-Anteil exakt übereinstimmt und der
  Textumfang gegenüber dem Original mindestens 20 % kleiner ausfällt.
* Der ältere Teil wird ausschließlich in der **ausgehenden Modellanfrage**
  durch eine Archiv-Zusammenfassung in einer User-Nachricht ersetzt.
  Die zwölf aktuellsten Nachrichten bleiben wörtlich erhalten.
* Der Cache bleibt nur im Browser-RAM und ist an das konkrete Chatobjekt und
  den unveränderten Nachrichtenpräfix gebunden. Neue Folgerunden dürfen den
  Cache für maximal zwölf weitere Nachrichten wiederverwenden, bevor erneut
  zusammengefasst werden muss. Editierte/ersetzte Nachrichten, deaktivierte
  Auto-Komprimierung sowie Datei-/Codekontexte fallen sofort auf den
  Originalverlauf zurück.
* Mehrere gleichzeitige Anfragen für dieselbe Sitzung teilen sich einen
  laufenden Komprimierungsaufruf. Bei Fehlern oder ungültigem Ergebnis wird
  ohne Datenverlust die bisherige vollständige Inferenz benutzt.

Die Option **Automatische Komprimierung** bleibt der bestehende Schalter
in Einstellungen. Die explizite, manuell vom Benutzer gestartete
Komprimierung bleibt unverändert: Diese ersetzt weiterhin den sichtbaren
Verlauf. Die neue Schonung gilt ausdrücklich **für die Automatik**.

## Sicherheit, Grenzen und Performance

Eine Modellzusammenfassung ist nicht garantiert vollständig. Deshalb werden
Code, lokale Projekte mit Dateianhängen, Toolzustände und andere strukturierte
Geschichten nicht automatisch zusammengefasst. Bei nicht eindeutig sicherem
Inhalt gilt: lieber langsamer, aber vollständig.

Der erste automatische Summary-Aufruf ist nach wie vor ein **zusätzlicher**
Modellaufruf und kostet Zeit. Die Einsparung entsteht bei nachfolgenden
Inferenzrunden durch weniger wiederholte Eingabetokens und Wiederverwendung
der Zusammenfassung; sie hängt von den tatsächlich verwendeten Modellen und
Chatverläufen ab. Es gibt **keinen gemessenen End-to-end-Speedup** durch
diesen Commit allein. Tokenzahlen werden hier nur näherungsweise durch
Zeichenlängen erfasst, nicht durch echte Tokenizer-Tokens.

Kein neues Backend, kein zusätzliches Modell, keine Datenübermittlung in
die Cloud und keine Änderung der 90-%-RAM-Admission oder DFlash2-Konfiguration.
Eine Browser-Aktualisierung löscht den flüchtigen Cache, nicht den Chatverlauf.

## Prüfen

```sh
node --test tests/test_context_preserving_compact.mjs
python3 -m pytest -q tests/test_chat_runtime_integration.py tests/test_chat_gateway_offload.py
```

Testmatrix: unveränderte Chatnachrichten und Objektreferenzen,
ausgehende Komprimierung, Wiederverwendung, Edit-Invalidierung,
Datei-/Code-/Tool-Bypass, schlechte/fehlerhafte Summary,
Session-Clear während des Requests und gleichzeitige Requests.

Für echte Performance-Werte: Einen langen, rein textbasierten Chat
mit identischen Eingaben vor/nachher vergleichen; Observatory-TTFT,
Modell-Prefill, Zeichenmenge und Gesamtlatenz dokumentieren. Wegen
zusätzlicher Summary-Aufrufe die erste Runde separat betrachten.
