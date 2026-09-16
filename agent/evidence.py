"""Existing evidence, repetition and final-answer rules for agent execution."""

import re

FILE_EXCERPT_MAX_CHARS = 40000


def normalize_agent_conversation_context(context):
    if not isinstance(context, list):
        return []
    normalized=[]
    for entry in context[-8:]:
        if not isinstance(entry, dict):
            continue
        role=str(entry.get("role") or "").strip().lower()
        content=entry.get("content")
        if role not in {"user", "assistant"} or not isinstance(content,str):
            continue
        content=content.strip()
        if content:
            normalized.append({"role":role,"content":content[:2000]})
    return normalized



def compact_agent_observations(observations):
    """Keep iterative planning useful without reloading whole projects."""
    compact=[]
    internal_actions = {
        "code_read_search_anchor",
        "code_read_pagination",
    }

    for observation in observations:
        if observation.get("action") in internal_actions:
            continue

        entry=dict(observation)
        result=entry.get("result")
        if not isinstance(result, dict):
            compact.append(entry)
            continue
        result=dict(result)
        if entry.get("action") == "code_read" and isinstance(result.get("content"), str):
            content = result["content"]
            content_limit = FILE_EXCERPT_MAX_CHARS
            result["content"] = content[:content_limit]
            result["content_truncated"] = len(content) > content_limit
        elif entry.get("action") == "code_files" and isinstance(result.get("files"), list):
            files=result["files"]
            result["files"]=files[:100]
            result["files_truncated"]=len(files) > 100
        elif entry.get("action") in {"code_patch", "code_diff"}:
            result["files"]=[
                {
                    "path": file.get("path"),
                    "operation": file.get("operation"),
                    "added": file.get("added"),
                    "removed": file.get("removed"),
                }
                for file in result.get("files", [])
                if isinstance(file, dict)
            ]
        elif entry.get("action") == "code_test" and isinstance(result.get("results"), list):
            result["results"]=[
                {
                    **test_result,
                    "output": str(test_result.get("output") or "")[:1000],
                }
                for test_result in result["results"][:50]
                if isinstance(test_result, dict)
            ]
        entry["result"]=result
        compact.append(entry)
    return compact



def ambiguous_delete_reference(goal, conversation_context):
    value=str(goal or "").strip().lower()
    delete_intent=any(marker in value for marker in (
        "lösche", "loesche", "entferne", "delete", "remove", "kann weg",
    ))
    vague_reference=any(marker in value for marker in (
        "das wieder", "die seite wieder", "die datei wieder", "dort wieder",
        "lösche das", "loesche das", "entferne das",
    ))
    if not delete_intent or not vague_reference:
        return False
    if re.search(r"[a-z0-9_./-]+\.[a-z0-9]{1,12}\b", value):
        return False
    return not normalize_agent_conversation_context(conversation_context)



def coding_read_only_fast_final_requested(goal):
    """Detect explicit read-only analysis/review requests."""
    value = str(goal or "").strip().lower()

    if not value:
        return False

    normalized = (
        value
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )

    markers = (
        "aendere noch nichts",
        "noch nichts aendern",
        "nichts aendern",
        "nicht aendern",
        "ohne aenderungen",
        "ohne etwas zu aendern",
        "nur analysieren",
        "nur pruefen",
        "nur untersuchen",
        "read only",
        "read-only",
        "do not change",
        "don't change",
        "do not modify",
        "don't modify",
        "without changing",
    )

    return any(
        marker in normalized
        for marker in markers
    )



def orchestrator_required_evidence(goal):
    """Determine required capability groups from the user goal."""

    value = str(goal or "").lower()

    web_required = any(marker in value for marker in (
        "internet",
        "web",
        "online",
        "aktuell",
        "aktuelle",
        "aktuellen",
        "recherchiere",
        "recherchieren",
        "webrecherche",
        "best practices",
        "best-practices",
        "externe quelle",
        "externe quellen",
        "offizielle quelle",
        "offiziellen quelle",
        "offizielle dokumentation",
        "primärquelle",
        "primaerquelle",
    ))

    # Require local code evidence only when the user goal actually
    # concerns the active local workspace.
    explicit_local_code = any(marker in value for marker in (
        "lokaler code",
        "lokalen code",
        "lokale codebasis",
        "lokaler workspace",
        "lokalen workspace",
        "mein code",
        "meinen code",
        "unser code",
        "unseren code",
        "mein projekt",
        "meinem projekt",
        "unser projekt",
        "unserem projekt",
        "workspace",
        "lokale datei",
        "lokalen dateien",
        "lokale dateien",
        "im projekt",
        "im workspace",
    ))

    generic_code_request = any(marker in value for marker in (
        "quellcode analys",
        "code analys",
        "code prüfen",
        "code pruefen",
        "code untersuch",
        "code durchsuchen",
        "implementierung prüfen",
        "implementierung pruefen",
    ))

    code_required = explicit_local_code or generic_code_request

    knowledge_required = any(marker in value for marker in (
        "wissensbasis",
        "knowledge base",
        "rag",
        "lokales wissen",
        "lokale wissensbasis",
    ))

    return {
        "web": web_required,
        "code": code_required,
        "knowledge": knowledge_required,
    }



def orchestrator_observed_evidence(observations):
    """
    Determine evidence that was actually observed.

    Include both direct orchestrator tool calls and successfully completed
    tool steps from delegated specialist agents.
    """

    actions = set()

    def collect(entries):
        for item in entries or []:
            if not isinstance(item, dict):
                continue

            if item.get("status") != "completed":
                continue

            action = str(
                item.get("action") or ""
            ).strip()

            if action:
                actions.add(action)

            # Orchestrator v2:
            # include evidence from successful subagents.
            if action == "delegate_agent":
                result = item.get("result")

                if not isinstance(result, dict):
                    continue

                if result.get("status") not in {
                    "completed",
                    "max_steps",
                }:
                    continue

                child_steps = result.get("steps")

                if isinstance(child_steps, list):
                    collect(child_steps)

    collect(observations)

    return {
        "web": bool(
            actions
            & {
                "web_search",
                "search_web",
                "fetch_url",
            }
        ),
        "code": bool(
            actions
            & {
                "code_files",
                "code_search",
                "code_read",
            }
        ),
        "knowledge": (
            "knowledge_search" in actions
        ),
    }



def orchestrator_missing_evidence(goal, observations):
    required = orchestrator_required_evidence(goal)
    observed = orchestrator_observed_evidence(observations)

    return [
        capability
        for capability, needed in required.items()
        if needed and not observed.get(capability, False)
    ]



def normalize_delegate_goal(value):
    value = str(value or "").strip().lower()
    value = " ".join(value.split())
    return value[:1000]



def orchestrator_delegate_attempts(observations, agent_name):
    """
    Count delegations already run for the same specialist agent.
    """
    agent_name = str(agent_name or "").strip().lower()

    count = 0

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        if str(item.get("agent") or "").strip().lower() == agent_name:
            count += 1

    return count



def orchestrator_duplicate_delegation(
    observations,
    agent_name,
    delegate_goal,
):
    """
    Detect identical or effectively identical delegations.
    """
    agent_name = str(agent_name or "").strip().lower()
    goal_norm = normalize_delegate_goal(delegate_goal)

    if not goal_norm:
        return False

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        if str(item.get("agent") or "").strip().lower() != agent_name:
            continue

        previous_goal = normalize_delegate_goal(
            item.get("goal")
        )

        if previous_goal == goal_norm:
            return True

    return False



def orchestrator_unresolved_subagent_quality(observations):
    """
    Determine unresolved quality issues from delegated specialist agents.

    A later successful report from the same agent with
    evidence_sufficient=true resolves the open state.
    """
    state = {}

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        agent_name = str(
            item.get("agent") or ""
        ).strip().lower()

        if not agent_name:
            continue

        result = item.get("result")
        if not isinstance(result, dict):
            continue

        quality = result.get("quality")
        if not isinstance(quality, dict):
            continue

        needs_verification = bool(
            quality.get("needs_verification")
        )

        evidence_sufficient = bool(
            quality.get("evidence_sufficient")
        )

        if needs_verification:
            state[agent_name] = {
                "agent": agent_name,
                "confidence": quality.get("confidence"),
                "reason": str(
                    quality.get("reason")
                    or "Subagent-Evidence benötigt weitere Verifikation."
                ).strip(),
            }

        elif evidence_sufficient:
            state.pop(agent_name, None)

    return list(state.values())



def coding_evidence_contract(observations):
    """
    Deterministic summary of what completed coding observations can prove.
    This constrains the final LLM synthesis without trying to parse claims.
    """
    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    evidence = []

    if "code_files" in completed_actions:
        evidence.append(
            "code_files proves only that workspace file metadata/listing was inspected."
        )

    if "code_search" in completed_actions:
        evidence.append(
            "code_search proves only that matching workspace locations were searched."
        )

    if "code_read" in completed_actions:
        evidence.append(
            "code_read proves that returned source code was inspected; "
            "it does NOT prove runtime behavior or successful execution."
        )

    if "code_patch" in completed_actions:
        evidence.append(
            "code_patch proves only that a proposed patch was prepared; "
            "it does NOT prove that workspace files were changed."
        )

    if "code_diff" in completed_actions:
        evidence.append(
            "code_diff proves only that the prepared patch diff was inspected."
        )

    if "code_test" in completed_actions:
        evidence.append(
            "code_test may support test-result claims only to the extent explicitly "
            "shown by its returned test results."
        )

    verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    if verified_change:
        evidence.append(
            "verify_change with verified=true proves that the applied change passed "
            "the configured post-apply verification."
        )
    else:
        evidence.append(
            "No completed verify_change with verified=true exists. "
            "Do NOT claim that a change was successfully applied and verified."
        )

    if "code_test" not in completed_actions:
        evidence.append(
            "No completed code_test exists. Do NOT claim that tests were run or passed."
        )

    return evidence



def coding_final_answer_requires_repair(answer, observations):
    """
    Detect affirmative strong coding claims that are not supported by completed
    evidence. Explicit uncertainty/negation must not trigger the gate.
    """
    value = str(answer or "").lower()

    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    has_code_test = "code_test" in completed_actions

    has_verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    reasons = []

    # Evaluate one sentence at a time so negative statements such as
    # "The code cannot be guaranteed to run without errors" are not
    # treated as positive claims about functionality.
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", value)
        if sentence.strip()
    ]

    def is_explicitly_uncertain(sentence):
        uncertainty_markers = (
            "nicht getestet",
            "nicht ausgeführt",
            "nicht verifiziert",
            "nicht bestätigt",
            "nicht garantiert",
            "kann nicht garantiert",
            "kann nicht bestätigt",
            "lässt sich nicht bestätigen",
            "lässt sich nicht verifizieren",
            "keine tests",
            "kein test",
            "keine verifikation",
            "keine garantie",
            "nicht möglich",
            "nicht beurteilt",
            "nicht geprüft",
            "ohne laufzeittest",
            "ohne test",
        )
        return any(marker in sentence for marker in uncertainty_markers)

    if not has_code_test:
        affirmative_runtime_patterns = (
            r"\b(?:der|die|das|dieser|diese|dieses)\b.{0,80}\b"
            r"(?:funktioniert korrekt|funktioniert einwandfrei|"
            r"technisch funktionsfähig|strukturell funktionsfähig|"
            r"ist fehlerfrei|sind fehlerfrei|"
            r"ist korrekt implementiert|sind korrekt implementiert|"
            r"ist vollständig korrekt|sind vollständig korrekt|"
            r"ist regelkonform|sind regelkonform)\b",

            r"\b(?:keine fehler vorhanden|keine fehler gefunden|"
            r"keine logischen fehler vorhanden|"
            r"keine offensichtlichen fehler vorhanden)\b",
        )

        unsupported = any(
            not is_explicitly_uncertain(sentence)
            and any(
                re.search(pattern, sentence)
                for pattern in affirmative_runtime_patterns
            )
            for sentence in sentences
        )

        if unsupported:
            reasons.append(
                "Die Antwort enthält eine affirmative starke "
                "Funktions-/Korrektheitsaussage, obwohl kein completed "
                "code_test vorliegt."
            )

    if not has_verified_change:
        verification_patterns = (
            r"\b(?:änderung|patch|code)\b.{0,60}\b"
            r"(?:erfolgreich angewendet und verifiziert|"
            r"erfolgreich verifiziert|ist verifiziert|wurde verifiziert)\b",
        )

        unsupported_verification = any(
            not is_explicitly_uncertain(sentence)
            and any(
                re.search(pattern, sentence)
                for pattern in verification_patterns
            )
            for sentence in sentences
        )

        if unsupported_verification:
            reasons.append(
                "Die Antwort behauptet Verifikation ohne verify_change "
                "verified=true."
            )

    return reasons



def compact_coding_inline_paragraphs(value):
    """Join model-created paragraph breaks around inline code."""

    text = str(value or "").replace("\r\n", "\n")

    # Qwen occasionally emits:
    #
    #   In
    #
    #   `startNewGame()`
    #
    #   wird ...
    #
    # Inline code is semantic sentence content, not a paragraph.
    # Collapse blank lines around standalone inline-code fragments.
    inline_only = re.compile(
        r"(?m)"
        r"[ \t]*\n[ \t]*\n[ \t]*"
        r"(`[^`\n]+`)"
        r"[ \t]*\n[ \t]*\n[ \t]*"
    )

    previous = None

    while previous != text:
        previous = text
        text = inline_only.sub(r" \1 ", text)

    # Also handle a line break without an empty line around inline code.
    inline_line = re.compile(
        r"(?m)"
        r"(?<=\S)[ \t]*\n[ \t]*"
        r"(`[^`\n]+`)"
        r"[ \t]*\n[ \t]*"
        r"(?=\S)"
    )

    previous = None

    while previous != text:
        previous = text
        text = inline_line.sub(r" \1 ", text)

    # Markdown may put the dash separating title/explanation on its own line.
    text = re.sub(
        r"(?m)"
        r"(\*\*[^\n]+\*\*)[ \t]*\n+[ \t]*"
        r"(?:\\?-|–|—)[ \t]*",
        r"\1 - ",
        text,
    )

    # Avoid excessive vertical whitespace while preserving finding separation.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()



def compact_coding_answer_markdown(value):
    """Compact accidental paragraph breaks around inline code."""
    value = str(value or "")

    if not value.strip():
        return ""

    # Never rewrite fenced code blocks.
    # Normalize model output BEFORE splitting Markdown into protected
    # blocks. Qwen occasionally splits a numbered bold finding title
    # around an inline-code identifier:
    #
    #   3. **Fehlende Validierung bei**
    #
    #   **`setBet`**
    #
    #   - Die Funktion ...
    #
    # Convert that shape first so the normal compacting rules see one
    # coherent finding title.
    value = re.sub(
        r"(?m)^(\s*\d+[.)]\s+)\*\*([^\n*]+?)\*\*"
        r"[ \t]*\n(?:[ \t]*\n)*[ \t]*"
        r"\*\*(`[^`\n]+`)\*\*",
        r"\1**\2 \3**",
        value,
    )

    # Also join a numbered bold title with a dash placed on a later line.
    value = re.sub(
        r"(?m)^(\s*\d+[.)]\s+\*\*[^\n]+\*\*)"
        r"[ \t]*\n(?:[ \t]*\n)*[ \t]*"
        r"(?:\\?-|–|—)[ \t]*",
        r"\1 - ",
        value,
    )

    text = compact_coding_inline_paragraphs(value).strip()

    parts = re.split(
        r"(```[\s\S]*?```)",
        text,
    )

    inline_code = r"`[^`\\n]+`"

    for index in range(0, len(parts), 2):
        part = parts[index]

        # Convert:
        #
        # 1. **Finding**
        #    Explanation ...
        #
        # into:
        #
        # 1. **Finding** - Explanation ...
        part = re.sub(
            r"(?m)^(\s*\d+[.)]\s+\*\*[^\n]+\*\*)"
            r"[ \t]*\n[ \t]+(?=\S)",
            r"\1 - ",
            part,
        )

        # "In\n\n`startNewGame()`" -> "In `startNewGame()`"
        part = re.sub(
            rf"([^\n])\n[ \t]*\n[ \t]*({inline_code})",
            r"\1 \2",
            part,
        )

        # Join a numbered bold finding title with its explanation,
        # even when the explanation starts after an empty line.
        part = re.sub(
            r"(?m)^(\s*\d+[.)]\s+\*\*[^\n]+\*\*)"
            r"[ \t]*\n(?:[ \t]*\n)+[ \t]*(?=\S)",
            r"\1 - ",
            part,
        )

        # "`foo()`\n\n," -> "`foo()`,"
        part = re.sub(
            rf"({inline_code})\n[ \t]*\n[ \t]*([,.;:!?])",
            r"\1\2",
            part,
        )

        # "`undefined`\n\n-Werten" -> "`undefined`-Werten"
        part = re.sub(
            rf"({inline_code})\n[ \t]*\n[ \t]*"
            r"-([A-Za-zÄÖÜäöüß])",
            r"\1-\2",
            part,
        )

        # "`foo()`\n\nwird" -> "`foo()` wird"
        # Do not merge into headings, quotes or new list items.
        part = re.sub(
            rf"({inline_code})\n[ \t]*\n[ \t]*"
            r"(?!#|>|[-*+]\s|\d+[.)]\s)(\S)",
            r"\1 \2",
            part,
        )

        # Remove whitespace between inline code and punctuation:
        # "`bankroll` ," -> "`bankroll`,"
        part = re.sub(
            rf"({inline_code})[ \t]+([,.;:!?])",
            r"\1\2",
            part,
        )

        parts[index] = part

    result = "".join(parts)

    # Final Markdown cleanup: inline code must attach directly to
    # following punctuation.
    result = re.sub(
        r"(`[^`\n]+`)[ \t]+([,.;:!?])",
        r"\1\2",
        result,
    )

    return result



def boost_orchestrator_research_query(goal, query):
    """
    Steer technical orchestrator searches toward primary sources without
    changing regular web searches globally.
    """
    goal_value = str(goal or "").lower()
    value = str(query or "").strip()

    if not value:
        return value

    technical_markers = (
        "best practice",
        "best-practice",
        "best practices",
        "dokumentation",
        "documentation",
        "framework",
        "library",
        "bibliothek",
        "repository",
        "repo",
        "github",
        "api",
        "server",
        "installation",
        "konfiguration",
        "configuration",
        "version",
        "release",
        "inference",
        "inferenz",
    )

    is_technical = any(
        marker in goal_value or marker in value.lower()
        for marker in technical_markers
    )

    if not is_technical:
        return value

    # Do not expand the request twice.
    lower = value.lower()

    if (
        "official documentation" in lower
        or "official docs" in lower
        or "official github" in lower
    ):
        return value

    return (
        value
        + " official documentation official GitHub repository"
    )



def sanitize_orchestrator_web_query(goal, query):
    """
    Remove stale model-invented years from web queries for explicitly
    current research.
    """
    from datetime import datetime

    value = str(query or "").strip()
    goal_value = str(goal or "").lower()

    if not value:
        return value

    freshness_markers = (
        "aktuell",
        "aktuelle",
        "aktuellen",
        "neueste",
        "neuesten",
        "latest",
        "current",
        "heute",
        "best practice",
        "best-practice",
        "best practices",
    )

    if not any(marker in goal_value for marker in freshness_markers):
        return value

    current_year = datetime.now().year

    def replace_year(match):
        year = int(match.group(0))

        if year == current_year:
            return match.group(0)

        if 2000 <= year < current_year:
            return ""

        return match.group(0)

    value = re.sub(r"\b20\d{2}\b", replace_year, value)
    value = re.sub(r"\s+", " ", value).strip()

    return value



def source_is_primary_for_goal(goal, reference):
    """
    Conservatively determine whether a loaded web source qualifies as a
    primary source for the specific research goal.

    GitHub and raw GitHub project sources are accepted only when the goal
    explicitly names both the owner and repository.

    An arbitrary github.com result is not automatically a primary source.
    """
    from urllib.parse import urlsplit

    goal_value = str(goal or "").strip().lower()
    reference = str(reference or "").strip()

    if not goal_value or not reference:
        return False

    try:
        parsed = urlsplit(reference)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").lower()
    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    # --------------------------------------------------------
    # github.com/<owner>/<repo>/...
    # --------------------------------------------------------
    if host == "github.com":
        if len(parts) < 2:
            return False

        owner = parts[0].lower()
        repo = parts[1].lower()

    # --------------------------------------------------------
    # raw.githubusercontent.com/<owner>/<repo>/<branch>/...
    # --------------------------------------------------------
    elif host == "raw.githubusercontent.com":
        if len(parts) < 2:
            return False

        owner = parts[0].lower()
        repo = parts[1].lower()

    else:
        return False

    # GitHub allows .git at the end of a repository name.
    if repo.endswith(".git"):
        repo = repo[:-4]

    def normalize_identifier(value):
        return "".join(
            char
            for char in str(value or "").lower()
            if char.isalnum()
        )

    normalized_goal = normalize_identifier(goal_value)
    normalized_owner = normalize_identifier(owner)
    normalized_repo = normalize_identifier(repo)

    # Deliberately strict:
    # both the owner and repository must be identifiable in the goal.
    if not normalized_owner or not normalized_repo:
        return False

    return (
        normalized_owner in normalized_goal
        and normalized_repo in normalized_goal
    )



def deterministic_loaded_web_sources(goal, sub_result):
    """
    Extract only successfully loaded web sources from child observations and
    assign primary-source status deterministically.
    """
    sources = []

    if not isinstance(sub_result, dict):
        return sources

    seen = set()

    for observation in sub_result.get("steps") or []:
        if not isinstance(observation, dict):
            continue

        if observation.get("action") != "fetch_url":
            continue

        if observation.get("status") != "completed":
            continue

        result = observation.get("result")

        if not isinstance(result, dict):
            continue

        if result.get("ok") is not True:
            continue

        reference = str(
            result.get("url")
            or result.get("requested_url")
            or ""
        ).strip()

        if not reference:
            continue

        if reference in seen:
            continue

        seen.add(reference)

        sources.append({
            "type": "web",
            "reference": reference[:2000],
            "loaded": True,
            "primary": source_is_primary_for_goal(
                goal,
                reference,
            ),
        })

    return sources



def research_goal_requires_primary_source(goal):
    """
    Determine whether the research goal explicitly requires an official or
    primary source.
    """
    value = str(goal or "").strip().lower()

    markers = (
        "primärquelle",
        "primaerquelle",
        "primary source",
        "primary-source",
        "offizielle quelle",
        "offizieller quelle",
        "offiziellen quelle",
        "offizielle dokumentation",
        "offizieller dokumentation",
        "offiziellen dokumentation",
        "official source",
        "official documentation",
        "offizielle primärquelle",
        "offizielle primaerquelle",
    )

    return any(marker in value for marker in markers)



def assess_subagent_report(agent_name, goal, report):
    """
    Evaluate the quality of a structured subagent report deterministically
    without an additional LLM call.

    This function does not execute tools or change permissions.
    """
    agent_name = str(agent_name or "").strip().lower()
    goal = str(goal or "").strip().lower()

    if not isinstance(report, dict):
        return {
            "evidence_sufficient": False,
            "needs_verification": True,
            "confidence": 0.0,
            "findings_count": 0,
            "loaded_sources_count": 0,
            "reason": "Kein gültiger strukturierter Report vorhanden.",
        }

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

    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []

    sources = report.get("sources")
    if not isinstance(sources, list):
        sources = []

    limitations = report.get("limitations")
    if not isinstance(limitations, list):
        limitations = []

    valid_findings = [
        item
        for item in findings
        if isinstance(item, dict)
        and str(item.get("claim") or "").strip()
        and str(item.get("evidence") or "").strip()
    ]

    loaded_sources = [
        item
        for item in sources
        if isinstance(item, dict)
        and bool(item.get("loaded"))
        and str(item.get("reference") or "").strip()
    ]

    loaded_web_sources = [
        item
        for item in loaded_sources
        if str(item.get("type") or "").strip().lower() == "web"
    ]

    loaded_code_sources = [
        item
        for item in loaded_sources
        if str(item.get("type") or "").strip().lower()
        in {"code", "file"}
    ]

    loaded_primary_web_sources = [
        item
        for item in loaded_web_sources
        if bool(item.get("primary"))
    ]

    primary_source_required = (
        agent_name == "research"
        and research_goal_requires_primary_source(goal)
    )

    reasons = []
    warnings = []

    # LLM confidence is only the report's self-assessment.
    # Deterministically confirmed tool evidence takes precedence.
    deterministic_evidence_present = bool(loaded_sources)

    if confidence < 0.65:
        if deterministic_evidence_present:
            warnings.append(
                f"Niedrige Report-Confidence ({confidence:.2f}), "
                "aber deterministisch geladene Evidence ist vorhanden."
            )
        else:
            reasons.append(
                f"Niedrige Evidence-Confidence ({confidence:.2f})."
            )

    if not valid_findings:
        reasons.append(
            "Keine belastbaren Findings mit Evidence vorhanden."
        )

    if agent_name == "coding_analysis":
        if not loaded_code_sources:
            reasons.append(
                "Keine tatsächlich geladene Code-/Dateiquelle vorhanden."
            )

    if agent_name == "research":
        if not loaded_web_sources:
            reasons.append(
                "Keine tatsächlich geladene Webquelle vorhanden."
            )

        if (
            primary_source_required
            and not loaded_primary_web_sources
        ):
            reasons.append(
                "Das Research-Ziel verlangt ausdrücklich eine offizielle "
                "Quelle oder Primärquelle, aber keine tatsächlich geladene "
                "Webquelle ist als Primärquelle belegt."
            )

    evidence_sufficient = not reasons
    needs_verification = not evidence_sufficient

    return {
        "evidence_sufficient": evidence_sufficient,
        "needs_verification": needs_verification,
        "confidence": confidence,
        "findings_count": len(valid_findings),
        "loaded_sources_count": len(loaded_sources),
        "loaded_web_sources_count": len(loaded_web_sources),
        "loaded_primary_web_sources_count": len(
            loaded_primary_web_sources
        ),
        "primary_source_required": primary_source_required,
        "loaded_code_sources_count": len(loaded_code_sources),
        "limitations_count": len([
            item
            for item in limitations
            if str(item).strip()
        ]),
        "warnings": warnings,
        "reason": (
            " ".join(reasons)
            if reasons
            else (
                "Subagent-Report besitzt ausreichende strukturierte Evidence."
                + (
                    " " + " ".join(warnings)
                    if warnings
                    else ""
                )
            )
        ),
    }



def canonical_github_repo_from_goal(goal):
    """
    Conservatively extract an explicitly named GitHub owner/repo from the goal.

    Supported forms:
      - https://github.com/owner/repo
      - github.com/owner/repo
      - owner/repo

    Do not infer an unspecified repository.
    """
    value = str(goal or "").strip()

    if not value:
        return None

    patterns = (
        r'https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',
        r'github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',
        r'(?<![\w.-])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?![\w.-])',
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        owner = match.group(1).strip()
        repo = match.group(2).strip().rstrip(".,;:)")

        if not owner or not repo:
            continue

        blocked_owners = {
            "http",
            "https",
            "api",
            "v1",
            "v2",
            "docs",
        }

        if owner.lower() in blocked_owners:
            continue

        return {
            "owner": owner,
            "repo": repo,
            "url": f"https://github.com/{owner}/{repo}",
        }

    return None



def degraded_empty_web_search_count(observations):
    """
    Count executed web searches that were degraded and returned no results.
    """
    count = 0

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if item.get("action") not in {
            "web_search",
            "search_web",
        }:
            continue

        result = item.get("result")

        if not isinstance(result, dict):
            continue

        if (
            result.get("search_degraded") is True
            and not result.get("results")
        ):
            count += 1

    return count

