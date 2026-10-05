from pathlib import Path

runtime_path = Path("agent/runtime.py")
test_path = Path("tests/test_coding_planner_compat.py")
helper_path = Path(__file__)

runtime = runtime_path.read_text()

mode_anchor = '''        goal = str(goal or "").strip()\n        mode = str(mode or "diagnostic").strip().lower()\n'''
mode_replacement = '''        goal = str(goal or "").strip()\n        mode = str(mode or "diagnostic").strip().lower()\n        coding_write_requested = bool(\n            mode == "coding"\n            and re.search(\n                r"\\b(?:ändere|aendere|implementiere|repariere|"\n                r"behebe|fixe|ersetze|entferne|füge|fuege|"\n                r"erstelle|erzeuge|refaktoriere|überarbeite|"\n                r"ueberarbeite|lösche|loesche|verbessere|"\n                r"optimiere)\\b",\n                goal,\n                re.IGNORECASE,\n            )\n        )\n'''
if mode_anchor not in runtime:
    raise SystemExit("mode anchor not found")
runtime = runtime.replace(mode_anchor, mode_replacement, 1)

action_anchor = '''            action = str(\n                decision.get("action", "")\n            ).strip()\n            plan = decision.get("plan")\n'''
action_replacement = '''            action = str(\n                decision.get("action", "")\n            ).strip()\n\n            # Qwen3-Coder can emit ``normal_chat`` as an intent for a direct\n            # knowledge answer even though it is not a registered runtime tool.\n            # Normalize only read-only coding questions. Mutation requests keep\n            # the unsupported-action guard so they cannot bypass patch workflow.\n            if (\n                mode == "coding"\n                and action == "normal_chat"\n                and not coding_write_requested\n            ):\n                observations.append({\n                    "step": step,\n                    "action": "normal_chat_compat",\n                    "status": "completed",\n                    "reason": (\n                        "Coding-Modell hat normal_chat als Direktantwort-Intent "\n                        "verwendet; als final normalisiert."\n                    ),\n                })\n                publish("running", observations[-1])\n                decision = dict(decision)\n                decision["action"] = "final"\n                action = "final"\n\n            plan = decision.get("plan")\n'''
if action_anchor not in runtime:
    raise SystemExit("action anchor not found")
runtime = runtime.replace(action_anchor, action_replacement, 1)

old_final_guard = '''                if (mode == "coding" and not prepared and\n                    not any(item.get("action") == "code_apply" and\n                            item.get("status") == "rejected_by_user"\n                            for item in observations) and\n                    re.search(r"\\b(?:ändere|aendere|implementiere|repariere|"\n                              r"behebe|fixe|ersetze|entferne|füge|fuege|"\n                              r"erstelle|erzeuge|refaktoriere|überarbeite|"\n                              r"ueberarbeite|lösche|loesche|verbessere|"\n                              r"optimiere)\\b", goal, re.IGNORECASE)):\n'''
new_final_guard = '''                if (mode == "coding" and not prepared and\n                    not any(item.get("action") == "code_apply" and\n                            item.get("status") == "rejected_by_user"\n                            for item in observations) and\n                    coding_write_requested):\n'''
if old_final_guard not in runtime:
    raise SystemExit("final guard anchor not found")
runtime = runtime.replace(old_final_guard, new_final_guard, 1)
runtime_path.write_text(runtime)

tests = test_path.read_text()
old_test = '''    def test_repeated_unsupported_coding_action_hits_circuit_breaker(self):\n        provider = FakeProvider([\n            {"action": "normal_chat", "reason": "answer normally"},\n            {"action": "normal_chat", "reason": "answer normally"},\n        ])\n        runtime = AgentRuntime(\n            RunContext("compat-run", "chat-one", None, None, ()),\n            provider,\n            ToolRegistry(permission_engine=PermissionEngine()),\n            hooks(),\n        )\n\n        result = runtime.run("Explain PHP ===", mode="coding")\n\n        self.assertEqual(result["status"], "failed")\n        self.assertEqual(result["error"]["code"], "unsupported_action_loop")\n        self.assertEqual(len(provider.calls), 2)\n        self.assertEqual(result["steps"][-1]["action"], "invalid_action_circuit_breaker")\n        self.assertEqual(result["steps"][-1]["blocked_action"], "normal_chat")\n'''
new_test = '''    def test_normal_chat_intent_becomes_final_for_read_only_coding_question(self):\n        provider = FakeProvider([\n            {"action": "normal_chat", "reason": "answer normally"},\n        ])\n        runtime = AgentRuntime(\n            RunContext("compat-run", "chat-one", None, None, ()),\n            provider,\n            ToolRegistry(permission_engine=PermissionEngine()),\n            hooks(),\n        )\n\n        result = runtime.run("Explain PHP ===", mode="coding")\n\n        self.assertEqual(result["status"], "completed")\n        self.assertEqual(result["answer"], "final")\n        self.assertEqual(len(provider.calls), 1)\n        self.assertEqual(result["steps"][-1]["action"], "normal_chat_compat")\n\n    def test_repeated_unsupported_coding_action_hits_circuit_breaker_for_write_goal(self):\n        provider = FakeProvider([\n            {"action": "normal_chat", "reason": "answer normally"},\n            {"action": "normal_chat", "reason": "answer normally"},\n        ])\n        runtime = AgentRuntime(\n            RunContext("compat-run", "chat-one", None, None, ()),\n            provider,\n            ToolRegistry(permission_engine=PermissionEngine()),\n            hooks(),\n        )\n\n        result = runtime.run("Fix PHP strict equality handling", mode="coding")\n\n        self.assertEqual(result["status"], "failed")\n        self.assertEqual(result["error"]["code"], "unsupported_action_loop")\n        self.assertEqual(len(provider.calls), 2)\n        self.assertEqual(result["steps"][-1]["action"], "invalid_action_circuit_breaker")\n        self.assertEqual(result["steps"][-1]["blocked_action"], "normal_chat")\n'''
if old_test not in tests:
    raise SystemExit("test anchor not found")
tests = tests.replace(old_test, new_test, 1)
test_path.write_text(tests)

helper_path.unlink()
print("Applied coding normal_chat compatibility patch and removed one-shot helper.")
