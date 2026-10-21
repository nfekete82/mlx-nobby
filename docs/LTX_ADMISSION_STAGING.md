# LTX Admission: Quellcode übernommen, Produktion nicht aktiviert

Stand 21.10.2026, Branch `feature/ltx-performance-lab-v017`.

Die acht Module unter `ltx_lab/` wurden aus der vom Nutzer bereitgestellten
Entwicklungs-ZIP übernommen: `admission`, `exclusive`, `guarded_serve`,
`offline`, `queue_admission`, `service_recovery`, `services`, `session`.
Sie sind **nur vorbereiteter Quellcode**. Weder der produktive MLX-Q4-Worker
noch LaunchAgents, Chat-/Router-Lifecycle, MuseTalk oder Modelle werden verändert.

## Was geprüft wurde
- Python-Syntax aller gelieferten Module und Tests (ohne GPU-Aufruf).
- 40 ausgewählte CPU-Tests aus der beigefügten Admission-Testsuite in einer
  isolierten Prüfstruktur; das dortige Telemetrie-Modul war ein Stub.
- Zusätzlich gibt es eine eigenständige kleine Regressionstestsuite
  `tests/test_ltx_admission_core.py` zur Gate-/Proof-Fail-Closed-Logik.
- Nicht nachgewiesen: vollständige Testparität mit dem produktiven Setup,
  Mac-LaunchAgent-Verträge, offizielle GPU-Sitzung, End-to-End-Recovery.

## Warum der Live-A/B-Test weiterhin gesperrt ist

Die vorhandenen produktiven Listener bieten `/lab/admission` nicht an
(Chat: HTTP 404). Der Admission-Launcher unterstützt inzwischen auch den bestehenden
`-m model_lifecycle_launcher` (Chat mit aktivem Lifecycle). Die
Chat- und Router-Startskripte besitzen nun den **standardmäßig abgeschalteten**
Schalter `LTX_LAB_ADMISSION=1`. Chat lehnt damit nicht unterstützte
Hybrid-/Audit-Launcher und das `mlx_lm`-Backend ab.
**Produktive LaunchAgents und ihre Umgebungen bleiben unverändert.**

Hinzu kommt: `ltx_lab.exclusive.verify_services` verlangt für alle
laufenden Listener, darunter auch Port 11234, eine identische Gate-/Build-
und PID-Proof-Implementierung. Ein provisorischer `/lab/admission`-Handler
ohne echte Sperr- und Aktivitätskontrolle ist ausdrücklich verboten.

Die gelieferten Tests `test_ltx_lab_session.py` referenzieren außerdem
`ltx_lab.cli`- und `ltx_lab.telemetry`-Schnittstellen aus einer späteren
lokalen Entwicklungsfassung, die in dieser ZIP nicht enthalten waren.
Daher wurden diese beiden ursprünglichen Testdateien **nicht** als
vorgeblich grüne Branch-Regressionen eingecheckt. Ihre lokalen Originale
dürfen nicht überschrieben werden.

**Verbleibender Blocker:** Das externe `mlx-serve`-Binary (Port 11234)
nutzt den Python/ASGI-Startpfad nicht. Auch Agent, Embeddings, Image,
Speech, Video und MuseTalk benötigen eine vollständige, verifizierte
Admission-/Queue-Anbindung. Einen künstlichen `/lab/admission`-Endpoint
einzubauen wäre kein wirksamer Schutz. Vor einem echten GPU-Lauf sind
gemeinsame Admission-, Recovery- und Offline-Start-Abnahme erforderlich.

## Sicherheit
- `scripts/ltx-ab-once-safe.py` bleibt bis dahin fail-closed.
- Keine automatische Abschaltung oder Restart von Diensten.
- Keine Änderung an lokaler `.ltx-lab/`-Arbeit, Modellen oder Konfigs.
- Bestehende uncommittete Arbeit auf `main` **nicht** stashen/resetten.
- CPU-Tests in separatem Git-Worktree möglich, aber *keine* GPU-Freigabe.

Gezielter CPU-Test (nur in sauberer Arbeitskopie):

```bash
python3 -B -m pytest -q tests/test_ltx_admission_core.py
```

## Abschlussprüfung ohne GPU oder Dienstneustart

`python3 -B scripts/ltx-release-readiness.py --lab-root ~/mlx-web/.ltx-lab` prüft nur die zwei isolierten Runtime-Pins, die bestehende globale Listener-Admission sowie die Speicher-Freigabe. Das Skript führt **keine** Lastgenerierung, Modell-Downloads, `launchctl`-Kommandos oder Schreiboperationen an produktiven Modelldateien aus. Ergebnis bleibt **NO-GO**, solange der Runtime-/Admission-Nachweis oder der noch ausstehende End-to-End-Recovery-/GPU-/Qualitätsnachweis fehlt. Es gibt absichtlich keinen unsicheren `--force`-Modus.

