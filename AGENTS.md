# Repository instructions

## Git commit attribution

- Do not add `Co-authored-by` trailers to commit messages.
- Do not add `Signed-off-by` or other attribution trailers unless explicitly requested.
- Use only the repository's configured Git author identity for commits.

## Projektweite Entwicklung: Execution First

**Ziel:** Die angeforderte Funktion tatsächlich fertigstellen – keine Diagnose-, Test- oder Commit-Endlosschleifen.

1. Bekannten Projektkontext nutzen. Nur fehlende, entscheidende Informationen erheben.
2. Bestehende Implementierung wiederverwenden; keine unnötigen Frameworks, Wrapper, Refactorings oder Nebenfeatures.
3. Ein zusammenhängender Implementierungsdurchlauf statt vieler Mini-Patches und Zwischencommits.
4. Standardmäßig höchstens zwei Testphasen: ein praxisnaher Funktions-/Integrationstest und ein gezielter Regressionstest. Mehr nur bei konkreten Fehlern oder Sicherheitsrisiken.
5. Nach erfolgreicher Validierung abschließen, nicht erneut dieselbe Architektur untersuchen.
6. Vorhandene uncommittete Arbeit, Konfiguration, Modelle, Daten und laufende Dienste erhalten. Niemals unaufgefordert `git reset`, `git clean`, Löschungen oder Neustarts.
7. Einen sinnvollen Commit pro abgeschlossener Funktion erstellen, nur bewusst ausgewählte Dateien stagen.
8. Code und Terminalbefehle möglichst in einem ausführbaren Block liefern; keine unnötigen Rückfragen.
9. Abschluss eindeutig kennzeichnen: **FERTIG**, **TEILWEISE** oder **BLOCKIERT**, mit Begründung und nächstem konkreten Schritt.
10. Wenn zwei aufeinanderfolgende Schritte keinen nutzbaren Implementierungsfortschritt liefern, Ansatz wechseln.

**Sicherheit hat Vorrang:** Keine aktiven Requests/Streams abbrechen oder unbekannte Runtime-Zustände ignorieren. Neue riskante Modellsteuerung nur opt-in, zuerst isoliert testen. Sicherheitskritische Prüfungen sind nicht durch ein Testbudget begrenzt.

Leitsatz: *So wenig Tests wie sinnvoll möglich, so viele wie tatsächlich nötig.*
