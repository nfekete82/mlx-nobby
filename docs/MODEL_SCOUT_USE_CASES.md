# Model Scout: Einsatzgebiete statt irreführender Upgrade-Versprechen

Der Discovery-Score beruht auf Aktualität, Popularität und einer groben
RAM-Schätzung. Er ist **kein Qualitätsbenchmark und kein Upgrade-Beleg**.
Daher zeigen die Kandidatenkarten den möglichen Einsatzzweck und
kennzeichnen interessante Funde nicht mehr als belegtes Upgrade.

Ergänzte Rollen: Chat, Coding, Vision, TTS/Sprachausgabe,
ASR/Transkription, Audioverständnis, Langzeitgedächtnis-Schreiber,
Embeddings, Reranking sowie Bild- und Videogenerierung.

Die Zuordnung wird aus Modellname und Hugging-Face-Tags **abgeleitet**,
nicht durch einen realen Adapter-/Leistungstest bestätigt. Spezialisierte
Modelle dürfen nicht versehentlich als Chatmodell hinzugefügt oder über
den Chat-A/B-Test gestartet werden. Nicht-Chat-Einträge zeigen nur ihren
Einsatzbereich und einen Link zur Modellkarte. Integration in Speech,
Embedding, Bild-/Video- oder Gedächtnisdienste bleibt eine separate Aufgabe.

Beispiele:
- Hy-Memory-30B-A3B: Langzeitgedächtnis schreiben, kein allgemeines Chat-Upgrade.
- fish-audio-drama-3: Sprachausgabe/TTS, kein allgemeines Chat-Upgrade.
- Ming-3.0-tts: Sprachausgabe/TTS.
- Ming-3.0-asr: Sprache erkennen.
- Molmo2: Bildverständnis.

Diese Änderung lädt nichts herunter, verändert keine Modellzuordnungen und
startet keine KI-Dienste. Branch stammt direkt von main, ohne LTX-0.17.0
oder andere parallel laufende Änderungen.
