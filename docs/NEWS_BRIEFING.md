# Nachrichten-Kurzbriefings

Die bestehende News-Pipeline prüft zunächst Veröffentlichungsdatum,
Originallink, geladenen Artikeltext, Themenbezug und Duplikate.
Erst danach werden für das Frontend kurze Auszüge gebildet.

## Neu: Leseansicht

- `message.news_digest` aktiviert ausschließlich für News-Briefings die
  kompakten Trennlinien und zusätzlichen Zeilenabstände.
- Alle anderen Chat-Antworten bleiben optisch unverändert.
- Die Originalartikel bleiben verlinkt; Quellenzeiten bleiben sichtbar.

## Neu: lokale KI-Umformulierung

- `agent/news_briefing.py` erstellt aus bis zu fünf bereits geprüften
  Originalauszügen **einen gebündelten Modellaufruf** (Qwen im vorhandenen
  Agent-Modellpfad; kein neues Modell).
- Das Modell erhält lediglich Überschrift und belegten Originalauszug.
  Es darf keinen neuen Fakt erfinden; insbesondere neue Zahlen/Datumsangaben,
  starke thematische Abweichungen und neue Namen werden konservativ abgelehnt.
- Bei ungültigem JSON, fehlendem Modell, Ablehnung oder zu wenig Text
  bleibt der ursprüngliche wörtliche Auszug unverändert.
- Der Text kennzeichnet explizit, wenn Teile lokal durch KI umformuliert
  wurden. Dies ist **keine unabhängige Faktenprüfung**.

Um die lokale Umschreibung abzuschalten, vor Start des Agenten
`MLX_NEWS_AI_SUMMARIES=0` setzen. Standardmäßig aktiviert.

## Tests

```bash
test-venv/bin/python -m pytest -q \
  tests/test_news_briefing.py \
  tests/test_news_intelligence.py \
  tests/test_today_news_freshness.py \
  tests/test_news_query.py
node --check frontend/assets/chat/rendering.js
```

Es werden keine Artikel in ein externes Modell übertragen. Die Kurztexte
gehen ausschließlich an die bereits konfigurierte lokale Modellpipeline.
