# MLX Nobby: Agent-Handoff

## Ziel und Arbeitsumfang

MLX Nobby führt lokale, modellgestützte Agent-Aufgaben mit MLX aus:
Diagnose, Recherche, Coding im ausgewählten Workspace und kontrollierte Delegation.
Bestehende Tools, nachvollziehbare Ergebnisse und explizite Freigaben für
zustandsändernde Aktionen bilden die Grundlage.

Dieses Dokument beschreibt den zuletzt implementierten Stand. Für Folgearbeiten
nur betroffene Symbole und Ausschnitte prüfen; keine vollständige Neuanalyse von
`agent/app.py` oder des Repositorys beginnen.

## Architektur und Invarianten

```text
API / Integration in app.py
  → AgentRuntime
      → ModelProvider → lokaler MLX-Provider
      → ToolRegistry → PermissionEngine → bestehender Tool-Handler
      → bestehende Approval-Infrastruktur → dieselbe Runtime bei Resume
```

- Modellaufrufe der migrierten Runtime laufen über `ModelProvider`.
- Tool-Aufrufe der Runtime laufen über `ToolRegistry`.
- `PermissionEngine` entscheidet `ALLOW`, `CONFIRM` oder `DENY`.
- Der Workspace wird einmal pro Run im `RunContext` gebunden.
- Delegation und Approval-Resume behalten denselben relevanten RunContext.
- Approval-Resume behält außerdem Runtime, Provider, Registry und Progress-Callback.
- Es gibt keinen automatischen Cloud-Fallback.
- Vorhandene Sicherheitsprüfungen in Tool-Handlern bleiben verbindlich.
- Legacy-Mutationen `code_apply` und `docker_restart` haben weiterhin eigene
  Approval-Handler; sie sind kein allgemeiner Registry-Bypass für neue Tools.

## Relevante Module

Alle folgenden Pfade liegen unter `agent/`.

| Modul | Verantwortung |
| --- | --- |
| `runtime.py` | `AgentRuntime`, bestehender Agent-Loop, Limits, Guards, Delegation, Progress, Cancellation und Approval-Resume. |
| `tool_registry.py` | `Tool`-Metadaten, Katalog, Dispatch und Permission-Gate; gesonderte Ausführung einer konsumierten Freigabe. |
| `permissions.py` | `PermissionEngine`, Policy, Risiken, Entscheidungen und strukturierter `ToolPermissionError`; prüft auch Kontext und Pfadgrenzen. |
| `run_state.py` | Fester `RunContext`, Run-/Chat-/Workspace-Identität, erlaubte Wurzeln, Cancellation und ContextVar-Bindung. |
| `model_provider.py` | `ModelProvider`, `ModelRequest`, `ModelResponse`, `ProviderError` und lokaler `MLXProvider`. |
| `prompts.py` | Bestehende Planungs-/Abschluss-Prompts, JSON-Parsing und Format-Reparatur, Subagent-Berichte; Modellzugriff wird injiziert. |
| `evidence.py` | Evidence-Verträge, Kompaktierung, Coding-Antwortregeln, Quellenbewertung und Delegations-/Research-Helfer. |
| `approvals.py` | `AgentApprovals`: bestehender Freigabespeicher, TTL, einmalige Entnahme, Validierung, Ausführung und Verifikation. |
| `code_workspaces.py` | Workspace-Verwaltung, sichere Dateioperationen und bestehender Patch-/Diff-/Test-/Apply-/Verify-Workflow. |
| `app.py` | FastAPI-Endpunkte, Zusammensetzen der Abhängigkeiten, lokale Modellintegration, Progress-Speicher und Compatibility-Funktionen. Enthält weiterhin andere Anwendungslogik. |

## Ablauf eines Runs

1. `POST /api/agent/run` validiert Eingaben und erzeugt den RunContext vor der Planung.
2. `run_agent_v2(...)` ist der Compatibility-Einstieg zur Runtime.
3. `agent_runtime(context, ...)` verbindet Provider, Registry und `RuntimeHooks`.
4. `AgentRuntime.run(...)` bindet RunContext und aktuelle Runtime per ContextVar.
5. Der bestehende Loop plant, verarbeitet JSON-Aktionen und führt Tools,
   Delegation, Approval-Anfragen oder eine Abschlussantwort aus.
6. Beobachtungen gehen in weitere Planung und Evidence-Prüfung ein.
7. Ergebnis und Progress verwenden weiterhin die bestehenden API-Verträge.

`agent_llm()` liefert weiterhin Text, verwendet innerhalb einer Runtime aber
deren Provider. `observed_agent_llm()` erhält die Observability-Zweckzuordnung.
Prompt-Helfer enthalten keine eigene MLX-/HTTP-Anbindung.

`RuntimePolicy` erhält die bisherigen Schrittbudgets:
Diagnose 6, Recherche 6, Coding 24, Orchestrator 12.
Recherche kann bis zu 3 zusätzliche Schritte zur Fortsetzung einer bereits
geladenen, gekürzten Quelle nutzen. Bestehende Wiederholungs-, Such-,
Evidence- und Delegationsgrenzen bleiben zusätzlich aktiv.

## Tool- und Permission-Ablauf

```text
Modellantwort → Aktion → Modus-/Loop-Guards → Registry
  → PermissionEngine.evaluate(tool, context, arguments)
      ALLOW   → Handler → Beobachtung → weitere Planung
      DENY    → strukturierter Fehler → weitere Planung
      CONFIRM → bestehende Freigabe → Pause bis zur Entscheidung
```

- Die Runtime akzeptiert keine Registry ohne Permission Engine.
- Die Runtime erlaubt registrierte READ-, EXECUTE- und CREATE-Tools. Im
  Coding-Modus kommen PREPARE- und WRITE-Tools hinzu. `image_edit` ist auch
  außerhalb des Coding-Modus verfügbar. Die Permission Engine entscheidet
  danach weiterhin jeden konkreten Aufruf; EXECUTE/CREATE/WRITE benötigen
  standardmäßig CONFIRM.
- PREPARE für `code_patch` erlaubt nur Patch-Vorbereitung, keine Anwendung.
- `DENY` und `CONFIRM` führen im normalen Registry-Dispatch keinen Handler aus.
- Delegierte Runs mit `allow_approval=False` dürfen keine Freigaben anfordern.
- Tool-Fehler werden als Beobachtungen an die weitere Planung zurückgegeben.

## Angebundene Bestandsfähigkeiten

`agent/runtime_tools.py` enthält nur Adapter; die bestehenden Handler,
Provider, Job-Speicher und Services bleiben zuständig.

| Kategorie | Runtime-Tools | Bestehender Pfad / Grenze |
| --- | --- | --- |
| Workspace/Coding | `workspace_status`; vorhandene `code_files`, `code_search`, `code_read`, `code_patch`, `code_diff`, `code_test` | `code_workspaces`; `code_apply` bleibt expliziter Legacy-Approval-Pfad. |
| Shell | `shell_workspace`; vorhandenes `shell_read` | Vetted argv ohne Shell, gebundener Workspace, 30 s und begrenzte Ausgabe; nur `pwd`, `ls`, `rg`, ausgewählte Python-Pytest- und Node-Syntaxbefehle. Jede Ausführung verlangt CONFIRM. |
| Git | `git_status`, `git_diff`, `git_log`, `git_stage`, `git_commit` | Git-CLI nur bei Repo-Wurzel gleich gebundenem Workspace. Stage/Commit verlangen CONFIRM; Stage bindet die ausgewählten Datei-Inhalte, Commit die staged Blob-IDs an die Freigabe. Commit verlangt genau ausgewählte staged Pfade. Kein Push/Reset/Force-Tool. |
| Web | vorhandene `web_search`, `search_web`, `fetch_url` | Bestehende SearXNG-/Fetch-Handler unverändert. |
| Vision | `vision_analyze` | Gleicher ModelProvider mit Vision-Rolle; nur Workspace-Bild oder verwaltetes Bild des gebundenen Chats. |
| Bilder | `image_generate`, `image_edit`, `image_job_status` | Bestehender Image-Service und Chat-Job-Vertrag. Erzeugung/Bearbeitung starten nach CONFIRM nur einen Job; Status liefert den vorhandenen Artefaktvertrag. Chat-ID erforderlich. |
| Text/Dokumente | `file_inspect`, `file_pii_audit`, `file_analyze`, `file_analysis_status`, `document_search`, `document_page` | Bestehende Struktur-/PII-Funktionen, Datei-Analysejobs und hochgeladene Dokumentindexierung. PDF-Extraktion bleibt im Upload-Pfad; Runtime liest nur bereits indexierte PDF-Seiten. |

Bei Git, Shell und Workspace-Dateien wird ausschließlich der RunContext-Workspace
verwendet. Neue Tool-Adapter begrenzen ihre Ausgabe im Handler, weil die Registry
die Metadaten selbst nicht als allgemeine Timeout-/Trunkierungs-Engine ausführt.
Freigaben für Git zeigen Pfade und Commit-Nachricht öffentlich an; interne
Tool-Argumente bleiben im Pending-Speicher.

Die normale Chat-Oberfläche verwendet weiterhin eigene Routing-Pfade für
Anhänge, Vision, Bildjobs und PDF-Uploads. `AgentRunRequest` transportiert
noch keine gebundene Anhangs-/Dokumentauswahl; Runtime-Tools erhalten dafür
explizite Artifact- oder Dokument-IDs. Bild- und Datei-Analysejobs bleiben
asynchron. Die Adapter starten Jobs und lesen ihren Status, warten aber nicht
im Modell-/Tool-Zyklus auf rechenintensive Fertigstellung.

## Approval → Resume

1. Eine explizite bestehende Approval-Aktion oder ein Registry-`CONFIRM` erzeugt
   über `AgentApprovals` einen Eintrag im vorhandenen Pending-Speicher.
2. Intern gespeichert werden RunContext, ursprüngliche Runtime, Progress-Callback,
   Beobachtungen, Schritt, Modus, Ziel und Gesprächskontext.
3. Bei Registry-Aufrufen werden zusätzlich die konkreten Argumente kopiert und
   die freizugebende Tool-Definition gespeichert.
4. Die API liefert weiterhin `approval_required` und die bisherigen öffentlichen
   `pending_action`-Felder. Runtime-Objekte und interne Argumente werden nicht exponiert.
5. `POST /api/agent/approve/{approval_id}` entnimmt den Eintrag einmalig.
   Fehlende/verwendete IDs ergeben 404, abgelaufene Freigaben 410; TTL: 300 Sekunden.
6. `AgentRuntime.resume_approval(...)` verwendet die gespeicherte Runtime und prüft
   Kontextidentität sowie Cancellation vor der Ausführung.
7. Ablehnung wird als `rejected_by_user` protokolliert; die Planung kann fortsetzen.
8. Bei Zustimmung prüft `execute_approved(...)` für Registry-Tools erneut Policy
   und Tool-Definition. Ein aktuelles DENY oder eine geänderte Definition blockiert.
9. Die Zustimmung gilt nur für den gespeicherten Aufruf; sie schaltet keine
   dauerhafte Berechtigung im RunContext oder in der Registry frei.
10. Nach Ausführung geht der Run ab dem nächsten Schritt mit seinen Beobachtungen
    weiter. Progress wird unter der ursprünglichen Run-ID aktualisiert.

Legacy-Aktionen behalten ihre Spezialprüfungen:

- `code_apply`: nur Coding-Modus, gültiger vorgeschlagener Patch, passende
  erfolgreiche `code_diff`- und danach `code_test`-Beobachtungen mit ausgeführten Checks.
- `docker_restart`: nur Diagnose-Modus und validierter Containername.
- Beide prüfen die Permission vor der Mutation erneut und nutzen ihre bestehenden
  Verifikationsroutinen.
- Ein erfolgreich angewendeter und verifizierter Patch beendet den Run ohne
  zusätzliche Planung.
- Direkte Legacy-Aufrufe ohne gespeicherte Runtime verwenden den vorhandenen
  RunContext zur Erzeugung einer Runtime beim Resume.

## Workspace-Binding und Sicherheitsregeln

- `RunContext` bindet Run-ID, Chat-ID, Workspace-ID, aufgelöste Workspace-Wurzel,
  erlaubte Wurzeln und ein gemeinsames Cancellation-Event.
- `RunContext.start()` übernimmt die Auswahl zu Run-Beginn. Ein späterer globaler
  Workspace-Wechsel darf den laufenden Run nicht umleiten.
- `workspace()` und `resolve_path()` prüfen die Bindung und vorhandene Pfadregeln.
  Verschobene/entfernte Workspaces und Pfade außerhalb der Grenzen werden blockiert.
- Ein Run ohne Workspace erhält durch eine spätere globale Auswahl keinen Workspace.
- Delegation verwendet denselben Kontext, Provider und dieselbe Registry;
  untergeordnete Beobachtungen und Schrittbudgets bleiben getrennt.
- ContextVar-Bindungen werden auch bei Fehlern und verschachtelten Runs zurückgesetzt.
- Traversal-, Symlink-, Secret-/Ignore-, Patch- und Workspace-Prüfungen nicht umgehen.
- Insbesondere bleibt der bestehende Active-Workspace-Guard beim Patch-Anwenden
  erhalten: Nach globalem Workspace-Wechsel kann Apply mit `WORKSPACE_CHANGED` scheitern.
- Freigaben heben weder DENY noch Cancellation oder bestehende Handler-Prüfungen auf.
- Keine direkte Tool-Ausführung aus Prompt-Helfern oder neue Modell-HTTP-Aufrufe in der Runtime.

## Compatibility-Pfade und technische Grenzen

- Der ältere Read-only-Loop bleibt vorerst in `app.py`; keine pauschale Migration nötig.
- Dünne Funktionen in `app.py` erhalten bisherige Aufrufstellen und binden die
  ausgelagerten Prompt-, Evidence- und Approval-Module an.
- Rollen-/Modellauflösung, Modell-Lock und Progress-/Pending-Speicher bleiben in der
  bestehenden Integration. Es wurde keine neue Event-Plattform eingeführt.
- Freigaben und Progress sind weiterhin prozesslokal; keine neue dauerhafte
  Speicherung oder Wiederaufnahme nach einem Prozessneustart implementiert.
- Cancellation ist kooperativ: vor Modell-/Tool-Aufrufen und neuen Schritten.
  Bereits laufende HTTP-Anfragen und Prozesse werden nicht aktiv unterbrochen.
- Bereits abgeschlossene Tool-Ergebnisse bleiben bei Cancellation erhalten.
- Provider-Fehler ergeben strukturierte fehlgeschlagene Runs; Cancellation ergibt
  `cancelled`. Bestehende JSON-Fehlerbehandlung und Format-Reparatur bleiben bestehen.
- Tool-Schemas, Timeout- und Output-Metadaten ersetzen keine Handler-Validierung;
  die Registry führt daraus keine allgemeine neue Ausführungs-/Timeout-Engine ab.
- Die automatisierten Tests verwenden Fake/Mock Provider; echte MLX-Inferenz wurde
  für diese Extraktion nicht benötigt und damit nicht als Integrationstest bestätigt.

## Relevante Tests

| Datei unter `tests/` | Schwerpunkt |
| --- | --- |
| `test_agent_runtime.py` | Loop, ALLOW/DENY/CONFIRM, Delegation, Limits, Cancellation, Fehler, API und Approval-Resume. |
| `test_runtime_tools.py` | Neue Adapter, Workspace-/Chat-Bindung, Git-Freigaben, Shell-Grenzen, Vision-, Image- und Dokumentverträge. |
| `test_permissions.py` | Policy, Pfad-/Workspace-Grenzen, Kontextbindung und Approval-Sicherheitsprüfungen. |
| `test_tool_registry.py` | Registry-Metadaten und Dispatch. |
| `test_model_provider.py` | Lokaler Provider, Fehler- und Kontextverhalten. |
| `test_code_workspaces.py` | Workspace-/Patch-/Approval-Workflow sowie bestehende Coding-/Agent-Regressionsfälle. |
| `test_model_runtime_api.py` | Modell-Runtime/API-Integration. |
| `test_observability.py` | Bestehende Mess-/Kontextintegration. |
| `test_disk_usage.py`, `test_service_bridge.py` | Relevante bestehende Tool-/Integrationsregressionen. |
| `test_sse_stream.mjs`, `test_agent_card.mjs`, `test_code_evidence_ui.mjs` | SSE-, Agent-Card- und Evidence-/Approval-UI-Verträge. |

Der obige historische Teststand beschreibt die ursprüngliche Runtime-Extraktion.
Die Adapter-Erweiterung wird durch gezielte Python- und JavaScript-Tests geprüft.

## Bekannte Testbefehle

Vom Repository-Wurzelverzeichnis aus arbeiten. `agent-venv/bin/python` verwendet
die passende Umgebung; das allgemeine `python3` kann eine ältere Version sein.
Für Subprozesse ebenfalls den venv-Pfad voranstellen.

Wichtig: Einige Tests importieren Anwendungscode mit benutzerspezifischen
Konfigurationspfaden. `Path.home()` vor Test-Discovery/Imports isolieren,
damit insbesondere Modell-Runtime-Tests keine echte `jobs.json` verändern.

```sh
PATH="$PWD/agent-venv/bin:$PATH" agent-venv/bin/python - <<'PY'
import tempfile
import unittest
from pathlib import Path
from unittest import mock

patterns = ["test_agent_runtime.py", "test_permissions.py"]
with tempfile.TemporaryDirectory() as directory:
    with mock.patch.object(Path, "home", return_value=Path(directory)):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite(
            loader.discover("tests", pattern=pattern) for pattern in patterns
        )
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        raise SystemExit(not result.wasSuccessful())
PY
```

`patterns` nur um die für die Änderung relevanten Testdateien erweitern.
Nicht mehrfach pauschal die vollständige Suite starten.

```sh
node tests/test_sse_stream.mjs
node tests/test_agent_card.mjs
node tests/test_code_evidence_ui.mjs
git diff --check
```

Syntaxprüfungen sind mit `ast.parse(Path(datei).read_text(), filename=datei)` möglich.

## Git- und Architekturstand bei Erstellung

- Foundation und erste Runtime-Extraktion waren beim letzten Implementierungsschritt
  bereits committed; die anschließende Fertigstellung der Runtime-Grenze wurde nicht committed.
- Zuletzt neu/ungetrackt: `agent/prompts.py`, `agent/evidence.py`, `agent/approvals.py`.
- Zuletzt geändert: `agent/app.py`, `agent/runtime.py`, `agent/tool_registry.py`,
  `tests/test_agent_runtime.py`, `tests/test_permissions.py`.
- `app.py` wurde in diesem letzten Schritt netto um 3.304 Zeilen reduziert.
- Bestehende Benutzeränderung: `frontend/assets/chat/generation.js`.
  Diese wurde nicht verändert, gestagt oder zurückgesetzt und muss erhalten bleiben.
- Vor Folgeänderungen `git status --short` prüfen; diese Liste ist eine Momentaufnahme.
- Keine pauschalen Git-Operationen, kein `git add .`, kein Hard Reset und kein Force Push.
- Dieses Handoff wurde ohne erneute Repository-Analyse erstellt.

## Nächste Arbeiten, priorisiert

1. Gezielter lokaler Integrationstest mit echtem MLX: Run, bestehende Tools,
   Freigabe, Resume, Progress und verifizierter Abschluss.
   Zustandsändernde Aktionen nur mit ausdrücklich autorisiertem Testziel ausführen.
2. Dabei auftretende Abweichungen gezielt beheben; vorhandene Unit-/API-Tests
   nur um konkrete fehlende Fälle ergänzen.
3. Den älteren Read-only-Loop nur bei einem klaren, kleinen Migrationsbedarf anfassen;
   ansonsten den dokumentierten Compatibility-Pfad erhalten.
4. Aktive Unterbrechung laufender Operationen oder dauerhafte Run-Wiederaufnahme
   nur als separat beauftragte Arbeiten planen.

Über die hier dokumentierten Adapter hinaus sind Cloud-Provider,
Routing-/Planning-Architektur und Frontend-Umbauten nicht Teil dieses Stands.
