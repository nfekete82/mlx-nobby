"""Existing agent prompts and JSON handling; model access is injected."""

import json
import re

from agent.evidence import (
    compact_agent_observations,
    normalize_agent_conversation_context,
    coding_evidence_contract,
    coding_final_answer_requires_repair,
    compact_coding_answer_markdown,
    deterministic_loaded_web_sources,
)


def normalize_json_structural_whitespace(value):
    """
    Normalize Unicode whitespace only outside JSON strings.

    Some local models emit NBSP (U+00A0), for example, when indenting an
    otherwise valid JSON object. Python's JSON parser accepts only JSON
    whitespace defined by RFC 8259 in that position.

    Content inside strings remains unchanged.
    """
    value = str(value or "")

    result = []
    in_string = False
    escaped = False

    for char in value:
        if in_string:
            result.append(char)

            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            result.append(char)
            continue

    # JSON permits only these whitespace characters structurally:
    # U+0020 SPACE, TAB, LF, and CR.
        #
    # Other Unicode whitespace characters outside strings are
    # safely normalized to regular SPACE characters.
        if char.isspace() and char not in " \t\n\r":
            result.append(" ")
        else:
            result.append(char)

    return "".join(result)



def parse_agent_json(value):
    """Reliably extract exactly one JSON object from a model response."""

    value = str(value or "").strip()

    # Local models occasionally use Unicode whitespace such as
    # NBSP (U+00A0) for JSON indentation. Outside strings, this is
    # not valid JSON whitespace.
    value = normalize_json_structural_whitespace(value)

    if not value:
        raise ValueError(
            "Agent hat kein gültiges JSON geliefert"
        )

    if value.startswith("```"):
        value = re.sub(
            r"^```(?:json)?\s*",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(
            r"\s*```$",
            "",
            value,
        ).strip()

    # Ideal case: the complete response is valid JSON.
    try:
        result = json.loads(value)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Eingebettetes JSON robust finden.
    decoder = json.JSONDecoder()

    for index, char in enumerate(value):
        if char != "{":
            continue

        try:
            result, _end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(result, dict):
            return result

    raise ValueError(
        "Agent hat kein gültiges JSON geliefert"
    )



def agent_tool_description(include_prepare=False, *, capability_text, include_extended=True):
    prepare_tools = """

Verfügbare PREPARE-Tools (nur im Coding-Modus):

code_patch
- Erzeugt ausschließlich einen Patch-Vorschlag und verändert keine
  Workspace-Datei.
- Darf ohne Benutzerfreigabe automatisch ausgeführt werden.
- Unterstützt CREATE, MODIFY und DELETE innerhalb des aktiven Workspaces.
- Ein Aufruf ist ein zusammenhängendes Change-Set und darf beliebig viele
  CREATE-, MODIFY- und DELETE-Einträge gemeinsam enthalten.
- CREATE/MODIFY enthalten den vollständigen neuen Dateiinhalt in
  proposed_content. DELETE verwendet operation="DELETE" und keinen neuen
  Inhalt.
- Nach code_patch müssen code_diff und code_test ausgeführt werden.
- Das spätere code_apply benötigt eine ausdrückliche Benutzerfreigabe.
""".rstrip() if include_prepare else ""
    runtime_tools_text = """

Weitere Registry-Tools:
- workspace_status: Status des gebundenen Code-Workspaces.
- shell_workspace: Freigegebene Workspace-Befehle (pwd, ls, rg,
  python3 -m pytest DATEI, node --check DATEI); "query" ist der Befehl.
  Jede Ausführung benötigt eine Freigabe. Keine Shell-Verknüpfungen.
- git_status, git_diff, git_log: lesender Git-Zugriff im gebundenen Workspace.
  git_diff kann einen relativen Pfad in "query" und cached=true in "options" nutzen.
- git_stage: gezieltes Staging mit options.paths als Liste relativer Pfade.
- git_commit: nur exakt diese zuvor gestagten Pfade mit
  options.paths und options.message. Staging und Commit benötigen Freigaben.
  Kein Push, Reset oder Force-Befehl.
- vision_analyze: Bild im gebundenen Workspace per relativem Pfad in "query"
  analysieren; alternativ options.artifact_id für ein verwaltetes Bild oder
  options.upload_path für einen an diesen Run gebundenen Chat-Upload.
- image_generate: Bildjob für den gebundenen Chat anlegen; Bildbeschreibung
  in "query". image_edit benötigt options.artifact_id oder
  options.upload_path aus den gebundenen Run-Ressourcen. Beide benötigen
  Freigabe und liefern zunächst einen Job, kein fertiges Bild.
- image_job_status: Bildjob-ID in "query" abfragen.
- document_search: "query" ist Suchtext, options.document_id das bereits
  indexierte Dokument. document_page: options.document_id und options.page.
- file_inspect: Struktur einer Workspace-Textdatei lesen. file_pii_audit:
  bestehende PII-Prüfung einer Workspace-Textdatei. Pfad in "query".
- file_analyze: Textdatei im Workspace in "query", Aufgabe in "instruction";
  startet einen Analysejob nach Freigabe. PDFs über die bestehende
  Dokumentindexierung lesen. file_analysis_status: Job-ID in "query".
""".rstrip() if include_extended else ""

    return f"""
Zentrale MLX-Nobby-Fähigkeiten:
{capability_text}

Verfügbare automatisch ausführbare READ-Tools:

disk_usage
- Analysiert große Dateien und Ordner nativ, strukturiert und ausschließlich
  lesend. Verwende dieses Tool immer für lokalen Speicherplatz,
  Speicherverbrauch, volle SSDs und Ranglisten großer Dateien oder Ordner.
- Verwende dafür NICHT shell_read mit du, find, sort, Pipes, Globs oder
  Redirects.
- Ohne Optionen wird sicher der Benutzerordner untersucht.
- Optionale Eingabe im Feld "options":
  {{"path":"/absoluter/freigegebener/Pfad","mode":"files|directories|both",
  "limit":20,"min_size_bytes":104857600,"max_depth":5,
  "include_hidden":true}}
- Bei partial=true fasse die vorhandenen Resultate zusammen und erwähne die
  Warnungen, statt die gesamte Analyse als fehlgeschlagen zu behandeln.

shell_read
- Führt einen einzelnen freigegebenen Diagnosebefehl aus.
- Verwende dafür das JSON-Feld "query".
- Keine Pipes, Redirects oder Shell-Verknüpfungen.
- Erlaubt sind insbesondere:
  ps, pgrep, df, du, uptime, vm_stat, memory_pressure,
  sysctl, lsof, curl sowie docker ps/logs/inspect/stats.
- Beispiel:
  {{"action":"shell_read","reason":"RAM prüfen","query":"vm_stat"}}

process_usage
- Erfasst lokale Prozesse strukturiert und ausschließlich lesend.
- Liefert getrennte Ranglisten für CPU-Prozent und RAM/RSS inklusive
  Prozessname, PID und Laufzeit.
- Verwende dieses Tool bei Fragen nach Apps/Prozessen mit der höchsten
  CPU- oder Speichernutzung. Berechne keinen erfundenen Gesamtverbrauch.

system_status
- System-, RAM- und MLX-Status untersuchen.

logs_query
- Aktuelle Agent-/Server-Logs untersuchen.

batch_status
- Laufende Batch-Jobs und Aufgaben untersuchen.

knowledge_search
- In der lokalen Wissensbasis suchen.

code_search
- Im konfigurierten Code-Workspace suchen.



code_diff
- Zeigt den Unified Diff eines bereits vorbereiteten Patches.
- "query" enthält ausschließlich die patch_id.

code_test
- Testet einen bereits vorbereiteten Patch isoliert.
- Verändert den echten Workspace nicht.
- "query" enthält ausschließlich die patch_id.

code_files

- Findet Dateien im konfigurierten Code-Workspace.
- Verwende "query" für Dateinamen, Funktionsnamen oder Code-Begriffe.
- Das Tool durchsucht Dateipfade und geeignete Textdateien.
- Wenn code_search keine brauchbaren Treffer liefert, verwende code_files.
- Anschließend die relevante Datei mit code_read lesen.

code_read

- Liest eine konkrete Datei aus dem Code-Workspace.
- Im Feld "query" den relativen Dateipfad angeben.
- Wenn die Datei unbekannt ist, zuerst code_search verwenden.

web_search
- Schnelle Webrecherche über SearXNG.
- Sucht und lädt automatisch die relevantesten Seiten.

search_web
- Suche gezielt nach aktuellen Informationen.
- Verwende dafür das JSON-Feld "query".
- Liefert Titel, URL und Snippet, lädt die Seiten aber noch nicht.
- Nutze dieses Tool bevorzugt für mehrstufige Recherche.

fetch_url
- Lade gezielt eine URL aus einem vorherigen search_web-Ergebnis.
- Übergib die vollständige URL im JSON-Feld "query".
- Öffne bevorzugt relevante Primärquellen und seriöse Quellen.
- Du darfst mehrere Quellen nacheinander laden.

{runtime_tools_text}

Bei Fragen, die aktuelle Webinformationen benötigen:
1. search_web verwenden.
2. Relevante Treffer auswählen.
3. Mit fetch_url mindestens die wichtigsten Quellen öffnen.
4. Bei widersprüchlichen Informationen weitere Quellen prüfen.
5. In der Abschlussantwort die verwendeten Quellen bzw. URLs nennen.
{prepare_tools}
""".strip()



def agent_choose_next_step_v2(
    goal,
    observations,
    max_steps=8,
    mode="diagnostic",
    conversation_context=None,
    *, observed_agent_llm, agent_tool_description, _looks_like_disk_usage_request,
):
    mode = str(mode or "diagnostic").strip().lower()
    coding_mode = mode == "coding"

    if (
        not observations
        and mode in {"diagnostic", "orchestrator"}
        and _looks_like_disk_usage_request(goal)
    ):
        return {
            "action": "disk_usage",
            "reason": "Große Dateien und Ordner sicher analysieren",
            "options": {},
        }

    if coding_mode:
        role_context = """
Du bist der lokale Coding-Agent für den aktiven Code-Workspace.

Du darfst und sollst legitime Datei-Erstellungen und Änderungen über den
sicheren Patch-Workflow vorbereiten. Behaupte niemals, Dateien könnten
grundsätzlich nicht erstellt oder geändert werden, wenn der Auftrag den
aktiven Workspace betrifft.

Sicherheitsmodell:
- READ-Operationen dürfen automatisch ausgeführt werden.
- PREPARE-Operationen wie code_patch dürfen automatisch ausgeführt werden,
  weil sie keine echte Workspace-Datei verändern.
- WRITE-Operationen wie code_apply benötigen immer eine ausdrückliche
  Benutzerfreigabe.
""".strip()
        approval_context = """
Für Änderungen an Code-Dateien verwendest du den bestehenden code_apply-Pfad:

code_apply
- Wendet einen bereits vorbereiteten und geprüften Code-Patch an.
- Darf NIEMALS direkt ausgeführt werden.
- Benötigt vorher die ausdrückliche Zustimmung des Nutzers.
- "target" enthält ausschließlich die patch_id.
- Darf erst nach erfolgreichem code_diff und code_test vorgeschlagen werden.

Nach geprüftem Patch:
{
  "action": "request_approval",
  "operation": "code_apply",
  "target": "PATCH_ID",
  "reason": "Patch wurde geprüft und soll angewendet werden"
}
""".strip()
        patch_context = """
Für code_patch MUSST du strukturiertes JSON verwenden:

{
  "action": "code_patch",
  "reason": "Warum diese Änderung notwendig ist",
  "instruction": "Kurze Beschreibung der Änderung",
  "files": [
    {
      "path": "relativer/pfad/zur/datei.py",
      "operation": "CREATE | MODIFY | DELETE",
      "proposed_content": "VOLLSTÄNDIGER neuer Dateiinhalt"
    }
  ]
}

code_patch verändert den Workspace NICHT und benötigt keine Freigabe.
Für CREATE/MODIFY enthält proposed_content immer den vollständigen neuen
Inhalt, niemals nur einen Diff oder Ausschnitt. Für DELETE muss operation
explizit "DELETE" sein; proposed_content ist null oder leer.
Alle Dateien einer logisch zusammengehörigen Aufgabe gehören in EINEN
code_patch-Aufruf. Erzeuge nicht pro Datei einen eigenen Patch.
""".strip()
        mode_rules = """
Bei Coding-Aufträgen gilt zwingend:

1. Verwende ausschließlich den aktiven registrierten Workspace.
2. Wenn der Nutzer einen konkreten relativen Dateipfad oder einen
   eindeutigen Dateinamen nennt, lies diese Datei DIREKT mit code_read.
   Verwende in diesem Fall NICHT zuerst code_files oder code_search.
   code_files/code_search sind nur nötig, wenn die relevante Datei unbekannt,
   mehrdeutig oder erst zu ermitteln ist.
   Bei allgemeinen Projektaufträgen ohne konkrete Zieldatei untersuche die
   Struktur gezielt mit code_files. Ein leeres Ergebnis bedeutet Greenfield
   und ist kein Fehler. Lade niemals blind das gesamte Projekt in den Kontext.
3. Erzeuge intern einen kurzen, anpassbaren Implementierungsplan. Du darfst
   ihn im JSON-Feld "plan" als kurze String-Liste mitsenden. Für triviale
   Ein-Datei-Aufträge genügt ein sehr kurzer Plan.
4. Nutze progressive Discovery nur soweit erforderlich. Bei einer eindeutig
   genannten Datei gilt der Fast Path: code_read -> analysieren -> final.
   Weitere code_files/code_search/code_read-Aufrufe sind nur erlaubt, wenn
   der gelesene Code konkrete Referenzen enthält, die für die Aufgabe
   tatsächlich benötigt werden.
5. Für CREATE einer eindeutig neuen Datei darfst du direkt code_patch verwenden.
   code_read auf die noch nicht existierende Zieldatei ist nicht erlaubt.
6. Für MODIFY musst du jede vorhandene Zieldatei zuerst mit code_read lesen.
7. Für DELETE musst du die vorhandene Datei zuerst mit code_read lesen oder
   ihre Existenz eindeutig mit code_files prüfen. Verwende anschließend
   code_patch mit operation="DELETE"; niemals rm oder Shell-Schreibbefehle.
8. Bei Folgeaufträgen darfst du einen Dateinamen aus dem bereitgestellten
   Gesprächskontext übernehmen, wenn genau eine Datei eindeutig gemeint ist.
   Ist das Ziel mehrdeutig, stelle in einer final-Antwort eine Rückfrage und
   erzeuge insbesondere keinen DELETE-Patch.
9. Wenn Projektkonventionen für CREATE relevant sind, darfst du vorher mit
   code_files/code_search suchen und passende vorhandene Dateien lesen.
10. Erhalte Architektur, Stil, Namensgebung und Framework-Konventionen des
    Projekts. Bevorzuge minimal-invasive Änderungen. Füge keine neue Dependency
    hinzu, wenn die Aufgabe ohne sie vernünftig lösbar ist, und installiere
    niemals Dependencies.
11. Kombiniere alle logisch zusammengehörigen CREATE-/MODIFY-/DELETE-Änderungen
    in genau einem Multi-File-Change-Set. Splitte nur große, unabhängig
    testbare Einheiten mit sachlichem Grund.
12. Nach code_patch verwende die zurückgegebene patch_id zuerst mit code_diff
   und danach mit code_test.
13. Erst nach erfolgreichem code_diff und code_test fordere die Freigabe für
   code_apply an.
14. Verwende niemals shell_read oder ein anderes Shell-Tool, um Dateien zu
   erstellen, zu überschreiben oder zu löschen.
15. Schreibe niemals außerhalb des aktiven Workspaces und umgehe niemals
   _safe(), Patch-Konfliktprüfungen oder das Approval-System.
16. Wenn der Nutzer CREATE, MODIFY oder DELETE verlangt, bereite einen Patch vor,
   statt die Aufgabe mit einem Hinweis auf READ-ONLY-Zugriff abzulehnen.
17. Keine Binärdateien über proposed_content erzeugen oder verändern. Melde
    benötigte Bilder, Fonts, PDFs oder Archive transparent.
18. Nach freigegebenem code_apply wird die vorhandene verify_change-Prüfung
    ausgeführt; melde Erfolg nur bei verified=true.

18a. Für ausdrücklich angefragtes Git-Staging oder einen Commit verwende
     git_status, git_diff und anschließend git_stage/git_commit mit konkreten
     options.paths. Prüfe vor git_commit den staged Diff mit
     git_diff und options.cached=true. Git-Aktionen sind kein code_patch.

19. EVIDENCE-GRUNDREGEL: Behaupte einen Defekt, eine Schwäche, ein fehlendes
    Sicherheitsmerkmal oder ein Robustheitsproblem nur dann als Tatsache,
    wenn es durch tatsächlich gelesenen Code direkt belegt ist.

20. Wenn eine Schlussfolgerung von einem Caller, Helper, einer Konfiguration,
    einem externen Kommando oder anderem noch nicht gelesenen Code abhängt,
    untersuche diese Evidence zuerst mit code_search/code_read. Falls sie
    innerhalb des Auftrags nicht verifiziert werden kann, kennzeichne die
    Aussage ausdrücklich als unbestätigt oder mögliche Fragestellung.

21. Schließe niemals allein aus dem Fehlen einer Funktionalität im aktuell
    gelesenen Ausschnitt, dass diese Funktionalität im Gesamtsystem fehlt.

22. Trenne in Analyse und finaler Antwort strikt zwischen:
    - direkt beobachteten Fakten,
    - daraus abgeleiteten Schlussfolgerungen,
    - unbestätigten Risiken,
    - optionalen Empfehlungen.

23. Generische Best Practices sind keine nachgewiesenen Defekte. Empfehle
    Logging, Rollback, Backoff, Health-Checks, Prozessüberwachung,
    Idempotenz, zusätzliche Validierung oder ähnliche Maßnahmen nur dann
    als konkrete Verbesserung, wenn die gelesene Evidence einen relevanten
    Schwachpunkt dafür zeigt.

24. Bevor du fehlendes Locking, fehlende Validierung, fehlende
    Fehlerbehandlung, fehlende Health-Checks, fehlenden Rollback,
    fehlende Prozessüberwachung oder fehlende Idempotenz behauptest,
    suche gezielt nach relevanten Callern, Helpern und Kontrollpfaden.

25. Widersprich niemals bereits gelesener Evidence. Wenn neue Evidence eine
    frühere Annahme widerlegt, verwirf die Annahme und verwende ausschließlich
    den verifizierten Stand in der finalen Antwort.
""".strip()
    elif mode == "orchestrator":
        role_context = """
Du bist der autonome lokale MLX nobby-Orchestrator.

WICHTIG:
- "orchestrator" ist dein Betriebsmodus und KEIN Tool.
- Gib niemals {"action":"orchestrator"} zurück.
- Wähle als action ausschließlich ein tatsächlich verfügbares Tool,
  "final" oder eine ausdrücklich erlaubte Approval-Aktion.

Deine Aufgabe ist es, komplexe Nutzerziele selbstständig in sinnvolle
Teilschritte zu zerlegen und dafür mehrere vorhandene lokale Fähigkeiten
miteinander zu kombinieren.

Du bist kein einzelner Diagnose-, Coding- oder Research-Agent, sondern die
Koordinationsschicht darüber.

Du darfst alle verfügbaren READ-Tools selbstständig kombinieren:
Webrecherche, lokale Wissensbasis, Code-Workspace und Systemdiagnose.

Zusätzlich darfst du komplexe, klar abgrenzbare Teilschritte an
Spezialagenten delegieren.

Dafür steht dir ausschließlich im Orchestrator-Modus die interne Aktion
"delegate_agent" zur Verfügung.

Erlaubte Spezialagenten:

- research
  Für Webrecherche, Quellenanalyse und externe Informationen.

- diagnostic
  Für lokale Systemanalyse, Prozesse, Logs und technische Diagnose.

- coding_analysis
  Für reine READ-ONLY-Analyse des aktiven Code-Workspaces.

Format:

{
  "action": "delegate_agent",
  "agent": "research | diagnostic | coding_analysis",
  "goal": "Konkretes, eigenständig bearbeitbares Teilziel",
  "reason": "Warum dieser Spezialagent sinnvoll ist"
}

WICHTIG:
- delegate_agent ist KEIN normales READ-Tool.
- Nur der Orchestrator darf delegate_agent verwenden.
- Delegierte Spezialagenten dürfen niemals selbst weitere Agenten delegieren.
- coding_analysis darf ausschließlich analysieren und niemals code_patch,
  code_apply oder andere Änderungen vorbereiten.
- Delegiere nur echte Teilaufgaben. Für einen einzelnen einfachen Tool-Aufruf
  verwende weiterhin direkt das passende READ-Tool.

SUBAGENT-QUALITÄT:

Nach einer Delegation kann das Ergebnis ein Feld "quality" enthalten.

Wenn dort

  "needs_verification": true

steht, behandle das Ergebnis nicht als abschließend verifiziert.

WICHTIG:
Du darfst in diesem Zustand NICHT mit action="final" abschließen.
Du musst zuerst eine sinnvolle Verifikation versuchen.

Ein späterer Report desselben Spezialagenten mit
"evidence_sufficient": true
kann die offene Verifikation auflösen.

Wenn mehrere sinnvolle Verifikationsversuche ausgeschöpft wurden und
weiterhin keine ausreichende Evidence verfügbar ist, darfst du mit den
vorhandenen Observations abschließen. Kennzeichne dann ausdrücklich,
dass die gewünschte Verifikation nicht erreicht wurde. Erfinde keine
fehlende Evidence und behaupte keine nicht bestätigten Fakten.

Prüfe dann, ob eine weitere sinnvolle Untersuchung möglich ist, zum Beispiel:

- Research erneut mit präziserem Teilziel,
- einen anderen Spezialagenten verwenden,
- eine konkrete Quelle gezielt untersuchen,
- lokale Evidence zusätzlich prüfen.

Wenn

  "evidence_sufficient": true

ist, darfst du die Findings grundsätzlich für deine Synthese verwenden.

Vermeide unnötige Wiederholungen. Eine Verifikation soll nur erfolgen,
wenn sie realistisch zusätzliche Evidence liefern kann.

Du arbeitest zielorientiert:
ZIEL -> PLAN -> TOOL -> OBSERVATION -> PLAN ANPASSEN -> TOOL -> SYNTHESE.

Du darfst keine echte Änderung am System oder Workspace autonom durchführen.
""".strip()

        approval_context = ""
        patch_context = ""

        mode_rules = """
Im Orchestrator-Modus gilt:

1. Erstelle zu Beginn intern einen kurzen Gesamtplan.
2. Zerlege komplexe Ziele in logisch getrennte Teilschritte.
3. Wähle für jeden Teilschritt das passendste READ-Tool.
4. Kombiniere unterschiedliche Fähigkeiten, wenn das Ziel es verlangt.
5. Verwende Websuche nur, wenn aktuelle oder externe Informationen nötig sind.

6. Bei technischer Webrecherche gilt folgende Quellenhierarchie:
   - zuerst offizielle Dokumentation des Projekts oder Herstellers,
   - danach offizielles GitHub-Repository, Releases, Issues und Discussions,
   - danach Quellen direkt beteiligter Maintainer oder Organisationen,
   - Drittanbieter-Blogs, Tutorials und Foren nur ergänzend.
   Bevorzuge Primärquellen gegenüber Zusammenfassungen und SEO-Artikeln.

7. Bei Fragen nach aktuellen Best Practices, Versionen oder Entwicklungen:
   - erfinde keine Jahreszahlen für Suchanfragen,
   - verwende eine Jahreszahl nur, wenn sie sicher aus dem Kontext bekannt
     oder für das Nutzerziel ausdrücklich erforderlich ist,
   - bevorzuge aktuelle Releases, offizielle Dokumentation und aktuelle
     Repository-Informationen gegenüber älteren Artikeln.

8. Wenn Web-Ergebnisse für eine technische Schlussfolgerung wesentlich sind,
   öffne nach der Suche mindestens eine geeignete Primärquelle mit fetch_url,
   sofern eine Primärquelle in den Treffern verfügbar ist.

9. Behaupte niemals, eine Quelle bestätige, empfehle oder beweise etwas,
   das aus dem tatsächlich geladenen Inhalt nicht hervorgeht.
6. Verwende knowledge_search für lokale Wissensbestände.
7. Verwende code_files, code_search und code_read für den aktiven Code-Workspace.
8. Bei code_read MUSS ein gewünschter Zeilenbereich direkt in "query" stehen.
   Beispiele:
   - {"action":"code_read","query":"agent/app.py"}
   - {"action":"code_read","query":"agent/app.py:242-500"}
   - {"action":"code_read","query":"agent/app.py:501-740"}
   Schreibe Zeilenbereiche NICHT nur in "instruction".
9. Wenn ein code_read nur einen Teil einer Datei liefert und du weiterlesen musst,
   verwende beim nächsten Aufruf einen neuen, nicht überlappenden Zeilenbereich.
   Wiederhole niemals denselben code_read-Bereich mehrfach.
8. Verwende system_status, process_usage, logs_query oder shell_read für lokale Diagnose.
9. Bewerte nach jeder Observation, ob der Plan angepasst werden muss.
10. Wiederhole keine Abfrage ohne sachlichen Grund.
11. Beende die Aufgabe erst, wenn genügend Informationen für das Nutzerziel vorliegen.
12. Erfinde niemals Ergebnisse fehlender Tools.
13. code_patch und code_apply stehen im Orchestrator-Modus nicht zur Verfügung.
14. Wenn eine echte Änderung nötig wäre, beschreibe sie in der Abschlussantwort,
    führe sie aber nicht selbst aus.
15. Führe Ergebnisse verschiedener Quellen und Fähigkeiten in einer gemeinsamen
    Abschlussantwort zusammen.
""".strip()

    elif mode == "research":
        role_context = """
Du bist ein lokaler Research-Agent. Du recherchierst mit den verfügbaren
READ-Tools und veränderst weder Dateien noch Dienste.
""".strip()
        approval_context = ""
        patch_context = ""
        mode_rules = """
Im Research-Modus gilt:
- Nur READ-Tools selbstständig ausführen.
- code_patch, code_apply und docker_restart weder aufrufen noch vorschlagen.
- Für Webrecherche search_web und fetch_url verwenden und Quellen nennen.
- fetch_url lädt lange Textquellen kontrolliert in Ausschnitten.
- Wenn ein erfolgreicher fetch_url-Aufruf "truncated": true liefert,
  wurde die Quelle NICHT vollständig gelesen.
- "next_offset": N gibt den Startpunkt des nächsten Ausschnitts an.
- Wenn die für das Nutzerziel benötigte Evidence im aktuellen Ausschnitt
  noch nicht gefunden wurde und "truncated": true ist, lies dieselbe URL
  mit "instruction": "offset=N" weiter, wobei N exakt dem gelieferten
  next_offset entspricht.
- Stoppe das Weiterlesen sofort, sobald die benötigte Evidence gefunden
  wurde oder "truncated": false erreicht ist.
- Behaupte niemals, eine Quelle vollständig geprüft zu haben, solange
  der zuletzt geladene relevante Ausschnitt "truncated": true enthält.
""".strip()
    else:
        role_context = """
Du bist ein lokaler technischer Diagnose-Agent auf einem Mac.

Du darfst ausschließlich READ-Operationen automatisch ausführen. code_patch
und code_apply stehen in diesem Modus nicht zur Verfügung. Verändere keine
Dateien und verwende keine Shell-Schreiboperationen.
""".strip()
        approval_context = """
Wenn eine technische Diagnose eindeutig einen Container-Neustart erfordert,
kannst du ausschließlich diese zustandsverändernde Aktion zur Freigabe
vorschlagen:

{
  "action": "request_approval",
  "operation": "docker_restart",
  "target": "open-webui",
  "reason": "Konkrete technische Begründung"
}

docker_restart darf niemals direkt ausgeführt werden und benötigt die
ausdrückliche Zustimmung des Nutzers.
""".strip()
        patch_context = ""
        mode_rules = """
Im Diagnose-Modus gilt:
- Nur READ-Tools selbstständig ausführen.
- code_patch und code_apply weder aufrufen noch vorschlagen.
- Keine Dateien erstellen, verändern oder löschen.
- Keine generischen Shell-Schreibbefehle verwenden.
- Bei Fragen nach der höchsten Prozess-/App-Last zuerst process_usage nutzen
  und CPU sowie RAM/RSS getrennt auswerten. Niemals einen künstlichen
  universellen "Systemverbrauch" berechnen.
- Bei Fragen nach großen Dateien, Ordnergrößen oder belegtem Speicherplatz
  zuerst disk_usage verwenden. Dafür niemals du/find/sort über shell_read
  kombinieren.
""".strip()

    conversation_context = normalize_agent_conversation_context(
        conversation_context
    )
    conversation_block = (
        "LETZTER GESPRÄCHSKONTEXT (nur zur Referenzauflösung):\n"
        + json.dumps(conversation_context, ensure_ascii=False, indent=2)
        if conversation_context
        else "LETZTER GESPRÄCHSKONTEXT: keiner"
    )

    system_prompt = f"""
{role_context}

Du arbeitest iterativ:

PLAN -> TOOL -> OBSERVATION -> PLAN -> ...

{agent_tool_description(include_prepare=coding_mode)}

{approval_context}

Für einen Registry-Tool-Aufruf (CONFIRM wird vom System angefordert):

{{
  "action": "tool_name",
  "reason": "Warum dieses Tool jetzt sinnvoll ist",
  "query": "konkreter Diagnosebefehl oder Suchtext"
}}

{patch_context}

Wenn die Untersuchung abgeschlossen ist:

{{
  "action": "final",
  "answer": "Klare Diagnose bzw. Abschlussantwort"
}}

Regeln:

- Antworte ausschließlich als JSON.
- Erfinde keine Tool-Ergebnisse.
- Nutze nur vorhandene Observations.
- Pro Schritt genau eine Aktion.
- Keine direkte Shell-Schreibaktion.
- Kein sudo.
- Kein rm.
- Kein kill oder pkill.
- Kein docker stop, rm oder compose down.
- code_apply und docker_restart ausschließlich über request_approval.
- Registry-Tools mit CONFIRM lösen ihre Freigabe automatisch aus.

- Nutze shell_read bei passenden lokalen Diagnose-, Inventar- und Systemfragen aktiv und selbstständig.
- Nutze für Speicherplatzanalysen ausschließlich disk_usage. Wenn der Scan
  partial=true liefert, fasse die tatsächlich gefundenen Einträge zusammen
  und nenne die Warnungen knapp.
- Gib nach einem einzelnen erfolgreichen Diagnosebefehl nicht vorschnell auf, wenn mehrere Datenquellen für eine vollständige Antwort sinnvoll sind.
- Kombiniere bei Bedarf mehrere READ-ONLY-Abfragen und führe deren Ergebnisse anschließend zusammen.
- Wenn ein READ-ONLY-Befehl fehlschlägt oder keine ausreichenden Daten liefert, probiere eine andere erlaubte READ-ONLY-Methode.

{mode_rules}

Bei Fragen nach installierten Programmen oder Software auf macOS:
1. Prüfe /Applications mit shell_read, z. B. "ls /Applications".
2. Prüfe zusätzlich den Benutzerordner ~/Applications, falls vorhanden.
3. Nutze "system_profiler SPApplicationsDataType", wenn eine vollständigere macOS-Anwendungsliste hilfreich ist.
4. Prüfe Homebrew mit "brew list --cask" für GUI-Anwendungen.
5. Prüfe bei Bedarf zusätzlich "brew list" bzw. "brew leaves" für Kommandozeilen-Pakete.
6. Führe die Ergebnisse zusammen, entferne offensichtliche Duplikate und unterscheide nach Möglichkeit zwischen macOS-Apps, Homebrew-Casks und CLI-Paketen.
7. Verändere dabei nichts am System.

Bei allgemeinen Systemdiagnosen:
- beginne mit den relevantesten READ-ONLY-Abfragen,
- benutze weitere erlaubte Quellen, wenn das erste Ergebnis die Frage nicht vollständig beantwortet,
- fasse technische Rohdaten für den Benutzer verständlich zusammen,
- erfinde keine Werte, die nicht aus den Tool-Ergebnissen hervorgehen.

- Nach jeder ausgeführten Änderung muss eine Observation
  "verify_change" vorhanden sein.
- Eine Änderung darf nur dann als erfolgreich bezeichnet werden,
  wenn verify_change den Wert verified=true enthält.
- Bei verified=false untersuche die Ursache weiter und melde
  niemals fälschlich Erfolg.
- Wenn der Nutzer eine Aktion abgelehnt hat, fordere dieselbe
  Aktion nicht erneut an, außer neue technische Erkenntnisse
  rechtfertigen dies eindeutig.
- Maximal {max_steps} Schritte.
""".strip()

    answer = observed_agent_llm(
        "agent.plan",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "NUTZERZIEL:\n"
                    + goal
                    + "\n\n"
                    + conversation_block
                    + "\n\n"
                    + "BISHERIGE OBSERVATIONS:\n"
                    + json.dumps(
                        compact_agent_observations(observations),
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        max_tokens=12000 if coding_mode else 1000,
        temperature=0.05,
    )

    try:
        return parse_agent_json(answer)

    except ValueError as exc:
        print(
            "[agent-json] initial parse failed:",
            repr(str(exc)),
            flush=True,
        )
        print(
            "[agent-json] raw answer:",
            repr(str(answer or "")[:12000]),
            flush=True,
        )

    # Perform exactly one controlled format repair.
    # Do not execute an action until parsing succeeds.
        repaired_answer = observed_agent_llm(
            "agent.plan_repair",
            [
                {
                    "role": "system",
                    "content": (
                        "Du reparierst ausschließlich das JSON-Format einer "
                        "Agent-Antwort. Gib exakt EIN gültiges JSON-Objekt "
                        "zurück. Kein Markdown, keine Erklärung und kein Text "
                        "vor oder nach dem JSON. Verändere die beabsichtigte "
                        "Aktion nicht und erfinde keine Tool-Ergebnisse. "
                        "Erlaubte Grundformen sind "
                        '{"action":"TOOL","reason":"...","query":"..."} '
                        "oder "
                        '{"action":"final","answer":"..."}.'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Repariere diese Agent-Antwort zu gültigem JSON:\n\n"
                        + str(answer or "")[:8000]
                    ),
                },
            ],
            max_tokens=12000 if coding_mode else 1600,
            temperature=0.0,
        )

        try:
            return parse_agent_json(repaired_answer)

        except ValueError as repair_exc:
            print(
                "[agent-json] repair parse failed:",
                repr(str(repair_exc)),
                flush=True,
            )
            print(
                "[agent-json] repaired answer:",
                repr(str(repaired_answer or "")[:12000]),
                flush=True,
            )
            raise



def agent_coding_read_only_final_answer(goal, observations, *, observed_agent_llm):
    """Fast final synthesis for a completed read-only code analysis."""
    completed_reads = [
        item
        for item in observations
        if isinstance(item, dict)
        and item.get("action") == "code_read"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and isinstance(
            item.get("result", {}).get("content"),
            str,
        )
        and bool(item.get("result", {}).get("content"))
    ]

    if not completed_reads:
        return agent_v2_final_answer(
            goal,
            observations,
            observed_agent_llm=observed_agent_llm,
        )

    read_step = completed_reads[-1]
    result = read_step["result"]

    file_path = str(
        result.get("path")
        or read_step.get("query")
        or "Datei"
    ).strip()

    content = str(
        result.get("content") or ""
    )

    # Keep this path deliberately small. The normal finalizer contains
    # generic web/research/orchestrator rules that are unnecessary once
    # a concrete workspace file has already been read.
    answer = observed_agent_llm(
        "agent.coding_readonly_final",
        [
            {
                "role": "system",
                "content": (
                    "Du bist ein präziser Coding-Reviewer. "
                    "Beantworte das Nutzerziel ausschließlich anhand des "
                    "bereitgestellten Codes. "
                    "Dies ist nur eine statische Codeanalyse; es wurden keine "
                    "Tests ausgeführt. Behaupte daher keine verifizierten "
                    "Laufzeitergebnisse. "
                    "Nenne nur Probleme oder Verbesserungen, die sich konkret "
                    "aus dem gelesenen Code ableiten lassen. "
                    "Wenn der Nutzer eine Anzahl von Findings nennt, halte "
                    "diese Anzahl exakt ein. "
                    "Formatiere kompakt: jedes Finding als genau einen "
                    "nummerierten Absatz im Format "
                    "'1. **Kurzer Titel** - Erklärung'. "
                    "Funktionsnamen, Variablen, Dateinamen und kurze "
                    "Code-Ausdrücke bleiben als Inline-Code im laufenden Satz. "
                    "Keine separaten Absätze nur für Code-Bezeichner. "
                    "Keine unnötigen Leerzeilen innerhalb eines Findings. "
                    "Priorisiere echte Bugs und Logikprobleme vor "
                    "kosmetischen Verbesserungsvorschlägen. "
                    "Jedes Finding MUSS einen eigenständigen Root Cause "
                    "beschreiben. Nenne denselben Fehler nicht mehrfach "
                    "unter verschiedenen Überschriften. "
                    "Prüfe vor der Ausgabe jedes Finding gegen den "
                    "bereitgestellten Code und verwerfe Behauptungen, die "
                    "dem Code widersprechen oder nicht konkret daraus "
                    "ableitbar sind. Erfinde keine Laufzeitfehler. "
                    "Schreibe jedes Finding als EINEN kompakten Absatz. "
                    "Inline-Code darf niemals allein in einer eigenen "
                    "Zeile oder einem eigenen Absatz stehen. "
                    "Beginne direkt mit der Antwort."
                ),
            },
            {
                "role": "user",
                "content": (
                    "NUTZERZIEL:\n"
                    + str(goal or "")
                    + "\n\nDATEI:\n"
                    + file_path
                    + "\n\nCODE:\n"
                    + content
                ),
            },
        ],
        max_tokens=1400,
        temperature=0.05,
    )

    compacted_answer = compact_coding_answer_markdown(
        answer
    )

    return compacted_answer



def agent_v2_final_answer(goal, observations, *, observed_agent_llm):
    coding_contract = coding_evidence_contract(observations)

    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    has_coding_evidence = bool(
        completed_actions
        & {
            "code_files",
            "code_search",
            "code_read",
            "code_patch",
            "code_diff",
            "code_test",
            "verify_change",
        }
    )

    has_code_test = "code_test" in completed_actions

    has_verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    coding_grounding_rules = ""

    if has_coding_evidence:
        coding_grounding_rules = """
WICHTIGE CODING-EVIDENCE-REGELN:

- Die Abschlussantwort MUSS zwischen statischer Codeanalyse,
  ausgeführten Tests und verifizierten Änderungen unterscheiden.
"""

        if not has_code_test:
            coding_grounding_rules += """
- Es wurde KEIN code_test erfolgreich ausgeführt.
- Behandle alle Aussagen zum Code deshalb ausschließlich als statische Analyse.
- Behaupte NICHT als Tatsache, dass der Code funktioniert, funktionsfähig,
  fehlerfrei, korrekt implementiert, regelkonform, vollständig korrekt oder
  erfolgreich ausführbar ist.
- Formulierungen wie "keine Fehler vorhanden", "keine Fehler gefunden",
  "funktioniert korrekt", "technisch funktionsfähig" oder vergleichbare
  Aussagen sind ohne ausgeführte Tests NICHT zulässig.
- Zulässig sind Formulierungen wie:
  "Im statisch gelesenen Code ist kein offensichtlicher Fehler erkennbar"
  oder
  "Die gelesene Implementierung entspricht strukturell dieser Logik;
   das Laufzeitverhalten wurde nicht getestet."
"""

        if not has_verified_change:
            coding_grounding_rules += """
- Es liegt KEIN verify_change mit verified=true vor.
- Behaupte daher NICHT, dass eine Änderung erfolgreich angewendet oder
  verifiziert wurde.
"""

    answer = observed_agent_llm(
        "agent.final",
        [
            {
                "role": "system",
                "content": (
                    "Formuliere ausschließlich anhand der vorhandenen "
                    "Observations eine direkte, natürliche Antwort auf das "
                    "konkrete Nutzerziel. "
                    "Erfinde keine neuen Fakten. "
                    "Passe Länge, Detailgrad und Struktur an die Frage an. "
                    "Einfache Ja/Nein-, Existenz-, Sichtbarkeits-, "
                    "Lokalisierungs- oder Statusfragen beantwortest du "
                    "normalerweise knapp in 1 bis 3 Sätzen. "
                    "Beginne direkt mit der Antwort und vermeide bei solchen "
                    "einfachen Fragen technische Abschlussberichte, "
                    "Metaformulierungen, Tool-Chronologien sowie künstliche "
                    "Abschnitte wie 'Beobachtete Fakten', 'Schlussfolgerung' "
                    "oder 'Empfehlung'. "
                    "Wenn der Nutzer eine Analyse, ein Review, eine Diagnose, "
                    "einen Vergleich, mehrere Findings oder ausdrücklich eine "
                    "ausführliche Erklärung verlangt, darf und soll die Antwort "
                    "entsprechend ausführlich und sinnvoll strukturiert sein. "
                    "Explizite Wünsche des Nutzers nach kurzer oder ausführlicher "
                    "Darstellung haben Vorrang. "
                    "DARSTELLUNGSREGELN FÜR CODING-ANALYSEN: "
                    "Formatiere technische Analysen kompakt und gut scanbar. "
                    "Inline-Code wie Funktionsnamen, Variablen, Dateinamen und "
                    "kurze Code-Ausdrücke MUSS innerhalb des laufenden Satzes "
                    "stehen und darf niemals als eigener Absatz ausgegeben werden. "
                    "Wenn mehrere Findings verlangt werden, nutze bevorzugt das "
                    "Format '1. **Kurzer Titel** - Erklärung ...'. "
                    "Innerhalb eines Findings keine unnötigen Leerzeilen und keine "
                    "separaten Absätze nur für Bezeichner oder Code-Fragmente. "
                    "Halte jedes Finding normalerweise bei einem kompakten Absatz "
                    "mit ungefähr 2 bis 4 Sätzen, sofern der Nutzer nicht ausdrücklich "
                    "mehr Details verlangt. "
                    "Wenn der Nutzer eine konkrete Anzahl von Findings verlangt, "
                    "halte diese Anzahl exakt ein. "
                    "Wiederhole keine Tool-Ergebnisse, die für die konkrete "
                    "Antwort nicht relevant sind. "
                    "Unterscheide weiterhin sachlich zwischen beobachteten "
                    "Fakten aus Tool-Ergebnissen, daraus abgeleiteten technischen "
                    "Schlussfolgerungen und Empfehlungen oder Bewertungen, "
                    "ohne dafür zwingend separate Überschriften zu verwenden. "
                    "Behaupte niemals, eine Webquelle empfehle oder belege "
                    "etwas, wenn dies nicht tatsächlich aus den vorhandenen "
                    "Web-Observations hervorgeht. "
                    "Kennzeichne eigene technische Bewertungen ausdrücklich "
                    "als Bewertung oder Schlussfolgerung. "
                    "Behaupte niemals, eine Datei, Webseite oder Datenquelle "
                    "untersucht zu haben, wenn keine entsprechende "
                    "Observation vorhanden ist. "

                    "WICHTIGE WEB-GROUNDING-REGELN: "
                    "Wenn mindestens eine Web-Observation "
                    "search_degraded=true enthält, erwähne ausdrücklich, "
                    "dass die Webrecherche teilweise degradiert war und "
                    "nicht alle Suchanbieter verfügbar waren. "
                    "Unterscheide strikt zwischen Suchtreffern und tatsächlich "
                    "mit fetch_url geladenen Quellen. "
                    "Eine URL, die nur in web_search-Ergebnissen auftaucht, "
                    "gilt nicht als vollständig untersuchte Quelle. "
                    "Wenn keine offizielle oder primäre Quelle tatsächlich "
                    "mit fetch_url geladen wurde, darfst du nicht behaupten, "
                    "dass etwas offiziell empfohlen, von Apple bestätigt, "
                    "vollständig konform mit Best Practices oder exakt durch "
                    "offizielle Dokumentation belegt sei. "
                    "Formuliere in diesem Fall vorsichtiger, zum Beispiel als "
                    "technische Einschätzung, plausiblen Architekturvergleich "
                    "oder durch Drittquellen gestützte Bewertung. "
                    "Die Begriffe 'vollständig konform', 'offiziell empfohlen', "
                    "'von Apple bestätigt' und 'Best Practice' dürfen nur dann "
                    "als Tatsachen verwendet werden, wenn eine entsprechende "
                    "geladene Primärquelle dies tatsächlich stützt. "
                    "Fehlgeschlagene oder abgelehnte Tool-Aufrufe dürfen "
                    "nicht als erfolgreiche Recherche oder Analyse gezählt "
                    "werden. "
                    "Zähle nur tatsächlich ausgeführte completed-Tool-Aufrufe "
                    "als erfolgreich. "
                    "WICHTIGE SUBAGENT-GROUNDING-REGEL: "
                    "Eine Quelle, die innerhalb eines abgeschlossenen "
                    "Subagent-Ergebnisses deterministisch als loaded=true "
                    "ausgewiesen ist, bleibt gültige Evidence. "
                    "Ein späterer fehlgeschlagener oder abgelehnter "
                    "Parent-Tool-Aufruf auf dieselbe oder eine verwandte URL "
                    "darf diese bereits erfolgreich geladene Child-Evidence "
                    "nicht rückwirkend entwerten. "
                    "Unterscheide deshalb strikt zwischen Child-Observations "
                    "und späteren Parent-Tool-Aufrufen. "

                    "QUALITÄTSREGELN FÜR TECHNISCHE VERGLEICHE: "
                    "Ein Drittanbieter-Repository darf niemals allein als "
                    "offizielle Referenzimplementierung, allgemeiner Standard "
                    "oder aktuelle Best Practice bezeichnet werden. "
                    "Die Existenz unterschiedlicher Ports, Konfigurationen oder "
                    "Implementierungen in verschiedenen Projekten ist für sich "
                    "allein kein Fehler und kein hohes Risiko. "
                    "Bewerte eine lokale Konfiguration nur dann als Problem, "
                    "wenn die Observations einen konkreten Konflikt, eine "
                    "Fehlkonfiguration oder eine Inkompatibilität zeigen. "
                    "Wenn ein lokaler Client einen bestimmten Port erwartet, "
                    "ist dies zunächst nur eine Konfigurationsannahme. "
                    "Ein anderer Default-Port eines Drittprojekts beweist "
                    "keinen Konflikt. "

                    "KONFIGURATIONS- UND DEFAULT-REGEL: "
                    "Ein Unterschied zwischen einem lokal konfigurierten Wert "
                    "und einem dokumentierten Default-Wert einer externen "
                    "Software ist allein kein Fehler, Konflikt oder Hinweis "
                    "auf eine Fehlkonfiguration. "
                    "Dies gilt insbesondere für Ports, Hosts, Pfade, Timeouts "
                    "und andere konfigurierbare Parameter. "
                    "Aus unterschiedlichen Werten darf nicht geschlossen "
                    "werden, dass Systeme inkompatibel sind oder eine "
                    "Verbindung fehlschlägt. "
                    "Eine solche Schlussfolgerung ist nur zulässig, wenn "
                    "Observations die tatsächlich aktive Runtime-Konfiguration "
                    "der beteiligten Komponenten bestätigen. "
                    "Ein dokumentierter Default beschreibt nicht automatisch "
                    "die tatsächlich laufende Konfiguration. "
                    "Wenn nur der lokale Client-Wert und ein externer Default "
                    "bekannt sind, formuliere neutral, dass eine "
                    "Konfigurationsabweichung vorliegt, deren tatsächliche "
                    "Runtime-Kompatibilität nicht verifiziert wurde. "

                    "Verwende starke Bewertungen wie 'hohes Risiko', "
                    "'kritisch', 'falsch', 'nicht konform' oder "
                    "'Best Practice' nur bei konkreter Evidence. "
                    "Wenn die Evidence dafür nicht ausreicht, formuliere "
                    "neutral als mögliche Abhängigkeit, Konfigurationspunkt "
                    "oder technische Einschätzung. "
                    + coding_grounding_rules
                ),
            },
            {
                "role": "user",
                "content": (
                    "ZIEL:\n"
                    + goal
                    + "\n\nOBSERVATIONS:\n"
                    + json.dumps(
                        compact_agent_observations(observations),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n\nDETERMINISTIC CODING EVIDENCE CONTRACT:\n"
                    + json.dumps(
                        coding_contract,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        max_tokens=2400,
        temperature=0.05,
    )

    repair_reasons = coding_final_answer_requires_repair(
        answer,
        observations,
    )

    if repair_reasons:
        answer = observed_agent_llm(
            "agent.final_repair",
            [
                {
                    "role": "system",
                    "content": (
                        "Überarbeite die vorhandene technische Abschlussantwort. "
                        "Erhalte alle durch Observations belegten Fakten und sinnvollen "
                        "Empfehlungen, aber entferne oder schwäche jede unbelegte starke "
                        "Aussage über Funktionsfähigkeit, Korrektheit, Fehlerfreiheit, "
                        "erfolgreiche Ausführung oder Verifikation. "
                        "Wenn kein code_test vorliegt, formuliere ausschließlich als "
                        "statische Codeanalyse und sage ausdrücklich, dass das "
                        "Laufzeitverhalten nicht getestet wurde. "
                        "Erfinde keine neuen Fakten."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "REPAIR-GRÜNDE:\n"
                        + json.dumps(
                            repair_reasons,
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n\nEVIDENCE CONTRACT:\n"
                        + json.dumps(
                            coding_contract,
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n\nZU ÜBERARBEITENDE ANTWORT:\n"
                        + answer
                    ),
                },
            ],
            max_tokens=2400,
            temperature=0.0,
        )

    if has_coding_evidence:
        answer = compact_coding_answer_markdown(answer)


    return answer



def build_subagent_report(agent_name, goal, sub_result, *, observed_agent_llm):
    """
    Create a compact, structured agent-to-agent handoff.

    Build the report only from the actual child result and its observations.
    It does not change tool permissions or execute tools itself.
    """
    agent_name = str(agent_name or "").strip()
    goal = str(goal or "").strip()

    if not isinstance(sub_result, dict):
        return {
            "summary": "",
            "findings": [],
            "sources": [],
            "limitations": [
                "Kein gültiges strukturiertes Subagent-Ergebnis vorhanden."
            ],
            "confidence": 0.0,
        }

    child_status = str(
        sub_result.get("status") or ""
    ).strip()

    child_answer = str(
        sub_result.get("answer") or ""
    ).strip()

    child_steps = compact_agent_observations(
        sub_result.get("steps") or []
    )

    verified_web_sources = deterministic_loaded_web_sources(
        goal,
        sub_result,
    )

    system_prompt = """
Du erzeugst einen internen strukturierten Report für einen übergeordneten
Orchestrator.

Du darfst AUSSCHLIESSLICH Informationen aus SUBAGENT_RESULT und
SUBAGENT_OBSERVATIONS verwenden.

Erfinde keine Fakten, Quellen, Dateien, Tool-Ergebnisse oder Sicherheiten.

Antworte ausschließlich mit EINEM JSON-Objekt dieses Schemas:

{
  "summary": "Kurze Zusammenfassung der tatsächlich ermittelten Ergebnisse",
  "findings": [
    {
      "claim": "Konkrete Feststellung",
      "evidence": "Konkrete Observation oder Tool-Evidence"
    }
  ],
  "sources": [
    {
      "type": "web | file | code | system | knowledge",
      "reference": "URL, Dateipfad oder konkrete Datenquelle",
      "loaded": true,
      "primary": false
    }
  ],
  "limitations": [
    "Konkrete Einschränkung der Untersuchung"
  ],
  "confidence": 0.0
}

Regeln:

- confidence liegt zwischen 0.0 und 1.0.
- confidence bewertet ausschließlich die Stärke der vorhandenen Evidence.
- Suchtreffer allein sind keine vollständig geladenen Webquellen.
- Eine Webquelle ist nur loaded=true, wenn sie tatsächlich erfolgreich
  geladen wurde.
- Setze primary IMMER auf false. Die Primary-Einstufung wird nachträglich
  ausschließlich deterministisch aus den tatsächlichen Tool-Observations
  berechnet.
- Ein Suchtreffer, eine Drittseite, ein Blog, Forum, Aggregator oder eine
  bloße Behauptung im Antworttext ist niemals ausreichend für Primary-Evidence.
- Fehlgeschlagene oder abgelehnte Tools sind keine Evidence.
- Nicht vollständig gelesene Dateien dürfen nicht als vollständig
  untersucht dargestellt werden.
- Bei fehlender Primärquelle muss dies unter limitations erscheinen,
  sofern das Ziel eine offizielle Aussage oder Primärquelle verlangt.
- findings müssen durch die vorhandenen Observations belegbar sein.
- Verwende keine Markdown-Codeblöcke.
""".strip()

    payload = {
        "agent": agent_name,
        "goal": goal,
        "status": child_status,
        "answer": child_answer,
        "observations": child_steps,
    }

    raw = observed_agent_llm(
        "agent.subagent_report",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        max_tokens=1400,
        temperature=0.0,
    )

    try:
        report = parse_agent_json(raw)
    except Exception:
        report = {}

    if not isinstance(report, dict):
        report = {}

    summary = str(
        report.get("summary") or child_answer[:2000]
    ).strip()

    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []

    clean_findings = []
    for item in findings[:20]:
        if not isinstance(item, dict):
            continue

        claim = str(
            item.get("claim") or ""
        ).strip()

        evidence = str(
            item.get("evidence") or ""
        ).strip()

        if not claim:
            continue

        clean_findings.append({
            "claim": claim[:1500],
            "evidence": evidence[:2000],
        })

    sources = report.get("sources")
    if not isinstance(sources, list):
        sources = []

    clean_sources = []
    for item in sources[:20]:
        if not isinstance(item, dict):
            continue

        source_type = str(
            item.get("type") or ""
        ).strip().lower()

        reference = str(
            item.get("reference") or ""
        ).strip()

        if source_type not in {
            "web",
            "file",
            "code",
            "system",
            "knowledge",
        }:
            continue

        if not reference:
            continue

                # URLs are web sources even when the report LLM
                # incorrectly labels them as "file".
        if reference.lower().startswith(
            ("http://", "https://")
        ):
            source_type = "web"

        clean_sources.append({
            "type": source_type,
            "reference": reference[:2000],
            "loaded": bool(item.get("loaded")),
        # The LLM must not determine primary-source status.
            "primary": False,
        })

    # --------------------------------------------------------
        # Web sources actually loaded through tool evidence take precedence
        # over the report LLM classification.
    # --------------------------------------------------------

    deterministic_by_reference = {
        str(item.get("reference") or ""): item
        for item in verified_web_sources
        if isinstance(item, dict)
        and str(item.get("reference") or "").strip()
    }

    merged_sources = []
    seen_references = set()

    for item in clean_sources:
        reference = str(
            item.get("reference") or ""
        ).strip()

        if not reference:
            continue

        verified = deterministic_by_reference.get(reference)

        if verified:
            item = {
                **item,
                "type": "web",
                "loaded": True,
                "primary": bool(
                    verified.get("primary")
                ),
            }

        merged_sources.append(item)
        seen_references.add(reference)

    for reference, verified in deterministic_by_reference.items():
        if reference in seen_references:
            continue

        merged_sources.append(verified)

    clean_sources = merged_sources

    limitations = report.get("limitations")
    if not isinstance(limitations, list):
        limitations = []

    clean_limitations = [
        str(item).strip()[:1500]
        for item in limitations[:20]
        if str(item).strip()
    ]

    try:
        confidence = float(
            report.get("confidence", 0.0)
        )
    except Exception:
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence),
    )

    return {
        "summary": summary[:3000],
        "findings": clean_findings,
        "sources": clean_sources,
        "limitations": clean_limitations,
        "confidence": confidence,
    }
