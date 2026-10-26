# Lokale EML-Stapelverarbeitung (erste Version)

Im Chat links auf den Umschlag klicken oder `http://127.0.0.1:8090/eml-anonymisierung` öffnen. Mehrere `.eml` oder einen Ordner auswählen und importieren. Nobby lädt jede Datei einzeln hoch, speichert sie im Docker-Volume `nobby-eml-data`, und verarbeitet die SQLite-Warteschlange sequenziell. Beim nächsten Statusabruf nach einem Neustart werden wartende/unterbrochene Jobs fortgesetzt. Über `Anonymisierte EMLs als ZIP` lassen sich die Ergebnisse herunterladen.

## Sicherheitsgrenzen

- **Nur ein regelbasierter Pseudonymisierungs-Prototyp:** Namen können im Fließtext, in Zitaten, bei freier Schreibweise und in Signaturen übersehen werden. Identifizierbarkeit kann weiterhin gegeben sein. Kein ausreichender Nachweis für DSGVO-konforme Anonymisierung.
- Originale und SQLite-Jobdaten bleiben lokal gespeichert; Dateien werden nicht automatisch gelöscht. Den Docker-Datenträger schützen und Originale niemals als anonymisierte Exporte behandeln.
- Neue minimale EML mit Betreff und Plaintext-Body; originale From/To/Cc/Message-ID/Date/HTML/MIME-Header werden nicht übernommen. Anhänge werden vollständig verworfen, nicht anonymisiert. Enthaltene EML-Zitate im Body können private Details behalten.
- Größenlimit 25 MiB je Datei. Der bestehende LocalRequestGuard begrenzt HTTP-Anfragen und schützt gegen fremde Browser-Origin-Zugriffe. Kein Schutz gegen andere lokale Prozesse mit Zugriff auf Docker.
- Der ZIP-Export enthält nur als `done` markierte Dateien und einen expliziten Prüfhinweis. Vor jeder externen Weitergabe manuelle Einzel- oder risikobasierte Qualitätsprüfung.

## Deployment

```bash
cd "$HOME/mlx-web"
git fetch origin main
git merge --ff-only origin/main
MLX_NOBBY_BUILD_SHA="$(git rev-parse --short HEAD)" docker compose up -d --build mlx-web
curl -fsS http://127.0.0.1:8090/api/mlx/eml/status
```

## Tests

```bash
./scripts/mlx test-quick tests/test_eml_anonymization.py
```

Nicht Teil dieser Version: FAQ-Extraktion, lokales LLM/NER, automatische Anhangsbereinigung, garantiert vollständige Namens- und Adressanonymisierung, anwendungsgesteuerte Löschfristen.
