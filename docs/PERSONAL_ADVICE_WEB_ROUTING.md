# Persönliche Beratung darf nicht in einer leeren Websuche enden

## Gemeldeter Fehler

Beispiel: Eine Person schildert eine Meinungsverschiedenheit mit ihrem
Chef über O2-Angebote, Newsletter, Besucher-Absprünge und Preis-Feedback.
Nobby antwortete lediglich mit "Die Websuche hat keine passenden
Ergebnisse gefunden." Eine öffentliche Recherche war nicht verlangt.

Zwei Ebenen sind beteiligt:

1. Der semantische Router darf bei längeren persönlichen Schilderungen
   nicht allein aufgrund der Wörter "Webseite", "Preise", "Statistiken",
   "jetzt" usw. eine Websuche auslösen.
2. Das Frontend beendete eine \`web_search\`-Aktion mit null Ergebnissen
   bislang immer mit dem generischen Fehlertext. Eine lokale Antwort auf
   eine aus dem Nutzertext beantwortbare Beratungsfrage blieb aus.

## Änderung

- \`agent/personal_advice_routing.py\` erkennt mit konservativen,
  regelbasierten Merkmalen persönliche Schilderungen (z. B. Chef,
  Kollegin oder Angehörige + eigene Erfahrung), *ohne* ausdrückliche
  Anfrage nach externen Fakten oder Quellen.
- Der Routingpfad wählt hierfür \`normal_chat\`. Angehängte Dateien,
  Coding-/Agent-Aufträge, explizite aktuelle Recherche und
  Medienoperationen behalten ihre bisherigen spezialisierten Pfade.
- Falls eine fälschlich geroutete \`web_search\` trotzdem leer
  zurückkommt, darf ausschließlich der Agent selbst den Bool-Wert
  \`empty_search_chat_fallback: true\` an den Toolresult-Daten ergänzen.
- Nur bei **erfolgreicher, wirklich leerer** Websuche und diesem
  ausdrücklichen Kennzeichen ruft das Frontend die normale lokale
  Chat-Generierung mit unverändertem Nutzertest und Gesprächsverlauf
  auf. Die Seite speichert keine künstlichen Webbelege.
- News-/Wetteranfragen, echte Web-Recherche, zeitkritische Preis-/
  Faktenfragen und nicht verifizierte Ergebnisse bleiben beim bisherigen
  ergebnislosen Verhalten. Es werden keine aktuellen Fakten erfunden.

## Prüfung

    python3 -m pytest -q tests/test_personal_advice_routing.py
    node --test tests/test_personal_advice_web_fallback.mjs

Nach einem Git-Pull den Agent neu starten und die aktualisierte
Weboberfläche bereitstellen; alte Frontend-Container oder Browser-Caches
laden andernfalls noch die bisherige Generation-Logik. Bestehende
Gesprächshistorie wird nicht verändert.

Der Routing-Guard ist bewusst konservativ, kein allgemeiner Ersatz für
das semantische Routing. Für andere fälschlich geroutete Fragen sind
weitere gezielte Regressionstests sinnvoll.
