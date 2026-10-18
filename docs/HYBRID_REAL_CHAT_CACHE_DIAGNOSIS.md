# Diagnose: APC-Hits in echten Chat-Anfragen

Das aktuelle Hybridprofil speichert Exact-Cache-Snapshots, aber in einigen
Frontend-Chats steigen `exact_stores`, ohne dass `exact_hits` steigt.
Der bisherige synthetische Longform-Test hat echte APC-Treffer bewiesen.
Das ist **noch kein Beweis**, dass Frontend-/Agent-Prompts unverändert sind.

## Read-only Probe über die produktive Agent-API

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/diag/hybrid-real-chat-cache
./test-venv/bin/python -m pytest -q tests/test_diagnose_hybrid_agent_cache.py
./scripts/mlx chat-profile status
python3 scripts/diagnose-hybrid-agent-cache.py \
  --output /tmp/nobby-hybrid-agent-diagnosis.json
./scripts/mlx chat-profile status
```

Der Probeaufruf benötigt ein bereits gestartetes Hybrid-Profil und einen
freien Agent/Media-Runtime-Lease. Er verändert weder Profil noch Konfiguration,
sendet aber drei synthetische Chat-Turns über die normale
`/api/runtime/chat/stream`-Route. Berichtet werden nur Latenzen, Counter-Deltas
und knappe Reason-Codes. Der Output ist privat (0600), ohne Antworttext.
Der erste Turn füllt den Cache, die beiden Folgefragen sind ein Präfix-Test.

Eine positive `followup_exact_hits`-Zahl beweist Reuse über die Agent-API.
Falls weiterhin nur das Frontend keine Hits erzeugt, ist der Unterschied
wahrscheinlich oberhalb dieser Route zu finden (Prompt-Reihenfolge, Memory,
Agent-Optionen oder Session-Aufbereitung) – diese Ursache wird **nicht**
automatisch durch das Skript behoben. Negative Ergebnisse rechtfertigen
ebenfalls keine automatische Cache-Key-Lockerung.

Eine bestehende Unterhaltung wird nicht gelesen oder aufgezeichnet.
Für eine Untersuchung der Browser-Pipeline müsste die tatsächliche
Request-Zusammenstellung gezielt instrumentiert werden – erst nach einer
Codeprüfung, ohne Prompt- oder Antwortinhalte zu persistieren.
