from pathlib import Path

runtime_path = Path("agent/runtime.py")
test_path = Path("tests/test_coding_planner_compat.py")
helper_path = Path(__file__)

runtime = runtime_path.read_text()

old_block = '''        coding_write_requested = bool(\n            mode == "coding"\n            and re.search(\n                r"\\b(?:ändere|aendere|implementiere|repariere|"\n                r"behebe|fixe|ersetze|entferne|füge|fuege|"\n                r"erstelle|erzeuge|refaktoriere|überarbeite|"\n                r"ueberarbeite|lösche|loesche|verbessere|"\n                r"optimiere)\\b",\n                goal,\n                re.IGNORECASE,\n            )\n        )\n'''
new_block = '''        coding_write_probe = goal\n        if mode == "coding":\n            # Remove explicit no-write constraints before detecting mutation\n            # intent. This keeps prompts like "Do not modify any files"\n            # read-only while still recognizing English write imperatives.\n            coding_write_probe = re.sub(\n                r"\\b(?:do\\s+not|don't|dont|without)\\s+"\n                r"(?:modify|change|edit|update|write|delete|remove|create|add|"\n                r"apply|fix|implement|refactor|optimi[sz]e|improve|replace|"\n                r"rewrite)\\b",\n                "",\n                coding_write_probe,\n                flags=re.IGNORECASE,\n            )\n            coding_write_probe = re.sub(\n                r"\\b(?:nicht|ohne)\\s+"\n                r"(?:ändern|aendern|bearbeiten|modifizieren|löschen|loeschen|"\n                r"entfernen|erstellen|hinzufügen|hinzufuegen|anwenden|fixen|"\n                r"implementieren|refaktorieren|optimieren|verbessern|ersetzen)\\b",\n                "",\n                coding_write_probe,\n                flags=re.IGNORECASE,\n            )\n\n        coding_write_requested = bool(\n            mode == "coding"\n            and re.search(\n                r"\\b(?:ändere|aendere|implementiere|repariere|behebe|fixe|"\n                r"ersetze|entferne|füge|fuege|erstelle|erzeuge|refaktoriere|"\n                r"überarbeite|ueberarbeite|lösche|loesche|verbessere|optimiere|"\n                r"fix|change|modify|edit|update|write|delete|remove|create|add|"\n                r"apply|implement|refactor|optimi[sz]e|improve|replace|rewrite)\\b",\n                coding_write_probe,\n                re.IGNORECASE,\n            )\n        )\n'''
if old_block not in runtime:
    raise SystemExit("coding write-intent block not found")
runtime = runtime.replace(old_block, new_block, 1)
runtime_path.write_text(runtime)

tests = test_path.read_text()
anchor = '''    def test_repeated_unsupported_coding_action_hits_circuit_breaker_for_write_goal(self):\n'''
extra_test = '''    def test_normal_chat_stays_read_only_when_prompt_forbids_modification(self):\n        provider = FakeProvider([\n            {"action": "normal_chat", "reason": "answer normally"},\n        ])\n        runtime = AgentRuntime(\n            RunContext("compat-run", "chat-one", None, None, ()),\n            provider,\n            ToolRegistry(permission_engine=PermissionEngine()),\n            hooks(),\n        )\n\n        result = runtime.run(\n            "Explain briefly what the PHP === operator does. "\n            "Do not modify any files and do not run destructive commands.",\n            mode="coding",\n        )\n\n        self.assertEqual(result["status"], "completed")\n        self.assertEqual(result["answer"], "final")\n        self.assertEqual(len(provider.calls), 1)\n        self.assertEqual(result["steps"][-1]["action"], "normal_chat_compat")\n\n'''
if anchor not in tests:
    raise SystemExit("write-goal test anchor not found")
tests = tests.replace(anchor, extra_test + anchor, 1)
test_path.write_text(tests)

helper_path.unlink()
print("Applied bilingual coding write-intent fix and removed one-shot helper.")
