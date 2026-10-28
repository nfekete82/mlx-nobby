# Interaktive Rückfragen im Chat

MLX-Nobby unterstützt interaktive Rückfragen als optionale Erweiterung des bestehenden Chat-Streams. Es ist kein separater Modell- oder Backend-Dienst nötig.

## Einstellungen

Chat → Einstellungen → Chat-Verhalten → Interaktive Rückfragen:

- Automatisch (Standard): Bei mindestens zwei unabhängigen, relevanten Informationslücken einen Fragebogen anbieten, sonst direkt antworten.
- Bevorzugt nachfragen: Bei komplexen, offenen Aufgaben mit fehlenden Präferenzen häufiger Fragen stellen.
- Aus: Keine Aufforderung an das LLM, Fragekarten zu erzeugen.

Die Einstellung wird lokal als mlx-nobby-interactive-questions-mode-v1 im Browser gespeichert.

## Schema

Ein Fragebogen wird als Markdown-Codeblock mit der Sprachkennung nobby-questions und gültigem JSON übertragen. Beispiel:

    {
      "title": "Drei Fragen zum Vorgehen",
      "description": "Damit ich deine Prioritäten berücksichtigen kann.",
      "questions": [
        {"id":"q1","label":"Was hat Vorrang?","type":"single","options":["Zeit","Kosten"]},
        {"id":"q2","label":"Welche Bereiche?","type":"multiple","options":["Frontend","Backend"]},
        {"id":"q3","label":"Weitere Hinweise?","type":"text","required":false}
      ],
      "footer": "Die Auswahl wird im Gespräch ausgewertet."
    }

Types: single (Radiobuttons), multiple (Checkboxen), text (Freitext). required ist standardmäßig true. Maximal vier Fragen akzeptiert der Parser, der Prompt fordert höchstens drei. Auswahlfragen benötigen zwei bis acht eindeutige Optionen; JSON ist auf 12 KB begrenzt. Texte werden stets über textContent und nicht als ungesichertes HTML eingesetzt.

## Technischer Ablauf

1. Der Chat ergänzt den bestehenden System-Prompt abhängig vom Modus um die Formatanweisung.
2. Der Renderer erkennt vollständige und gültige JSON-Codeblöcke und baut DOM-Steuerelemente; während des Streamings wird unvollständiges JSON vorübergehend verborgen.
3. Ausgewählte Antworten bleiben bei erneuter Darstellung der Nachrichten erhalten.
4. Beim Absenden werden Pflichtfragen validiert, interactive_answers in der Assistant-Nachricht gespeichert und die Angaben als normale User-Nachricht durch sendMessage() verarbeitet.
5. Überspringen sendet eine Bitte um eine direkte Antwort. Bereits gesendete Karten sind schreibgeschützt.
6. Aktive Chat-Generierung, offene Chat-Entwürfe, Anhänge und veraltete Sitzungen blockieren unerwünschte Übermittlungen.

## Tests

    node --check frontend/assets/chat/interactive-questions.js
    node --test tests/test_chat_interactive_questions.mjs
    node --test tests/test_chat_charts.mjs tests/test_chat_sessions.mjs tests/test_sse_stream.mjs

Die GitHub-Actions-Testsuite prüft zusätzlich JavaScript-Syntax und alle tests/*.mjs.

## Grenzen

Die Erzeugung ist LLM-basiert und daher nicht deterministisch. Ungültige oder unvollständige Codeblöcke fallen auf normale Textdarstellung zurück. Die Antworten bleiben in der üblichen Chat-Historie; es werden keine gesonderten Profile oder Diagnosen erstellt.