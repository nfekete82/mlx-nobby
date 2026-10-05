import json
import unittest

from agent import prompts
from agent.model_provider import ModelRequest, ModelResponse
from agent.permissions import PermissionEngine
from agent.run_state import RunContext
from agent.runtime import AgentRuntime, RuntimeHooks, current_runtime
from agent.tool_registry import ToolRegistry


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, request, *, run_context=None):
        self.calls.append(request)
        reply = next(self.replies)
        return ModelResponse(json.dumps(reply), "fake-local", request.role, {})


def hooks():
    def plan(goal, observations, **_kwargs):
        request = ModelRequest([
            {"role": "user", "content": json.dumps({"goal": goal, "observations": observations})}
        ])
        return json.loads(current_runtime().complete_model(request).text)

    return RuntimeHooks(
        coding_read_only_fast_final_requested=lambda goal: False,
        ambiguous_delete_reference=lambda goal, context: False,
        agent_choose_next_step_v2=plan,
        agent_coding_read_only_final_answer=lambda goal, observations: "final",
        agent_v2_final_answer=lambda goal, observations: "final",
        orchestrator_missing_evidence=lambda goal, observations: [],
        orchestrator_unresolved_subagent_quality=lambda observations: [],
        orchestrator_delegate_attempts=lambda observations, name: 0,
        orchestrator_duplicate_delegation=lambda *args: False,
        create_agent_approval=lambda **kwargs: {},
        build_subagent_report=lambda *args: {},
        assess_subagent_report=lambda *args: {"evidence_sufficient": True},
        compact_agent_observations=lambda observations: observations,
        sanitize_orchestrator_web_query=lambda goal, query: query,
        boost_orchestrator_research_query=lambda goal, query: query,
        degraded_empty_web_search_count=lambda observations: 0,
        canonical_github_repo_from_goal=lambda goal: None,
    )


class CodingPlannerCompatibilityTests(unittest.TestCase):
    def test_coding_prompt_explicitly_rejects_normal_chat_action(self):
        captured = {}

        def observed(_purpose, messages, **_kwargs):
            captured["system"] = messages[0]["content"]
            return '{"action":"final","answer":"ok"}'

        decision = prompts.agent_choose_next_step_v2(
            "Explain PHP strict equality",
            [],
            mode="coding",
            observed_agent_llm=observed,
            agent_tool_description=lambda **_kwargs: "TOOLS",
            _looks_like_disk_usage_request=lambda _goal: False,
        )

        self.assertEqual(decision["action"], "final")
        self.assertIn("`normal_chat` ist KEINE gültige action", captured["system"])
        self.assertIn("antworte direkt mit action=`final`", captured["system"])

    def test_normal_chat_intent_becomes_final_for_read_only_coding_question(self):
        provider = FakeProvider([
            {"action": "normal_chat", "reason": "answer normally"},
        ])
        runtime = AgentRuntime(
            RunContext("compat-run", "chat-one", None, None, ()),
            provider,
            ToolRegistry(permission_engine=PermissionEngine()),
            hooks(),
        )

        result = runtime.run("Explain PHP ===", mode="coding")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "final")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["steps"][-1]["action"], "normal_chat_compat")

    def test_normal_chat_stays_read_only_when_prompt_forbids_modification(self):
        provider = FakeProvider([
            {"action": "normal_chat", "reason": "answer normally"},
        ])
        runtime = AgentRuntime(
            RunContext("compat-run", "chat-one", None, None, ()),
            provider,
            ToolRegistry(permission_engine=PermissionEngine()),
            hooks(),
        )

        result = runtime.run(
            "Explain briefly what the PHP === operator does. "
            "Do not modify any files and do not run destructive commands.",
            mode="coding",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "final")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["steps"][-1]["action"], "normal_chat_compat")

    def test_repeated_unsupported_coding_action_hits_circuit_breaker_for_write_goal(self):
        provider = FakeProvider([
            {"action": "normal_chat", "reason": "answer normally"},
            {"action": "normal_chat", "reason": "answer normally"},
        ])
        runtime = AgentRuntime(
            RunContext("compat-run", "chat-one", None, None, ()),
            provider,
            ToolRegistry(permission_engine=PermissionEngine()),
            hooks(),
        )

        result = runtime.run("Fix PHP strict equality handling", mode="coding")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "unsupported_action_loop")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result["steps"][-1]["action"], "invalid_action_circuit_breaker")
        self.assertEqual(result["steps"][-1]["blocked_action"], "normal_chat")


if __name__ == "__main__":
    unittest.main()
