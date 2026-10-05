#!/usr/bin/env python3
"""One-shot helper for the coding planner compatibility fix.

This file deletes itself after applying the deterministic source/test patch so
it does not remain in the final PR diff.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    prompts = ROOT / "agent/prompts.py"
    replace_once(
        prompts,
        """Sicherheitsmodell:\n- READ-Operationen dürfen automatisch ausgeführt werden.\n- PREPARE-Operationen wie code_patch dürfen automatisch ausgeführt werden,\n  weil sie keine echte Workspace-Datei verändern.\n- WRITE-Operationen wie code_apply benötigen immer eine ausdrückliche\n  Benutzerfreigabe.\n""",
        """Sicherheitsmodell:\n- READ-Operationen dürfen automatisch ausgeführt werden.\n- PREPARE-Operationen wie code_patch dürfen automatisch ausgeführt werden,\n  weil sie keine echte Workspace-Datei verändern.\n- WRITE-Operationen wie code_apply benötigen immer eine ausdrückliche\n  Benutzerfreigabe.\n\nAktionsvertrag:\n- `normal_chat` ist KEINE gültige action und darf niemals ausgegeben werden.\n- Für allgemeine Programmier- oder Sprachfragen, die keine Workspace-Evidence\n  und keine Dateiänderung benötigen, antworte direkt mit action=`final`.\n- Verwende Registry-Tools nur, wenn das Nutzerziel tatsächlich Workspace-,\n  System- oder externe Evidence benötigt.\n""",
        "coding prompt",
    )

    runtime = ROOT / "agent/runtime.py"
    replace_once(
        runtime,
        """            if action not in self._allowed_tools(mode):\n                observations.append({\n                    \"step\": step,\n                    \"action\": action,\n                    \"status\": \"rejected\",\n                    \"reason\": (\n                        \"Tool ist nicht freigegeben\"\n                    ),\n                })\n                publish()\n                continue\n""",
        """            if action not in self._allowed_tools(mode):\n                observations.append({\n                    \"step\": step,\n                    \"action\": action,\n                    \"status\": \"rejected\",\n                    \"reason\": (\n                        \"Tool ist nicht freigegeben\"\n                    ),\n                })\n                publish()\n\n                if mode == \"coding\":\n                    rejected_same_action = sum(\n                        1\n                        for item in observations\n                        if isinstance(item, dict)\n                        and item.get(\"status\") == \"rejected\"\n                        and item.get(\"reason\") == \"Tool ist nicht freigegeben\"\n                        and str(item.get(\"action\") or \"\").strip() == action\n                    )\n\n                    if rejected_same_action >= 2:\n                        detail = (\n                            \"Coding-Planner hat wiederholt eine nicht \"\n                            f\"freigegebene Aktion gewählt: {action or '<leer>'}.\"\n                        )\n                        observations.append({\n                            \"step\": step,\n                            \"action\": \"invalid_action_circuit_breaker\",\n                            \"status\": \"failed\",\n                            \"blocked_action\": action or None,\n                            \"reason\": detail,\n                        })\n                        result = {\n                            \"status\": \"failed\",\n                            \"goal\": goal,\n                            \"steps\": observations,\n                            \"answer\": detail,\n                            \"error\": {\n                                \"code\": \"unsupported_action_loop\",\n                                \"detail\": detail,\n                            },\n                        }\n                        publish(\"failed\")\n                        return result\n\n                continue\n""",
        "runtime unsupported-action guard",
    )

    test = ROOT / "tests/test_coding_planner_compat.py"
    if test.exists():
        raise SystemExit(f"refusing to overwrite existing {test.relative_to(ROOT)}")
    test.write_text(
        '''import json\nimport unittest\n\nfrom agent import prompts\nfrom agent.model_provider import ModelRequest, ModelResponse\nfrom agent.permissions import PermissionEngine\nfrom agent.run_state import RunContext\nfrom agent.runtime import AgentRuntime, RuntimeHooks, current_runtime\nfrom agent.tool_registry import ToolRegistry\n\n\nclass FakeProvider:\n    def __init__(self, replies):\n        self.replies = iter(replies)\n        self.calls = []\n\n    def complete(self, request, *, run_context=None):\n        self.calls.append(request)\n        reply = next(self.replies)\n        return ModelResponse(json.dumps(reply), \"fake-local\", request.role, {})\n\n\ndef hooks():\n    def plan(goal, observations, **_kwargs):\n        request = ModelRequest([\n            {\"role\": \"user\", \"content\": json.dumps({\"goal\": goal, \"observations\": observations})}\n        ])\n        return json.loads(current_runtime().complete_model(request).text)\n\n    return RuntimeHooks(\n        coding_read_only_fast_final_requested=lambda goal: False,\n        ambiguous_delete_reference=lambda goal, context: False,\n        agent_choose_next_step_v2=plan,\n        agent_coding_read_only_final_answer=lambda goal, observations: \"final\",\n        agent_v2_final_answer=lambda goal, observations: \"final\",\n        orchestrator_missing_evidence=lambda goal, observations: [],\n        orchestrator_unresolved_subagent_quality=lambda observations: [],\n        orchestrator_delegate_attempts=lambda observations, name: 0,\n        orchestrator_duplicate_delegation=lambda *args: False,\n        create_agent_approval=lambda **kwargs: {},\n        build_subagent_report=lambda *args: {},\n        assess_subagent_report=lambda *args: {\"evidence_sufficient\": True},\n        compact_agent_observations=lambda observations: observations,\n        sanitize_orchestrator_web_query=lambda goal, query: query,\n        boost_orchestrator_research_query=lambda goal, query: query,\n        degraded_empty_web_search_count=lambda observations: 0,\n        canonical_github_repo_from_goal=lambda goal: None,\n    )\n\n\nclass CodingPlannerCompatibilityTests(unittest.TestCase):\n    def test_coding_prompt_explicitly_rejects_normal_chat_action(self):\n        captured = {}\n\n        def observed(_purpose, messages, **_kwargs):\n            captured[\"system\"] = messages[0][\"content\"]\n            return '{\"action\":\"final\",\"answer\":\"ok\"}'\n\n        decision = prompts.agent_choose_next_step_v2(\n            \"Explain PHP strict equality\",\n            [],\n            mode=\"coding\",\n            observed_agent_llm=observed,\n            agent_tool_description=lambda **_kwargs: \"TOOLS\",\n            _looks_like_disk_usage_request=lambda _goal: False,\n        )\n\n        self.assertEqual(decision[\"action\"], \"final\")\n        self.assertIn(\"`normal_chat` ist KEINE gültige action\", captured[\"system\"])\n        self.assertIn(\"antworte direkt mit action=`final`\", captured[\"system\"])\n\n    def test_repeated_unsupported_coding_action_hits_circuit_breaker(self):\n        provider = FakeProvider([\n            {\"action\": \"normal_chat\", \"reason\": \"answer normally\"},\n            {\"action\": \"normal_chat\", \"reason\": \"answer normally\"},\n        ])\n        runtime = AgentRuntime(\n            RunContext(\"compat-run\", \"chat-one\", None, None, ()),\n            provider,\n            ToolRegistry(permission_engine=PermissionEngine()),\n            hooks(),\n        )\n\n        result = runtime.run(\"Explain PHP ===\", mode=\"coding\")\n\n        self.assertEqual(result[\"status\"], \"failed\")\n        self.assertEqual(result[\"error\"][\"code\"], \"unsupported_action_loop\")\n        self.assertEqual(len(provider.calls), 2)\n        self.assertEqual(result[\"steps\"][-1][\"action\"], \"invalid_action_circuit_breaker\")\n        self.assertEqual(result[\"steps\"][-1][\"blocked_action\"], \"normal_chat\")\n\n\nif __name__ == \"__main__\":\n    unittest.main()\n''',
        encoding="utf-8",
    )

    Path(__file__).unlink()
    print("Applied coding planner compatibility patch and removed one-shot helper.")


if __name__ == "__main__":
    main()
