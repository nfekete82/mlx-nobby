# MLX Nobby: Agent-Architektur

## Ziel und Arbeitsumfang

MLX Nobby führt lokale, modellgestützte Agent-Aufgaben mit MLX aus:
Diagnose, Recherche, Coding im ausgewählten Workspace und kontrollierte Delegation.
Bestehende Tools, nachvollziehbare Ergebnisse und explizite Freigaben für
zustandsändernde Aktionen bilden die Grundlage.

Dieses Dokument beschreibt die implementierte Agent-Architektur. Änderungen an
angrenzenden Diensten sind nur beschrieben, soweit sie den Agenten betreffen.

## Architektur und Invarianten

```text
API / Integration in app.py
  → AgentRuntime
      → ModelProvider → lokaler MLX-Provider
      → ToolRegistry → PermissionEngine → bestehender Tool-Handler
      → bestehende Approval-Infrastruktur → dieselbe Runtime bei Resume
```

- Modellaufrufe der migrierten Runtime laufen über `ModelProvider`.
- Die Produktionsfactory injiziert die bestehende `chat_runtime()`-Lease in
  `MLXProvider`. Gemeinsame Lock-Reihenfolge: Runtime-Lease → Modell-Lock,
  gehalten bis zum Abschluss des Modellaufrufs. Rollenauflösung darf die Lease
  im selben Thread erneut betreten. Der Image-Edit-Prompt-Helfer verwendet
  dieselbe Reihenfolge; Cancellation während des Provider-Lease-Waits bleibt
  ein strukturierter `cancelled`-Fehler.
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
| `run_state.py` | Fester `RunContext`, Run-/Chat-/Workspace-Identität, ursprüngliches Nutzerziel, erlaubte Wurzeln, Cancellation und ContextVar-Bindung. |
| `model_provider.py` | `ModelProvider`, `ModelRequest`, `ModelResponse`, `ProviderError` und lokaler `MLXProvider`. |
| `prompts.py` | Bestehende Planungs-/Abschluss-Prompts, JSON-Parsing und Format-Reparatur, Subagent-Berichte; Modellzugriff wird injiziert. |
| `evidence.py` | Evidence-Verträge, Kompaktierung, Coding-Antwortregeln, Quellenbewertung und Delegations-/Research-Helfer. |
| `approvals.py` | `AgentApprovals`: bestehender Freigabespeicher, TTL, einmalige Entnahme, Validierung, Ausführung und Verifikation. |
| `code_workspaces.py` | Workspace-Verwaltung, sichere Dateioperationen und bestehender Patch-/Diff-/Test-/Apply-/Verify-Workflow. |
| `vision_classifier.py`, `vision_routing.py` | Lokale ONNX-Bildklassifikation und Auswahl einer passenden Vision-Rolle für den normalen multimodalen Chat-Pfad. |
| `app.py` | FastAPI-Endpunkte, Zusammensetzen der Abhängigkeiten, lokale Modellintegration, Progress-Speicher und Compatibility-Funktionen. Enthält weiterhin andere Anwendungslogik. |

## Chat- und Medienrouting

`backend/media_intent.py` ist die gemeinsame, nebenwirkungsfreie
Intent-Decision-Layer für Agent, Web-Preflight und Runtime-Medientools.
`RoutingDecision` enthält `intent`, `target`, `execution_requested`,
`media_context`, `confidence`, `reason`, `guard` und `fallback`.
Textausgaben wie Prompts/Skripte und Fragen haben Vorrang; Bildanhänge und
Adult-Begriffe liefern Kontext, keine Ausführungsabsicht. Eine unabhängige
explizite Medienanweisung kann einen kombinierten Text-/Medienauftrag ausführen.
Semantische Klassifikation darf ohne Ausführungsabsicht keine Medienjobs starten.

Preflight und Aktionsendpunkt verwenden dieselbe Entscheidung. Ein übermitteltes
`resolved_target` autorisiert keine Ausführung; `chat` unterbindet Medienjobs
nach fehlgeschlagenem Preflight. Browser-Regex-Hinweise dienen der Quellenbindung.
Runtime-Medientools prüfen `RunContext.user_goal`, sodass umformulierte oder
delegierte Tool-Ziele keine neue Medienabsicht einführen. Bestehende Pipeline-,
Ownership-, Revision- und Permission-Prüfungen bleiben erhalten.

Bildkontext ohne Medienausführung geht an den VLM-Chat: bevorzugt
`vision_uncensored`, sonst `vision`. Der Safety-Classifier liefert ausschließlich
Metadaten für Observability und beeinflusst die Rollenwahl nicht. Web-Telemetrie speichert Intent, Ziele, Gründe,
Hash und Länge, aber keine Prompt- oder Bildinhalte. Details, vorherige Reihenfolge
und Grenzen: [Routing-Audit](ROUTING_AUDIT.md).

`backend/routing_observatory.py` ergänzt einen thread-sicheren Ringpuffer mit 500
Events im Webprozess. Der bestehende Media-Guard erfasst Preflight-Entscheidungen;
eine passive ASGI-Middleware erfasst Chat-/Vision-SSE, Action-/Agent-Antworten und
Media-Dispatch. Rollen und tatsächliche Modelle stammen aus vorhandenen
ModelCallMetrics oder Job-Antworten; Router-Modelle werden separat ausgewiesen.
Vorhandene Job-Statusabfragen aktualisieren Events ohne zusätzliche Polls.
Ein ContextVar korreliert geplante Chat-Recovery mit dem aktuellen Event.
`/api/routing/events`, `/stats` und DELETE `/events` liefern gefilterte Diagnosen.
Die Tools-Ansicht pollt nur sichtbar, alle zehn Sekunden, ohne parallele Refreshes.
Normale Events werden nicht persistiert; explizites Feedback nutzt den bestehenden
JSON-Store. Schema, Datenschutz und Prozess-/Job-Grenzen:
[Routing Observatory](ROUTING_OBSERVATORY.md).

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

Die normale Chat-Oberfläche leitet Workspace-Agentaufträge, Webrecherche,
einzelne angehängte Bilder und Dokumentfragen über den bestehenden Router an
die Runtime. `AgentRunRequest` bindet Chat-Revision, Workspace-Auswahl,
Conversation-Auszug, Upload-Pfade, Dokument-IDs und Bildartefakte vor der
Planung an den RunContext. Runtime-Tools prüfen diese Auswahl zusätzlich zum
Permission-Gate. Mehrbild-Vision, direkte Bildbearbeitungsjobs und die
Datei-Transformationspipeline behalten ihre spezialisierten Chat-Pfade.
Bild- und Datei-Jobs bleiben asynchron und tragen Chat- und Run-ID; die
Adapter starten Jobs und lesen ihren Status, warten aber nicht im Modell-/Tool-
Zyklus auf rechenintensive Fertigstellung.

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

- `RunContext` bindet Run-ID, Chat-ID, Chat-Revision, Workspace-ID, aufgelöste
  Workspace-Wurzel, erlaubte Wurzeln, Conversation-Auszug, ausgewählte Uploads,
  Dokumente und Bildartefakte sowie ein gemeinsames Cancellation-Event.
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
- Die Modellrollen `chat`, `agent`, `coding`, `vision`, `image` und `embedding`
  werden in der bestehenden Integration aufgelöst; zusätzliche lokale
  Vision-Rollen können optional als Fallback eingebunden werden.
  BGE-M3 ist für die Embedding-Rolle kompatibel.
- Der Web-Backend-Chat-Pfad fragt bei Bildnachrichten die Vision-Route des
  Agenten ab. Ein optionaler lokaler ONNX-Klassifikator kann bei passender
  Konfiguration zwischen verfügbaren Vision-Rollen wählen. Bei Fehlern oder
  unklarer Klassifikation bleibt die Standard-Vision-Rolle aktiv. Das
  Klassifikatormodell wird bei Bedarf heruntergeladen; seine separaten
  Python-Abhängigkeiten installiert der Standardinstaller nicht.
- Freigaben und Progress sind weiterhin prozesslokal; keine neue dauerhafte
  Speicherung oder Wiederaufnahme nach einem Prozessneustart implementiert.
- Cancellation ist kooperativ: vor Modell-/Tool-Aufrufen und neuen Schritten.
  Bereits laufende HTTP-Anfragen und Prozesse werden nicht aktiv unterbrochen.
- Bereits abgeschlossene Tool-Ergebnisse bleiben bei Cancellation erhalten.
- Provider-Fehler ergeben strukturierte fehlgeschlagene Runs; Cancellation ergibt
  `cancelled`. Bestehende JSON-Fehlerbehandlung und Format-Reparatur bleiben bestehen.
- Tool-Schemas, Timeout- und Output-Metadaten ersetzen keine Handler-Validierung;
  die Registry führt daraus keine allgemeine neue Ausführungs-/Timeout-Engine ab.
- Die automatisierten Tests verwenden überwiegend Fake/Mock Provider. Zusätzlich
  wurde der Release-Stand lokal mit echter MLX-Inferenz Ende zu Ende validiert.

## Chat-Streaming und Reliability

Workspace-Modus liest den Server bei Initialisierung, Header-`data-active`-
Änderung, Fokus/Wiederanzeigen und Submission. Der Header-Observer ignoriert
die selbst gesetzten Agent-Modus-Attribute. Gleichzeitige Reads teilen nur die
laufende Promise, ohne TTL-Cache; Änderungen während eines Syncs erhalten einen
nachgelagerten Refresh. Composer-Handler werden einmal installiert.
Explizite deutsche Schreibverbote (`Ändere keine Dateien`, `Keine Dateien
ändern`) aktivieren den bestehenden Read-only-Abschluss nach erfolgreichem
`code_read`, ohne weitere Modellplanung oder Patch-Anforderung. Explizites
`file_analyze` verwendet weiterhin seinen Analysepfad.
Performance Observatory und System Health fragen automatisch nur bei sichtbarem
Dokument und sichtbarem, geöffnetem Settings-Panel ab; Öffnen aktualisiert sofort.
Messverfahren, Lock-Reproduktion und Grenzen: [Performance-Audit](PERFORMANCE_AUDIT.md).

`backend/chat_reliability_routes.py` kapselt den vorhandenen Gateway über
`/api/chat/reliable-stream`; das Frontend leitet normale Chat-Stream-Requests
über diesen Pfad. `image_url`-Blöcke in den Nachrichten einschließlich History
aktivieren das Vision-Budget (Standard 60 s, mindestens das Textbudget).
Textchat behält 30 s bis zum ersten Gateway-Chunk und 45 s bei Stream-Stillstand.

Vision sendet sofort und bei ausstehenden Reads alle 5 s SSE-Kommentare.
Pro Read bleibt genau ein Task aktiv. Heartbeats sind Transportaktivität und
weder Modellfortschritt noch eine erfolgreiche Antwort. Vor inhaltlicher Ausgabe
bleibt eine absolute Frist aktiv; auch Sources/Metrics verlängern sie nicht.
Danach gilt der normale 45-s-Stall-Watchdog. Die synchrone Vision-Gateway-
Vorbereitung läuft in einem Worker-Thread, damit sie den Watchdog nicht blockiert.
Der vorhandene Vision-Aufruf bleibt `stream: false`: das Gateway liefert
Modellausgabe erst nach dem vollständigen HTTP-Response.

Vor dem ersten Upstream-Chunk kann die Reliability-Schicht einmal Recovery
anfordern und nach Bereitschaft mit neuer PID erneut versuchen. Nach bereits
weitergereichten Upstream-Chunks beendet sie einen Stall mit SSE-Fehler und
Recovery-Anforderung ohne Replay. Der Schutz aktiver Bild-/Video-Jobs und das
Media-Wartebudget von 300 s bleiben bestehen. Disconnect/Timeout schließen den
Iterator und canceln ausstehende Async-Reads; bereits laufende synchrone
HTTP-Aufrufe in Threads werden dadurch nicht aktiv beendet.

Root Cause, Messwerte, Konfiguration und Regressionen:
[Vision streaming reliability](VISION_STREAMING_RELIABILITY.md).

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
