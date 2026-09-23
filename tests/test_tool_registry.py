import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent.tool_registry import Tool, ToolRegistry, UnknownToolError
from agent.permissions import Decision, PermissionDecision


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.handler = mock.Mock(return_value={"content": "result"})
        self.tool = Tool(
            name="read_file",
            description="Read a file excerpt.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            execute=self.handler,
            permission="READ",
            risks=("filesystem",),
            timeout_seconds=10,
            output_limit_chars=100,
        )

    def test_registration_lookup_and_permission_filter(self):
        self.registry.register(self.tool)
        self.assertEqual(self.registry.get("read_file"), self.tool)
        self.assertEqual(self.registry.names(), {"read_file"})
        self.assertEqual(self.registry.names(permission="READ"), {"read_file"})
        self.assertEqual(self.registry.names(permission="WRITE"), set())

    def test_definition_is_serializable_and_omits_callable(self):
        self.registry.register(self.tool)
        definition = self.registry.definitions()[0]
        self.assertEqual(json.loads(json.dumps(definition)), definition)
        self.assertEqual(definition["parameters"], self.tool.parameters)
        self.assertEqual(definition["risks"], ["filesystem"])
        self.assertEqual(definition["timeout_seconds"], 10)
        self.assertEqual(definition["output_limit_chars"], 100)
        self.assertNotIn("execute", definition)

    def test_schema_mutations_do_not_change_registered_definition(self):
        self.registry.register(self.tool)
        self.tool.parameters["properties"]["path"]["type"] = "integer"
        self.registry.get("read_file").parameters["required"].clear()
        self.registry.definitions()[0]["parameters"]["properties"].clear()
        schema = self.registry.get("read_file").parameters
        self.assertEqual(schema["properties"]["path"]["type"], "string")
        self.assertEqual(schema["required"], ["path"])

    def test_duplicate_name_does_not_replace_original_handler(self):
        self.registry.register(self.tool)
        replacement = mock.Mock()
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.registry.register(replace(self.tool, execute=replacement))
        self.registry.execute("read_file", path="file.txt")
        self.handler.assert_called_once_with(path="file.txt")
        replacement.assert_not_called()

    def test_unknown_lookup_and_execution(self):
        for operation in (self.registry.get, self.registry.execute):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(UnknownToolError, "Unknown tool: absent"):
                    operation("absent")

    def test_execution_preserves_arguments_and_result(self):
        self.registry.register(self.tool)
        result = self.registry.execute("read_file", path="folder/file.txt")
        self.handler.assert_called_once_with(path="folder/file.txt")
        self.assertIs(result, self.handler.return_value)

    def test_handler_exception_is_not_wrapped_or_retried(self):
        error = OSError("unavailable")
        self.handler.side_effect = error
        self.registry.register(self.tool)
        with self.assertRaises(OSError) as caught:
            self.registry.execute("read_file", path="file.txt")
        self.assertIs(caught.exception, error)
        self.handler.assert_called_once()

    def test_output_limit_is_metadata_and_does_not_corrupt_structured_results(self):
        result = {"content": "ä" * 200, "truncated": False}
        self.handler.return_value = result
        self.registry.register(self.tool)
        self.assertIs(self.registry.execute("read_file", path="file.txt"), result)
        self.assertEqual(self.registry.get("read_file").output_limit_chars, 100)

    def test_invalid_definitions_are_rejected(self):
        invalid = (
            {"name": "bad name"}, {"name": ""}, {"description": " "},
            {"permission": ""}, {"execute": None}, {"parameters": []},
            {"parameters": {"type": "array"}},
            {"parameters": {"type": "object", "default": float("nan")}},
            {"parameters": {"type": "object", "default": object()}},
            {"risks": ["filesystem"]}, {"risks": ("",)},
            {"timeout_seconds": 0}, {"timeout_seconds": True},
            {"timeout_seconds": float("inf")}, {"timeout_seconds": float("nan")},
            {"output_limit_chars": 0}, {"output_limit_chars": True},
            {"output_limit_chars": 1.5},
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises((ValueError, TypeError)):
                    replace(self.tool, **values)
        with self.assertRaises(TypeError):
            self.registry.register({"name": "not_a_tool"})

    def test_registries_are_independent(self):
        self.registry.register(self.tool)
        self.assertEqual(ToolRegistry().names(), set())


class AgentToolRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Agent imports recover job history; keep standalone tests off real data.
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        with mock.patch.object(Path, "home", return_value=Path(cls.temporary.name)):
            from agent import app
        cls.agent = app

    def test_catalog_matches_existing_agent_modes(self):
        expected_read = {
            "disk_usage", "shell_read", "process_usage", "system_status",
            "logs_query", "batch_status", "knowledge_search", "code_search",
            "code_files", "code_read", "code_test", "code_diff", "web_search",
            "search_web", "fetch_url",
        }
        registry = self.agent.AGENT_TOOL_REGISTRY
        expected_new = {
            "workspace_status", "shell_workspace", "git_status", "git_diff",
            "git_log", "git_stage", "git_commit", "vision_analyze",
            "image_generate", "image_edit", "image_job_status",
            "video_generate", "video_animate", "video_job_status",
            "document_search", "document_page", "file_inspect", "file_pii_audit", "file_analyze",
            "file_analysis_status",
        }
        self.assertEqual(registry.names(), expected_read | {"code_patch"} | expected_new)
        expected_automatic = expected_read
        for mode in ("diagnostic", "research", "orchestrator"):
            self.assertEqual(self.agent.allowed_agent_tools(mode), expected_automatic)
        self.assertEqual(self.agent.allowed_agent_tools("coding"), expected_automatic | {"code_patch"})
        self.assertNotIn("code_apply", registry.names())
        self.assertIn("executes_project_code", registry.get("code_test").risks)

    def test_all_registered_adapters_preserve_legacy_call_contract(self):
        arguments = {
            "goal": "Inspect project", "query": "file.txt",
            "instruction": "Read excerpt", "files": None, "options": None,
        }
        with mock.patch.object(self.agent, "_execute_legacy_agent_tool") as handler:
            registry = self.agent._build_agent_tool_registry()
            with (
                mock.patch.object(self.agent, "AGENT_TOOL_REGISTRY", registry),
                mock.patch.object(registry.permission_engine, "evaluate", return_value=PermissionDecision(Decision.ALLOW, "adapter contract")),
            ):
                for name in {
                    "disk_usage", "shell_read", "process_usage", "system_status",
                    "logs_query", "batch_status", "knowledge_search", "code_search",
                    "code_files", "code_read", "code_test", "code_diff", "web_search",
                    "search_web", "fetch_url", "code_patch",
                }:
                    with self.subTest(name=name):
                        handler.reset_mock()
                        result = self.agent.execute_read_only_agent_tool(name, **arguments)
                        handler.assert_called_once_with(name, **arguments)
                        self.assertIs(result, handler.return_value)

    def test_required_tool_arguments_are_described_without_shared_schema_state(self):
        registry = self.agent.AGENT_TOOL_REGISTRY
        for name in ("code_read", "code_diff", "code_test", "shell_read"):
            schema = registry.get(name).parameters
            self.assertEqual(schema["required"], ["goal", "query"])
            self.assertEqual(schema["properties"]["query"]["type"], "string")
        patch_schema = registry.get("code_patch").parameters
        self.assertEqual(patch_schema["required"], ["goal", "files"])
        self.assertEqual(patch_schema["properties"]["files"]["minItems"], 1)
        self.assertEqual(registry.get("git_commit").parameters["properties"]["options"]["required"], ["paths", "message"])
        self.assertEqual(registry.get("document_page").parameters["properties"]["options"]["required"], ["document_id", "page"])
        self.assertEqual(registry.get("shell_workspace").timeout_seconds, 30)
        self.assertEqual(registry.get("shell_workspace").output_limit_chars, 12000)
        self.assertEqual(registry.get("system_status").parameters["required"], ["goal"])

    def test_existing_unknown_tool_error_is_preserved(self):
        with self.assertRaisesRegex(ValueError, "Tool nicht für Agent-Ausführung freigegeben"):
            self.agent.execute_read_only_agent_tool("code_apply", "Apply patch")

    def test_registered_shell_retains_validation_and_output_limits(self):
        with mock.patch.object(self.agent.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                self.agent.execute_read_only_agent_tool("shell_read", "Inspect", query="sudo ls")
            run.assert_not_called()
            run.return_value = mock.Mock(
                returncode=0, stdout="x" * (self.agent.SHELL_READ_MAX_OUTPUT + 1), stderr="",
            )
            result = self.agent.execute_read_only_agent_tool("shell_read", "Inspect", query="ps")
            self.assertTrue(result["truncated"])
            self.assertEqual(len(result["stdout"]), self.agent.SHELL_READ_MAX_OUTPUT)
            self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_existing_handler_error_reaches_caller(self):
        error = RuntimeError("search unavailable")
        with mock.patch.object(self.agent, "tool_search_web", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                self.agent.execute_read_only_agent_tool("search_web", "Find documentation")
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
