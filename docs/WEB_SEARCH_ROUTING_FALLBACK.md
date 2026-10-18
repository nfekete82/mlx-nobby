# Websuche: Router-Guard für normale Chat-Folgefragen

## Problem
Der normale Browser-Chat routete sogar „Antworte ohne Werkzeuge oder
Websuche: Welche Rolle spielt der KV-Cache?“ zu `web_search`. Wenn
SearXNG keine Treffer lieferte, wurde eine leere Suchmeldung statt einer
Modellantwort angezeigt. Das kann Chatqualität und APC-Messungen verfälschen.

## Änderung
- Text-Chat mit explizitem Verzicht auf Websuche/Tools überspringt den
  semantischen Tool-Router und ruft das lokale Chatmodell auf.
- Kontextbezogene Folgefragen mit Rückverweisen wie „gerade erklärt“
  benutzen das lokale Modell, solange keine explizite Live-Informations-
  anforderung vorliegt.
- Eine versehentlich gestartete, erfolglose Websuche fällt bei
  nicht-zeitkritischen Wissensfragen auf eine lokale Modellantwort zurück.
- Wetter, tagesaktuelle Nachrichten, Preise/Kurse und andere aktuelle
  Fragen behalten ihr bisheriges Quellenverhalten.
- Bild-, Video- und Dokumentkontexte bleiben unverändert. Kein APC-Tuning,
  kein Eingriff in Cache-Keys oder Speichergrenzen.

## Lokale Prüfung

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/fix/web-search-routing-fallback
./test-venv/bin/python -m pytest -q tests/test_web_search_routing_fallback.py
docker compose up -d --build --no-deps mlx-web
```

Im selben Chat fragen:
1. „Erkläre mir den Transformer.“
2. „Welche Rolle spielt der KV-Cache bei dem gerade erklärten Transformer?“
3. „Antworte nur aus deinem Modellwissen, ohne Werkzeuge oder Websuche:
   Erkläre den KV-Cache.“

Anschließend gezielt eine explizite Websuche und eine Wetterfrage testen.
Cache vor/nach dem reinen Chat mit `/v1/cache/stats` vergleichen.

**Limitation:** Die Regeln sind ein gezielter Browser-Guard, kein vollständiger
serverseitiger Router-Fix. Für alle API-Clients wäre zusätzlich die
serverseitige Routingpolicy zu testen. Browser- und Hardwaretests müssen
noch lokal ausgeführt werden.
