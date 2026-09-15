import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import app as agent_app
from agent import code_workspaces


class CodeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.config = self.base / "config"
        self.workspace_one = self.base / "workspace-one"
        self.workspace_two = self.base / "workspace-two"
        self.workspace_one.mkdir()
        self.workspace_two.mkdir()

        self.constant_patch = mock.patch.multiple(
            code_workspaces,
            ROOT=self.config,
            WORKSPACES=self.config / "workspaces.json",
            PATCHES=self.config / "patches",
            SNAPSHOTS=self.config / "snapshots",
            TESTS=self.config / "tests",
            AUDIT=self.config / "audit" / "changes.jsonl",
        )
        self.constant_patch.start()
        with agent_app.PENDING_AGENT_ACTIONS_LOCK:
            agent_app.PENDING_AGENT_ACTIONS.clear()
        with agent_app.ACTIVE_AGENT_RUNS_LOCK:
            agent_app.ACTIVE_AGENT_RUNS.clear()

    def tearDown(self):
        with agent_app.PENDING_AGENT_ACTIONS_LOCK:
            agent_app.PENDING_AGENT_ACTIONS.clear()
        with agent_app.ACTIVE_AGENT_RUNS_LOCK:
            agent_app.ACTIVE_AGENT_RUNS.clear()
        self.constant_patch.stop()
        self.temporary_directory.cleanup()

    def add_workspace(self, path=None):
        return code_workspaces.add_workspace(
            str(path or self.workspace_one),
            activate=True,
        )

    def test_registers_workspace_and_reuses_existing_entry(self):
        first = self.add_workspace()
        second = self.add_workspace()

        self.assertEqual(first["workspace_id"], second["workspace_id"])
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(
            code_workspaces.active_workspace()["root_path"],
            str(self.workspace_one.resolve()),
        )
        self.assertEqual(len(code_workspaces.list_workspaces()), 1)

    def test_reregistering_workspace_updates_only_explicit_test_commands(self):
        workspace = self.add_workspace()
        command = [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "raise SystemExit(Path('checked.txt').read_text() != 'checked\\n')"
            ),
        ]

        updated = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[command],
            activate=True,
        )
        self.assertEqual(
            code_workspaces._workspace(workspace["workspace_id"])["test_commands"],
            [command],
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create text",
            [{"path": "checked.txt", "proposed_content": "checked\n"}],
        )
        test_result = code_workspaces.test(patch["patch_id"])
        self.assertTrue(test_result["passed"])
        self.assertEqual(test_result["checks_run"], 1)
        preserved = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=None,
            activate=True,
        )
        self.assertEqual(
            code_workspaces._workspace(workspace["workspace_id"])["test_commands"],
            [command],
        )
        cleared = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[],
            activate=True,
        )

        self.assertEqual(updated["workspace_id"], workspace["workspace_id"])
        self.assertEqual(preserved["workspace_id"], workspace["workspace_id"])
        self.assertEqual(cleared["workspace_id"], workspace["workspace_id"])
        self.assertEqual(
            code_workspaces._workspace(workspace["workspace_id"])["test_commands"],
            [],
        )

    def test_detects_node_test_script(self):
        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": "vitest run",
                },
            }),
            encoding="utf-8",
        )
        (self.workspace_one / "package-lock.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            side_effect=lambda binary: f"/usr/bin/{binary}",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        self.assertIn(
            ["npm", "run", "test"],
            [entry["command"] for entry in result["detected"]],
        )

    def test_does_not_invent_node_test_without_script(self):
        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "start": "node app.js",
                },
            }),
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/npm",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        commands = [
            entry["command"]
            for entry in result["detected"] + result["recommended"]
        ]

        self.assertNotIn(["npm", "run", "test"], commands)

    def test_node_lockfiles_select_expected_package_manager(self):
        cases = (
            ("package-lock.json", ["npm", "run", "test"]),
            ("pnpm-lock.yaml", ["pnpm", "run", "test"]),
            ("yarn.lock", ["yarn", "test"]),
        )

        for lockfile, expected in cases:
            with self.subTest(lockfile=lockfile):
                for candidate in (
                    "package-lock.json",
                    "pnpm-lock.yaml",
                    "yarn.lock",
                ):
                    target = self.workspace_one / candidate
                    if target.exists():
                        target.unlink()

                (self.workspace_one / "package.json").write_text(
                    json.dumps({
                        "scripts": {
                            "test": "runner",
                        },
                    }),
                    encoding="utf-8",
                )
                (self.workspace_one / lockfile).write_text(
                    "lock\n",
                    encoding="utf-8",
                )

                workspace = self.add_workspace()

                with mock.patch.object(
                    code_workspaces.shutil,
                    "which",
                    side_effect=lambda binary: f"/usr/bin/{binary}",
                ):
                    result = code_workspaces.detect_test_commands(
                        workspace["workspace_id"]
                    )

                self.assertIn(
                    expected,
                    [
                        entry["command"]
                        for entry in result["detected"]
                    ],
                )

    def test_node_default_placeholder_is_not_detected_as_test(self):
        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": (
                        'echo "Error: no test specified" && exit 1'
                    ),
                },
            }),
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/npm",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        commands = [
            entry["command"]
            for entry in result["detected"] + result["recommended"]
        ]

        self.assertNotIn(["npm", "run", "test"], commands)
        self.assertTrue(
            any(
                warning.get("warning") == "NODE_TEST_PLACEHOLDER"
                for warning in result["warnings"]
            )
        )

    def test_pyproject_without_pytest_configuration_does_not_invent_pytest(self):
        (self.workspace_one / "pyproject.toml").write_text(
            "[project]\nname = \"example\"\n",
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/pytest",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        commands = [
            entry["command"]
            for entry in result["detected"] + result["recommended"]
        ]

        self.assertNotIn(["pytest"], commands)

    def test_detects_explicit_pytest_configuration(self):
        (self.workspace_one / "pyproject.toml").write_text(
            (
                "[project]\n"
                "name = \"example\"\n\n"
                "[tool.pytest.ini_options]\n"
                "testpaths = [\"tests\"]\n"
            ),
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            side_effect=lambda binary: (
                "/usr/bin/pytest"
                if binary == "pytest"
                else None
            ),
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        self.assertIn(
            ["pytest"],
            [entry["command"] for entry in result["detected"]],
        )

    def test_detects_unittest_only_from_actual_unittest_test(self):
        tests = self.workspace_one / "tests"
        tests.mkdir()

        (tests / "test_example.py").write_text(
            (
                "import unittest\n\n"
                "class ExampleTests(unittest.TestCase):\n"
                "    def test_example(self):\n"
                "        self.assertTrue(True)\n"
            ),
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            side_effect=lambda binary: (
                "/usr/bin/python3"
                if binary == "python3"
                else None
            ),
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        self.assertIn(
            ["python3", "-m", "unittest", "discover"],
            [entry["command"] for entry in result["detected"]],
        )

    def test_tests_directory_alone_does_not_invent_unittest(self):
        tests = self.workspace_one / "tests"
        tests.mkdir()

        (tests / "test_example.py").write_text(
            "def test_example():\n    assert True\n",
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/python3",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        commands = [
            entry["command"]
            for entry in result["detected"] + result["recommended"]
        ]

        self.assertNotIn(
            ["python3", "-m", "unittest", "discover"],
            commands,
        )

    def test_detects_phpunit_only_when_project_evidence_exists(self):
        (self.workspace_one / "composer.json").write_text(
            json.dumps({
                "require-dev": {
                    "phpunit/phpunit": "^11",
                },
            }),
            encoding="utf-8",
        )

        phpunit = self.workspace_one / "vendor" / "bin" / "phpunit"
        phpunit.parent.mkdir(parents=True)
        phpunit.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        phpunit.chmod(0o755)

        workspace = self.add_workspace()
        result = code_workspaces.detect_test_commands(
            workspace["workspace_id"]
        )

        self.assertIn(
            ["vendor/bin/phpunit"],
            [entry["command"] for entry in result["detected"]],
        )

    def test_html_tidy_unavailable_is_recommended_not_detected(self):
        (self.workspace_one / "index.html").write_text(
            "<!doctype html><title>Test</title>\n",
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value=None,
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        self.assertNotIn(
            ["tidy", "-errors", "-quiet", "index.html"],
            [entry["command"] for entry in result["detected"]],
        )
        self.assertIn(
            ["tidy", "-errors", "-quiet", "index.html"],
            [entry["command"] for entry in result["recommended"]],
        )
        self.assertTrue(
            any(
                warning.get("warning") == "TIDY_UNAVAILABLE"
                for warning in result["warnings"]
            )
        )

    def test_node_script_content_is_never_used_as_free_shell_command(self):
        dangerous = "vitest && touch SHOULD_NOT_EXIST"

        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": dangerous,
                },
            }),
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/npm",
        ):
            result = code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        commands = [
            entry["command"]
            for entry in result["detected"] + result["recommended"]
        ]

        self.assertIn(["npm", "run", "test"], commands)
        self.assertNotIn([dangerous], commands)

        for command in commands:
            self.assertNotIn("sh", command[:1])
            self.assertNotIn("bash", command[:1])

        self.assertFalse(
            (self.workspace_one / "SHOULD_NOT_EXIST").exists()
        )

    def test_detection_does_not_change_existing_test_commands(self):
        configured_command = [
            sys.executable,
            "-m",
            "unittest",
        ]

        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[configured_command],
            activate=True,
        )

        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": "vitest",
                },
            }),
            encoding="utf-8",
        )

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            return_value="/usr/bin/npm",
        ):
            code_workspaces.detect_test_commands(
                workspace["workspace_id"]
            )

        stored = code_workspaces._workspace(
            workspace["workspace_id"]
        )

        self.assertEqual(
            stored["test_commands"],
            [configured_command],
        )

    def test_detect_tests_api_returns_workspace_detection(self):
        (self.workspace_one / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": "vitest run",
                },
            }),
            encoding="utf-8",
        )
        (self.workspace_one / "package-lock.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

        workspace = self.add_workspace()

        with mock.patch.object(
            code_workspaces.shutil,
            "which",
            side_effect=lambda binary: f"/usr/bin/{binary}",
        ):
            result = agent_app.code_workspace_detect_tests(
                workspace["workspace_id"]
            )

        self.assertEqual(
            result["workspace_id"],
            workspace["workspace_id"],
        )
        self.assertIn(
            ["npm", "run", "test"],
            [
                entry["command"]
                for entry in result["detected"]
            ],
        )
        self.assertIn("recommended", result)
        self.assertIn("warnings", result)

    def test_detect_tests_api_rejects_unknown_workspace(self):
        with self.assertRaises(Exception) as context:
            agent_app.code_workspace_detect_tests(
                "does-not-exist"
            )

        self.assertIn(
            "WORKSPACE_NOT_FOUND",
            str(context.exception),
        )

    def test_workspace_detection_frontend_contract(self):
        chat_html = Path("frontend/chat.html").read_text(
            encoding="utf-8"
        )
        chat_js = Path("frontend/assets/chat.js").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'id="workspaceTestsDetect"',
            chat_html,
        )
        self.assertIn(
            'id="workspaceTestDetection"',
            chat_html,
        )
        self.assertIn(
            'id="workspaceTestsUseDetected"',
            chat_html,
        )

        self.assertIn(
            "'/detect-tests'",
            chat_js,
        )
        self.assertIn(
            "renderWorkspaceTestDetection(result)",
            chat_js,
        )
        self.assertIn(
            "JSON.stringify(commands, null, 2)",
            chat_js,
        )

        # Auto-detection may populate the editor, but it must not
        # persist test_commands automatically.
        detect_handler_start = chat_js.index(
            "const workspaceTestsDetect ="
        )
        save_handler_start = chat_js.index(
            "const workspaceTestsSave ="
        )

        detect_handler = chat_js[
            detect_handler_start:save_handler_start
        ]

        self.assertNotIn(
            "test_commands:",
            detect_handler,
        )

    def test_workspace_detection_i18n_exists_in_both_languages(self):
        required = {
            "workspace_tests_detect",
            "workspace_tests_use_detected",
            "workspace_tests_detect_none",
            "workspace_tests_detect_unavailable",
            "workspace_tests_detect_complete",
            "workspace_tests_detect_applied",
        }

        for filename in (
            "frontend/i18n/de.json",
            "frontend/i18n/en.json",
        ):
            with self.subTest(filename=filename):
                data = json.loads(
                    Path(filename).read_text(encoding="utf-8")
                )

                ui = data.get("ui", {})

                self.assertTrue(
                    required.issubset(ui),
                    required - set(ui),
                )

                for key in required:
                    self.assertIsInstance(ui[key], str)
                    self.assertTrue(ui[key].strip())

    def test_reads_existing_file(self):
        source = self.workspace_one / "app.php"
        source.write_text("<?php\necho 'ok';\n", encoding="utf-8")
        workspace = self.add_workspace()

        result = code_workspaces.read(workspace["workspace_id"], "app.php")

        self.assertEqual(result["path"], "app.php")
        self.assertIn("echo 'ok'", result["content"])

    def test_modifies_existing_file_through_patch(self):
        source = self.workspace_one / "README.md"
        source.write_text("old\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Update README",
            [{"path": "README.md", "proposed_content": "new\n"}],
        )

        self.assertEqual(patch["files"][0]["operation"], "MODIFY")
        self.assertEqual(source.read_text(encoding="utf-8"), "old\n")
        code_workspaces.apply(patch["patch_id"], approved=True)
        self.assertEqual(source.read_text(encoding="utf-8"), "new\n")

    def test_creates_diffs_and_reports_txt_as_no_checks(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create file",
            [{"path": "src/new.txt", "proposed_content": "new\n"}],
        )

        file_diff = patch["files"][0]
        self.assertEqual(file_diff["operation"], "CREATE")
        self.assertIn("--- /dev/null", file_diff["diff"])
        self.assertIn("+++ proposed/src/new.txt", file_diff["diff"])
        self.assertFalse((self.workspace_one / "src/new.txt").exists())
        test_result = code_workspaces.test(patch["patch_id"])
        self.assertFalse(test_result["passed"])
        self.assertEqual(test_result["test_status"], "no_checks")
        self.assertEqual(test_result["checks_run"], 0)
        self.assertEqual(test_result["results"][0]["status"], "skipped")

    def test_apply_requires_approval(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create file",
            [{"path": "new.txt", "proposed_content": "content\n"}],
        )

        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRED"):
            code_workspaces.apply(patch["patch_id"], approved=False)
        self.assertFalse((self.workspace_one / "new.txt").exists())

    def test_apply_approval_requires_diff_then_test(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create file",
            [{"path": "new.txt", "proposed_content": "content\n"}],
        )
        patch_id = patch["patch_id"]
        test_result = code_workspaces.test(patch_id)
        observations = [{
            "action": "code_test",
            "query": patch_id,
            "status": "completed",
            "result": test_result,
        }]

        with self.assertRaisesRegex(ValueError, "code_diff"):
            agent_app.create_agent_approval(
                goal="Create file",
                observations=observations,
                step=2,
                mode="coding",
                operation="code_apply",
                target=patch_id,
                reason="Missing diff",
            )

    def test_apply_creates_file_and_revert_removes_it_without_indexing(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create file",
            [{"path": "nested/new.txt", "proposed_content": "content\n"}],
        )

        code_workspaces.apply(patch["patch_id"], approved=True)
        target = self.workspace_one / "nested/new.txt"
        self.assertEqual(target.read_text(encoding="utf-8"), "content\n")

        with mock.patch.object(code_workspaces, "refresh") as refresh:
            code_workspaces.revert(patch["patch_id"])
            refresh.assert_not_called()
        self.assertFalse(target.exists())

    def test_create_conflicts_if_file_appears_before_apply(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create file",
            [{"path": "new.txt", "proposed_content": "proposal\n"}],
        )
        (self.workspace_one / "new.txt").write_text("other\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "CREATE_CONFLICT"):
            code_workspaces.apply(patch["patch_id"], approved=True)

    def test_modify_conflicts_if_file_changes_before_apply(self):
        target = self.workspace_one / "existing.txt"
        target.write_text("base\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Modify file",
            [{"path": "existing.txt", "proposed_content": "proposal\n"}],
        )
        target.write_text("changed elsewhere\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "PATCH_CONFLICT"):
            code_workspaces.apply(patch["patch_id"], approved=True)

    def test_delete_patch_diff_test_apply_verify_and_revert(self):
        target = self.workspace_one / "test.txt"
        target.write_text("Hallo Welt\n", encoding="utf-8")
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[
                sys.executable,
                "-c",
                "from pathlib import Path; raise SystemExit(Path('test.txt').exists())",
            ]],
            activate=True,
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Delete test.txt",
            [{"path": "test.txt", "operation": "delete"}],
        )
        patch_id = patch["patch_id"]
        file_diff = patch["files"][0]

        self.assertEqual(file_diff["operation"], "DELETE")
        self.assertIn("--- original/test.txt", file_diff["diff"])
        self.assertIn("+++ /dev/null", file_diff["diff"])
        self.assertIn("-Hallo Welt", file_diff["diff"])
        self.assertTrue(target.exists(), "PREPARE must not delete the real file")

        tests = code_workspaces.test(patch_id)
        self.assertTrue(tests["passed"])
        self.assertEqual(tests["results"][0]["simulated"], "absent")
        self.assertEqual(tests["results"][1]["status"], "passed")

        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRED"):
            code_workspaces.apply(patch_id, approved=False)
        self.assertTrue(target.exists())

        code_workspaces.apply(patch_id, approved=True)
        self.assertFalse(target.exists())

        verification = code_workspaces.verify(patch_id)
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["files"][0]["operation"], "DELETE")
        self.assertTrue(verification["files"][0]["ok"])

        agent_verification = agent_app.verify_agent_action({
            "operation": "code_apply",
            "target": patch_id,
        })
        self.assertTrue(agent_verification["verified"])
        self.assertTrue(
            next(
                check for check in agent_verification["checks"]
                if check["check"] == "workspace_files"
            )["ok"]
        )

        code_workspaces.revert(patch_id)
        self.assertEqual(target.read_text(encoding="utf-8"), "Hallo Welt\n")

    def test_delete_conflicts_if_file_changes_or_disappears(self):
        target = self.workspace_one / "delete.txt"
        target.write_text("base\n", encoding="utf-8")
        workspace = self.add_workspace()
        changed_patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Delete changed file",
            [{"path": "delete.txt", "operation": "DELETE"}],
        )
        target.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PATCH_CONFLICT"):
            code_workspaces.apply(changed_patch["patch_id"], approved=True)

        target.write_text("base\n", encoding="utf-8")
        missing_patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Delete missing file",
            [{"path": "delete.txt", "operation": "DELETE"}],
        )
        target.unlink()
        with self.assertRaisesRegex(ValueError, "PATCH_CONFLICT"):
            code_workspaces.apply(missing_patch["patch_id"], approved=True)

    def test_delete_blocks_traversal_and_symlink_escape(self):
        workspace = self.add_workspace()
        outside = self.base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_WORKSPACE"):
            code_workspaces.create_patch(
                workspace["workspace_id"],
                "Traversal delete",
                [{"path": "../outside.txt", "operation": "DELETE"}],
            )

        (self.workspace_one / "escape.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_WORKSPACE"):
            code_workspaces.create_patch(
                workspace["workspace_id"],
                "Symlink delete",
                [{"path": "escape.txt", "operation": "DELETE"}],
            )

    def test_blocks_path_traversal_and_symlink_escape(self):
        workspace = self.add_workspace()

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_WORKSPACE"):
            code_workspaces.read(workspace["workspace_id"], "../outside.txt")

        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (self.workspace_one / "escape.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_WORKSPACE"):
            code_workspaces.read(workspace["workspace_id"], "escape.txt")

    def test_workspace_switch_is_persisted_and_blocks_old_patch(self):
        first = self.add_workspace(self.workspace_one)
        patch = code_workspaces.create_patch(
            first["workspace_id"],
            "Create file",
            [{"path": "new.txt", "proposed_content": "content\n"}],
        )
        second = self.add_workspace(self.workspace_two)

        self.assertEqual(
            code_workspaces.active_workspace()["workspace_id"],
            second["workspace_id"],
        )
        with self.assertRaisesRegex(ValueError, "WORKSPACE_CHANGED"):
            code_workspaces.apply(patch["patch_id"], approved=True)

    def test_coding_tools_use_active_workspace_instead_of_first(self):
        (self.workspace_one / "first.txt").write_text("first", encoding="utf-8")
        (self.workspace_two / "second.txt").write_text("second", encoding="utf-8")
        self.add_workspace(self.workspace_one)
        second = self.add_workspace(self.workspace_two)

        files = agent_app.execute_read_only_agent_tool(
            "code_files",
            "List files",
        )
        self.assertEqual([item["path"] for item in files["files"]], ["second.txt"])

        read = agent_app.execute_read_only_agent_tool(
            "code_read",
            "Read file",
            query="second.txt",
        )
        self.assertEqual(read["content"], "second")

        with mock.patch.object(
            code_workspaces,
            "search",
            return_value={"workspace_id": second["workspace_id"], "files": []},
        ) as search:
            result = agent_app.tool_code_search(
                agent_app.ChatActionRequest(prompt="login")
            )
        self.assertEqual(result["workspace_id"], second["workspace_id"])
        search.assert_called_once_with(second["workspace_id"], "login")

    def test_active_workspace_routes_common_coding_requests(self):
        self.add_workspace()

        for prompt in (
            "Erstelle test.txt mit Hallo Welt.",
            "Erstelle in diesem Workspace eine Datei test.txt.",
            "Analysiere dieses Projekt.",
            "Suche den Fehler im Login.",
            "Ändere die Navigation.",
            "Erstelle hier eine README.",
            "Lege eine neue PHP-Datei an.",
            "Ändere index.php.",
            "Behebe den Fehler in login.php.",
            "Prüfe alle PHP-Dateien.",
            "Lösche test.txt.",
            "Entferne die Datei test.txt.",
            "Remove test.txt.",
            "Delete test.txt.",
            "Die Datei kann weg.",
        ):
            with self.subTest(prompt=prompt):
                with mock.patch.object(
                    agent_app,
                    "semantic_intent_classifier",
                    return_value={
                        "intent": "coding_agent",
                        "confidence": 0.99,
                        "requires_tools": True,
                        "reason": "Eindeutiger Workspace-Auftrag",
                    },
                ):
                    self.assertEqual(
                        agent_app.classify_chat_action(prompt),
                        "coding_agent",
                    )

        with mock.patch.object(
            agent_app,
            "semantic_intent_classifier",
            return_value={
                "intent": "coding_agent",
                "confidence": 0.99,
                "requires_tools": True,
                "reason": "Eindeutiger Workspace-Auftrag",
            },
        ):
            routed = agent_app.run_chat_action(
                agent_app.ChatActionRequest(
                    prompt="Erstelle test.txt mit Hallo Welt",
                )
            )
        self.assertEqual(routed["tool"], "coding_agent")
        self.assertEqual(routed["data"]["mode"], "coding")

    def test_workspace_file_review_routes_to_coding_agent(self):
        self.add_workspace()

        prompts = (
            'Schau dir das Spiel blackjack an "blackjack.html" kann man das besser machen?',
            "Schau dir index.html an.",
            "Kann man login.php besser machen?",
            "Prüfe diese CSS-Datei style.css.",
            "Bewerte frontend.js.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                details = agent_app.classify_chat_action_details(
                    prompt,
                    classifier=lambda *_args: {
                        "intent": "normal_chat",
                        "confidence": 0.4,
                        "requires_tools": False,
                        "reason": "Unsicher",
                    },
                )
                self.assertEqual(details["intent"], "coding_agent")
                self.assertEqual(details["method"], "deterministic")

        self.assertFalse(
            agent_app._looks_like_coding_action(
                "Wie kann man ein Blackjack-Spiel in HTML besser machen?"
            )
        )

    def test_coding_planner_runs_create_prepare_diff_test_then_approval(self):
        code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[sys.executable, "-c", "raise SystemExit(0)"]],
            activate=True,
        )
        seen_system_prompts = []

        def planner(messages, **kwargs):
            system_prompt = messages[0]["content"]
            seen_system_prompts.append(system_prompt)
            raw_observations = messages[1]["content"].split(
                "BISHERIGE OBSERVATIONS:\n",
                1,
            )[1]
            observations = json.loads(raw_observations)

            if not observations:
                return json.dumps({
                    "action": "code_patch",
                    "reason": "Neue Datei sicher vorbereiten",
                    "plan": ["Zieldatei anlegen", "Diff und Tests prüfen"],
                    "instruction": "test.txt erstellen",
                    "files": [{
                        "path": "test.txt",
                        "proposed_content": "Hallo Welt\n",
                    }],
                })

            patch_id = observations[0]["result"]["patch_id"]
            last_action = observations[-1]["action"]
            if last_action == "code_patch":
                return json.dumps({
                    "action": "code_diff",
                    "reason": "CREATE-Diff prüfen",
                    "query": patch_id,
                })
            if last_action == "code_diff":
                return json.dumps({
                    "action": "code_test",
                    "reason": "Patch testen",
                    "query": patch_id,
                })
            return json.dumps({
                "action": "request_approval",
                "operation": "code_apply",
                "target": patch_id,
                "reason": "Patch ist geprüft",
            })

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner):
            result = agent_app.run_agent_v2(
                "Erstelle test.txt mit Hallo Welt",
                mode="coding",
            )

        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(
            [step["action"] for step in result["steps"]],
            ["code_patch", "code_diff", "code_test"],
        )
        self.assertNotIn("code_read", [step["action"] for step in result["steps"]])
        self.assertEqual(
            result["steps"][0]["plan"],
            ["Zieldatei anlegen", "Diff und Tests prüfen"],
        )
        self.assertFalse((self.workspace_one / "test.txt").exists())
        self.assertEqual(result["pending_action"]["operation"], "code_apply")
        self.assertIn("PREPARE-Operationen wie code_patch", seen_system_prompts[0])
        self.assertIn("code_patch verändert den Workspace NICHT", seen_system_prompts[0])

    def test_followup_delete_resolves_file_from_conversation_context(self):
        target = self.workspace_one / "test.txt"
        target.write_text("Hallo Welt\n", encoding="utf-8")
        code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[sys.executable, "-c", "raise SystemExit(0)"]],
            activate=True,
        )
        conversation_context = [{
            "role": "user",
            "content": "Erstelle test.txt mit dem Inhalt Hallo Welt",
        }, {
            "role": "assistant",
            "content": "Änderung erfolgreich angewendet und verifiziert.",
        }]
        saw_context = False

        def planner(messages, **kwargs):
            nonlocal saw_context
            user_prompt = messages[1]["content"]
            saw_context = saw_context or "Erstelle test.txt" in user_prompt
            observations = json.loads(
                user_prompt.split("BISHERIGE OBSERVATIONS:\n", 1)[1]
            )
            if not observations:
                return json.dumps({
                    "action": "code_read",
                    "reason": "Eindeutig referenzierte Datei vor DELETE lesen",
                    "query": "test.txt",
                })
            patch_id = next(
                (
                    step["result"]["patch_id"]
                    for step in observations
                    if step["action"] == "code_patch"
                ),
                None,
            )
            last_action = observations[-1]["action"]
            if last_action == "code_read":
                return json.dumps({
                    "action": "code_patch",
                    "reason": "Referenzierte Datei sicher löschen",
                    "instruction": "test.txt löschen",
                    "files": [{
                        "path": "test.txt",
                        "operation": "DELETE",
                        "proposed_content": None,
                    }],
                })
            if last_action == "code_patch":
                patch_id = observations[-1]["result"]["patch_id"]
                return json.dumps({"action": "code_diff", "query": patch_id})
            if last_action == "code_diff":
                return json.dumps({"action": "code_test", "query": patch_id})
            return json.dumps({
                "action": "request_approval",
                "operation": "code_apply",
                "target": patch_id,
                "reason": "DELETE wurde geprüft",
            })

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner):
            result = agent_app.run_agent_v2(
                "und jetzt lösche die datei bitte wieder danke",
                mode="coding",
                conversation_context=conversation_context,
            )

        self.assertTrue(saw_context)
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(
            [step["action"] for step in result["steps"]],
            ["code_read", "code_patch", "code_diff", "code_test"],
        )
        patch_entry = code_workspaces._patch(
            result["pending_action"]["target"]
        )["files"][0]
        self.assertEqual(patch_entry["path"], "test.txt")
        self.assertEqual(patch_entry["operation"], "DELETE")
        self.assertTrue(target.exists(), "DELETE still requires approval")

    def test_greenfield_multi_file_create_diff_apply_verify_and_revert(self):
        workspace = self.add_workspace()
        changes = [
            {"path": "index.html", "operation": "CREATE", "proposed_content": "<h1>nobby</h1>\n"},
            {"path": "assets/css/style.css", "operation": "CREATE", "proposed_content": "body { color: #fff; }\n"},
            {"path": "assets/js/app.js", "operation": "CREATE", "proposed_content": "console.log('ready');\n"},
        ]

        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create responsive site",
            changes,
        )

        self.assertEqual(patch["change_set_id"], patch["patch_id"])
        self.assertEqual(patch["summary"]["files"], 3)
        self.assertEqual(patch["summary"]["create"], 3)
        self.assertEqual(patch["summary"]["modify"], 0)
        self.assertGreater(patch["summary"]["added_lines"], 0)
        tests = code_workspaces.test(patch["patch_id"])
        self.assertTrue(tests["passed"])
        self.assertEqual(tests["test_status"], "passed")
        self.assertEqual(tests["checks_run"], 1)
        self.assertEqual(
            [entry["status"] for entry in tests["results"]],
            ["skipped", "skipped", "passed"],
        )
        self.assertTrue(tests["test_workspace_removed"])

        result = code_workspaces.apply(patch["patch_id"], approved=True)
        self.assertEqual(result["summary"]["files"], 3)
        self.assertTrue(code_workspaces.verify(patch["patch_id"])["verified"])
        for change in changes:
            self.assertTrue((self.workspace_one / change["path"]).is_file())

        code_workspaces.revert(patch["patch_id"])
        for change in changes:
            self.assertFalse((self.workspace_one / change["path"]).exists())
        self.assertFalse((self.workspace_one / "assets").exists())

    def test_existing_project_multi_file_modify(self):
        first = self.workspace_one / "index.php"
        second = self.workspace_one / "style.css"
        first.write_text("<?php echo 'light';\n", encoding="utf-8")
        second.write_text("body { color: black; }\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Add dark mode",
            [
                {"path": "index.php", "operation": "MODIFY", "proposed_content": "<?php echo 'dark';\n"},
                {"path": "style.css", "operation": "MODIFY", "proposed_content": "body { color: white; }\n"},
            ],
        )

        self.assertEqual(patch["summary"]["modify"], 2)
        code_workspaces.apply(patch["patch_id"], approved=True)
        verification = code_workspaces.verify(patch["patch_id"])
        self.assertTrue(verification["verified"])
        self.assertTrue(all(item["ok"] for item in verification["files"]))

    def test_mixed_change_set_is_atomic_and_fully_revertible(self):
        modified = self.workspace_one / "index.html"
        deleted = self.workspace_one / "legacy.css"
        modified.write_text("old heading\n", encoding="utf-8")
        deleted.write_text("legacy\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Mixed project update",
            [
                {"path": "index.html", "operation": "MODIFY", "proposed_content": "new heading\n"},
                {"path": "app.js", "operation": "CREATE", "proposed_content": "console.log('new');\n"},
                {"path": "legacy.css", "operation": "DELETE"},
            ],
        )

        self.assertEqual(
            {key: patch["summary"][key] for key in ("create", "modify", "delete")},
            {"create": 1, "modify": 1, "delete": 1},
        )
        code_workspaces.apply(patch["patch_id"], approved=True)
        verification = code_workspaces.verify(patch["patch_id"])
        self.assertTrue(verification["verified"])
        self.assertEqual({item["operation"] for item in verification["files"]}, {"CREATE", "MODIFY", "DELETE"})

        code_workspaces.revert(patch["patch_id"])
        self.assertEqual(modified.read_text(encoding="utf-8"), "old heading\n")
        self.assertEqual(deleted.read_text(encoding="utf-8"), "legacy\n")
        self.assertFalse((self.workspace_one / "app.js").exists())

    def test_one_conflict_prevents_every_file_from_being_applied(self):
        first = self.workspace_one / "first.txt"
        second = self.workspace_one / "second.txt"
        first.write_text("first old\n", encoding="utf-8")
        second.write_text("second old\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Modify both",
            [
                {"path": "first.txt", "operation": "MODIFY", "proposed_content": "first new\n"},
                {"path": "second.txt", "operation": "MODIFY", "proposed_content": "second new\n"},
            ],
        )
        second.write_text("external change\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "PATCH_CONFLICT"):
            code_workspaces.apply(patch["patch_id"], approved=True)

        self.assertEqual(first.read_text(encoding="utf-8"), "first old\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "external change\n")

    def test_apply_failure_rolls_back_entire_change_set_and_audits(self):
        existing = self.workspace_one / "existing.txt"
        existing.write_text("before\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Rollback on write failure",
            [
                {"path": "nested/first.txt", "operation": "CREATE", "proposed_content": "first\n"},
                {"path": "nested/second.txt", "operation": "CREATE", "proposed_content": "second\n"},
                {"path": "existing.txt", "operation": "MODIFY", "proposed_content": "after\n"},
            ],
        )
        original_atomic = code_workspaces._atomic

        def fail_second(target, content):
            if target.name == "second.txt":
                raise OSError("simulated write failure")
            return original_atomic(target, content)

        with mock.patch.object(code_workspaces, "_atomic", side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, "PATCH_APPLY_FAILED"):
                code_workspaces.apply(patch["patch_id"], approved=True)

        self.assertEqual(existing.read_text(encoding="utf-8"), "before\n")
        self.assertFalse((self.workspace_one / "nested").exists())
        stored = code_workspaces._patch(patch["patch_id"])
        self.assertEqual(stored["status"], "failed")
        self.assertTrue(stored["rollback"]["completed"])
        audit = code_workspaces.AUDIT.read_text(encoding="utf-8")
        self.assertIn('"status": "apply_failed"', audit)
        self.assertIn('"completed": true', audit)

    def test_revert_conflict_blocks_entire_revert(self):
        original = self.workspace_one / "original.txt"
        original.write_text("before\n", encoding="utf-8")
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Two changes",
            [
                {"path": "original.txt", "operation": "MODIFY", "proposed_content": "after\n"},
                {"path": "created.txt", "operation": "CREATE", "proposed_content": "created\n"},
            ],
        )
        code_workspaces.apply(patch["patch_id"], approved=True)
        original.write_text("manual\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "REVERT_CONFLICT"):
            code_workspaces.revert(patch["patch_id"])

        self.assertEqual(original.read_text(encoding="utf-8"), "manual\n")
        self.assertEqual((self.workspace_one / "created.txt").read_text(encoding="utf-8"), "created\n")

    def test_test_workspace_mirrors_project_without_mutating_real_workspace(self):
        existing = self.workspace_one / "existing.txt"
        existing.write_text("real\n", encoding="utf-8")
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[
                sys.executable,
                "-c",
                "from pathlib import Path; p=Path('existing.txt'); p.write_text('test-only'); raise SystemExit(not Path('new.txt').exists())",
            ]],
            activate=True,
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create in mirrored project",
            [{"path": "new.txt", "operation": "CREATE", "proposed_content": "new\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertTrue(result["passed"])
        self.assertEqual(result["test_status"], "passed")
        self.assertEqual(result["checks_run"], 1)
        self.assertEqual(
            [entry["status"] for entry in result["results"]],
            ["skipped", "passed"],
        )
        self.assertTrue(result["test_workspace_removed"])
        self.assertEqual(existing.read_text(encoding="utf-8"), "real\n")
        self.assertFalse((self.workspace_one / "new.txt").exists())

    def test_html_without_commands_reports_no_checks(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create HTML",
            [{"path": "index.html", "operation": "CREATE", "proposed_content": "<h1>nobby</h1>\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["test_status"], "no_checks")
        self.assertEqual(result["checks_run"], 0)
        self.assertEqual(result["results"][0]["status"], "skipped")

    def test_javascript_syntax_check_counts_as_passed(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create JavaScript",
            [{"path": "app.js", "operation": "CREATE", "proposed_content": "const ready = true;\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertTrue(result["passed"])
        self.assertEqual(result["test_status"], "passed")
        self.assertEqual(result["checks_run"], 1)
        self.assertEqual(result["results"][0]["status"], "passed")

    def test_python_syntax_check_counts_as_passed(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create Python",
            [{"path": "app.py", "operation": "CREATE", "proposed_content": "ready = True\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertTrue(result["passed"])
        self.assertEqual(result["test_status"], "passed")
        self.assertEqual(result["checks_run"], 1)
        self.assertEqual(result["results"][0]["status"], "passed")

    def test_failed_test_command_reports_failed(self):
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[sys.executable, "-c", "raise SystemExit(1)"]],
            activate=True,
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create text",
            [{"path": "notes.txt", "operation": "CREATE", "proposed_content": "notes\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["test_status"], "failed")
        self.assertEqual(result["checks_run"], 1)
        self.assertEqual(
            [entry["status"] for entry in result["results"]],
            ["skipped", "failed"],
        )

    def test_failed_result_overrides_passed_and_skipped_results(self):
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[
                [sys.executable, "-c", "raise SystemExit(0)"],
                [sys.executable, "-c", "raise SystemExit(1)"],
            ],
            activate=True,
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create text",
            [{"path": "notes.txt", "operation": "CREATE", "proposed_content": "notes\n"}],
        )

        result = code_workspaces.test(patch["patch_id"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["test_status"], "failed")
        self.assertEqual(result["checks_run"], 2)
        self.assertEqual(
            [entry["status"] for entry in result["results"]],
            ["skipped", "passed", "failed"],
        )

    def test_unavailable_required_syntax_checker_does_not_report_passed(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create JavaScript",
            [{"path": "app.js", "operation": "CREATE", "proposed_content": "const ok = true;\n"}],
        )
        with mock.patch.object(
            code_workspaces.subprocess,
            "run",
            side_effect=FileNotFoundError("node unavailable"),
        ):
            result = code_workspaces.test(patch["patch_id"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["test_status"], "no_checks")
        self.assertEqual(result["checks_run"], 0)
        self.assertEqual(result["results"][0]["status"], "unavailable")

    def test_binary_patch_content_and_suffix_are_blocked(self):
        workspace = self.add_workspace()
        with self.assertRaisesRegex(ValueError, "BINARY_FILE_BLOCKED"):
            code_workspaces.create_patch(
                workspace["workspace_id"],
                "No binary",
                [{"path": "image.png", "operation": "CREATE", "proposed_content": "fake"}],
            )
        with self.assertRaisesRegex(ValueError, "BINARY_FILE_BLOCKED"):
            code_workspaces.create_patch(
                workspace["workspace_id"],
                "No null bytes",
                [{"path": "data.txt", "operation": "CREATE", "proposed_content": "a\x00b"}],
            )

    def test_approval_exposes_one_multi_file_summary(self):
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            test_commands=[[sys.executable, "-c", "raise SystemExit(0)"]],
            activate=True,
        )
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create two files",
            [
                {"path": "one.txt", "operation": "CREATE", "proposed_content": "one\n"},
                {"path": "two.txt", "operation": "CREATE", "proposed_content": "two\n"},
            ],
        )
        patch_id = patch["patch_id"]
        tests = code_workspaces.test(patch_id)
        approval = agent_app.create_agent_approval(
            goal="Create two files",
            observations=[
                {"action": "code_diff", "query": patch_id, "status": "completed", "result": patch},
                {"action": "code_test", "query": patch_id, "status": "completed", "result": tests},
            ],
            step=3,
            mode="coding",
            operation="code_apply",
            target=patch_id,
            reason="Ready",
        )

        self.assertEqual(approval["summary"]["files"], 2)
        self.assertEqual(approval["summary"]["create"], 2)
        self.assertTrue(approval["tests"]["passed"])
        self.assertEqual(approval["tests"]["test_status"], "passed")
        self.assertEqual(approval["tests"]["checks_run"], 1)
        self.assertEqual(len(approval["files"]), 2)

    def test_approval_rejects_code_test_without_executed_checks(self):
        workspace = self.add_workspace()
        patch = code_workspaces.create_patch(
            workspace["workspace_id"],
            "Create text",
            [{"path": "new.txt", "operation": "CREATE", "proposed_content": "content\n"}],
        )
        patch_id = patch["patch_id"]
        tests = code_workspaces.test(patch_id)
        tests["passed"] = True

        with self.assertRaisesRegex(ValueError, "erfolgreichen code_test"):
            agent_app.create_agent_approval(
                goal="Create text",
                observations=[
                    {"action": "code_diff", "query": patch_id, "status": "completed", "result": patch},
                    {"action": "code_test", "query": patch_id, "status": "completed", "result": tests},
                ],
                step=3,
                mode="coding",
                operation="code_apply",
                target=patch_id,
                reason="Ready",
            )

    def test_project_and_followup_routing_and_programming_question(self):
        self.add_workspace()

        def classifier(prompt, *_args):
            normal_chat = prompt.startswith("Wie erstelle ich")
            return {
                "intent": "normal_chat" if normal_chat else "coding_agent",
                "confidence": 0.99,
                "requires_tools": not normal_chat,
                "reason": "Semantische Testklassifikation",
            }

        for prompt in (
            "Erstelle eine komplette Webseite.",
            "Baue mir eine kleine Web-App.",
            "Implementiere eine Benutzerverwaltung.",
            "Füge Dark Mode hinzu.",
            "Erstelle eine REST-API.",
            "Überarbeite das responsive Design.",
        ):
            with self.subTest(prompt=prompt):
                with mock.patch.object(
                    agent_app,
                    "semantic_intent_classifier",
                    side_effect=classifier,
                ):
                    self.assertEqual(agent_app.classify_chat_action(prompt), "coding_agent")

        with mock.patch.object(
            agent_app,
            "semantic_intent_classifier",
            side_effect=classifier,
        ):
            followup = agent_app.classify_chat_action(
                "Mach den Header kleiner.",
                conversation_context=[{
                    "role": "assistant",
                    "content": "Änderung erfolgreich angewendet und verifiziert.",
                }],
            )
        self.assertEqual(followup, "coding_agent")
        with mock.patch.object(
            agent_app,
            "semantic_intent_classifier",
            side_effect=classifier,
        ):
            self.assertEqual(
                agent_app.classify_chat_action("Wie erstelle ich eine REST-API?"),
                "normal_chat",
            )

    def test_semantic_router_distinguishes_local_actions_from_explanations(self):
        expected = {
            "Welche App zieht gerade am meisten Leistung?": "diagnostic_agent",
            "Warum ist mein Mac gerade so langsam?": "diagnostic_agent",
            "Schau mal was meinen RAM auffrisst.": "diagnostic_agent",
            "Wie kann ich unter macOS RAM-Verbrauch anzeigen?": "normal_chat",
            "Stell mein Projekt auf PDO um.": "coding_agent",
            "Wie funktioniert PDO?": "normal_chat",
            "Recherchiere aktuelle lokale LLMs.": "research_agent",
            "Was ist ein LLM?": "normal_chat",
        }

        def classifier(prompt, file_context, conversation_context):
            return {
                "intent": expected[prompt],
                "confidence": 0.96,
                "reason": "Semantische Testklassifikation",
            }

        for prompt, intent in expected.items():
            with self.subTest(prompt=prompt):
                details = agent_app.classify_chat_action_details(
                    prompt,
                    classifier=classifier,
                )
                self.assertEqual(details["intent"], intent)
                self.assertIn(details["method"], {"deterministic", "semantic_llm"})

    def test_semantic_router_keeps_diagnostic_followup(self):
        details = agent_app.classify_chat_action_details(
            "und was davon ist Docker?",
            conversation_context=[{
                "role": "assistant",
                "content": "Der diagnostic_agent hat CPU und RAM untersucht.",
            }],
            classifier=lambda *_args: {
                "intent": "normal_chat",
                "confidence": 0.35,
                "reason": "Unsicherer Follow-up",
            },
        )

        self.assertEqual(details["intent"], "diagnostic_agent")
        self.assertEqual(details["method"], "safe_fallback")

    def test_low_classifier_confidence_uses_safe_normal_chat_fallback(self):
        details = agent_app.classify_chat_action_details(
            "Erzähl mir etwas Interessantes.",
            classifier=lambda *_args: {
                "intent": "diagnostic_agent",
                "confidence": 0.4,
                "reason": "Nicht eindeutig",
            },
        )

        self.assertEqual(details["intent"], "normal_chat")
        self.assertEqual(details["classifier_intent"], "diagnostic_agent")
        self.assertEqual(details["method"], "safe_fallback")

    def test_semantic_router_precedes_ambiguous_substring_agent_match(self):
        calls = []

        def classifier(prompt, file_context, conversation_context):
            calls.append(prompt)
            return {
                "intent": "normal_chat",
                "confidence": 0.99,
                "requires_tools": False,
                "reason": "Allgemeine persönliche Frage",
            }

        details = agent_app.classify_chat_action_details(
            "Therapie und Reiterstellung",
            classifier=classifier,
        )

        self.assertEqual(calls, ["Therapie und Reiterstellung"])
        self.assertEqual(details["intent"], "normal_chat")
        self.assertEqual(details["method"], "semantic_llm")
        self.assertFalse(details["requires_tools"])

    def test_semantic_router_requires_explicit_tool_need_for_agent(self):
        details = agent_app.classify_chat_action_details(
            "Allgemeine Frage mit dem Wort Diagnose",
            classifier=lambda *_args: {
                "intent": "diagnostic_agent",
                "confidence": 0.98,
                "requires_tools": False,
                "reason": "Kein Zugriff auf den lokalen Mac nötig",
            },
        )

        self.assertEqual(details["intent"], "normal_chat")
        self.assertEqual(details["method"], "semantic_safety_fallback")

    def test_direct_action_still_bypasses_semantic_classifier(self):
        classifier = mock.Mock(side_effect=AssertionError("must not run"))
        details = agent_app.classify_chat_action_details(
            "Thinking an",
            classifier=classifier,
        )

        self.assertEqual(details["intent"], "thinking_on")
        self.assertEqual(details["method"], "deterministic")
        classifier.assert_not_called()

    def test_current_information_requests_route_to_web_search(self):
        cases = {
            "Fasse mir die wichtigsten News von heute zusammen": "web_search",
            "Was gibt es heute Neues bei Apple?": "web_search",
            "Wie ist der aktuelle Stand bei Python 3.14?": "web_search",
            "Was sind die aktuellen Nachrichten aus Deutschland?": "web_search",
            "Heute hatte ich einen schlechten Tag.": None,
            "Ich habe heute Python programmiert.": None,
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    agent_app._deterministic_chat_action(prompt),
                    expected,
                )

    def test_classifier_prompt_describes_real_local_capabilities(self):
        captured = {}

        def classify_llm(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return json.dumps({
                "intent": "diagnostic_agent",
                "confidence": 0.97,
                "reason": "Lokale Prozessprüfung",
            })

        with mock.patch.object(agent_app, "router_llm", side_effect=classify_llm):
            result = agent_app.semantic_intent_classifier(
                "Kannst du prüfen, welche App am meisten verbraucht?",
            )

        self.assertEqual(result["intent"], "diagnostic_agent")
        self.assertIn("Lokalen Mac, Prozesse, CPU, RAM", captured["system"])
        self.assertIn("kein generischer Cloud-Chatbot", captured["system"])
        self.assertIn("active_coding_workspace", captured["user"])

    def test_agent_api_returns_controlled_error_for_invalid_model_json(self):
        request = agent_app.AgentRunRequest(
            goal="Untersuche den lokalen Systemstatus",
            mode="diagnostic",
            trace_id="trace-agent-api-001",
        )
        with mock.patch.object(
            agent_app,
            "run_agent_v2",
            side_effect=ValueError("Agent hat kein gültiges JSON geliefert"),
        ):
            result = agent_app.api_agent_run(request)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "invalid_agent_response")
        self.assertIn("nichts ausgeführt", result["answer"])
        self.assertEqual(result["trace_id"], "trace-agent-api-001")
        self.assertIn("model_metrics", result)

    def test_run_chat_action_routes_before_normal_chat_answer(self):
        with mock.patch.object(
            agent_app,
            "semantic_intent_classifier",
            return_value={
                "intent": "diagnostic_agent",
                "confidence": 0.98,
                "reason": "Lokale Systemdiagnose angefordert",
            },
        ):
            result = agent_app.run_chat_action(agent_app.ChatActionRequest(
                prompt="Kannst du mal prüfen, welche App den höchsten Systemverbrauch hat?",
            ))

        self.assertEqual(result["tool"], "diagnostic_agent")
        self.assertEqual(result["data"]["mode"], "diagnostic")
        self.assertIn(
            result["data"]["routing"]["method"],
            {
                "semantic_llm",
                "semantic_manager",
            },
        )

    def test_process_usage_returns_separate_cpu_and_memory_rankings(self):
        process_output = "\n".join([
            "101 72.5 204800 01:02 /Applications/Video.app/Contents/MacOS/Video",
            "202 10.0 1048576 02:03 /Applications/Memory.app/Contents/MacOS/Memory",
            "303 1.5 1024 00:10 /usr/bin/helper",
        ])
        completed = subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout=process_output,
            stderr="",
        )

        with mock.patch.object(agent_app.subprocess, "run", return_value=completed) as run:
            result = agent_app.tool_process_usage(limit=2)

        self.assertEqual(result["cpu_top"][0]["name"], "Video")
        self.assertEqual(result["cpu_top"][0]["cpu_percent"], 72.5)
        self.assertEqual(result["memory_top"][0]["name"], "Memory")
        self.assertEqual(result["memory_top"][0]["rss_mb"], 1024.0)
        self.assertIn("getrennte Messgrößen", result["metric_note"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_diagnostic_agent_can_execute_structured_process_usage(self):
        process_result = {
            "cpu_top": [{"name": "Video", "pid": 101, "cpu_percent": 72.5, "rss_mb": 200.0}],
            "memory_top": [{"name": "Memory", "pid": 202, "cpu_percent": 10.0, "rss_mb": 1024.0}],
            "metric_note": "CPU und RAM sind getrennt.",
        }

        def planner(messages, **kwargs):
            observations = json.loads(
                messages[1]["content"].split("BISHERIGE OBSERVATIONS:\n", 1)[1]
            )
            if not observations:
                return json.dumps({
                    "action": "process_usage",
                    "reason": "CPU und RAM getrennt erfassen",
                })
            return json.dumps({
                "action": "final",
                "answer": "Video führt bei CPU, Memory beim RAM.",
            })

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner), mock.patch.object(
            agent_app,
            "tool_process_usage",
            return_value=process_result,
        ):
            result = agent_app.run_agent_v2(
                "Welche App hat aktuell den höchsten Systemverbrauch?",
                mode="diagnostic",
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps"][0]["action"], "process_usage")
        self.assertEqual(result["steps"][0]["result"], process_result)
        self.assertIn("Video", result["answer"])

    def test_coding_evidence_contract_read_does_not_imply_tests(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script>console.log('blackjack')</script>",
            },
        }]

        contract = agent_app.coding_evidence_contract(observations)
        joined = " ".join(contract)

        self.assertIn("source code was inspected", joined)
        self.assertIn("does NOT prove runtime behavior", joined)
        self.assertIn("No completed code_test exists", joined)
        self.assertIn("No completed verify_change", joined)

    def test_coding_evidence_contract_distinguishes_test_and_verification(self):
        observations = [
            {
                "action": "code_test",
                "status": "completed",
                "result": {
                    "results": [{
                        "command": "python3 -m unittest",
                        "success": True,
                        "output": "OK",
                    }],
                },
            },
            {
                "action": "verify_change",
                "status": "completed",
                "result": {
                    "verified": True,
                },
            },
        ]

        contract = agent_app.coding_evidence_contract(observations)
        joined = " ".join(contract)

        self.assertIn("test-result claims", joined)
        self.assertIn("verified=true proves", joined)
        self.assertNotIn("No completed code_test exists", joined)
        self.assertNotIn("No completed verify_change", joined)

    def test_final_answer_marks_read_only_code_analysis_as_unverified(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script>function hit() {}</script>",
            },
        }]

        captured = {}

        def final_llm(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return "Statische Analyse."

        with mock.patch.object(agent_app, "agent_llm", side_effect=final_llm):
            answer = agent_app.agent_v2_final_answer(
                "Analysiere blackjack.html",
                observations,
            )

        self.assertEqual(answer, "Statische Analyse.")
        self.assertIn(
            "Es wurde KEIN code_test erfolgreich ausgeführt",
            captured["system"],
        )
        self.assertIn(
            "Behaupte NICHT als Tatsache, dass der Code funktioniert",
            captured["system"],
        )
        self.assertIn(
            "statische Analyse",
            captured["system"],
        )
        self.assertIn(
            "No completed code_test exists",
            captured["user"],
        )

    def test_final_answer_allows_test_claims_when_code_test_exists(self):
        observations = [{
            "action": "code_test",
            "status": "completed",
            "result": {
                "passed": True,
                "results": [{
                    "command": "node --check blackjack.js",
                    "success": True,
                    "output": "",
                }],
            },
        }]

        captured = {}

        def final_llm(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return "Test ausgeführt."

        with mock.patch.object(agent_app, "agent_llm", side_effect=final_llm):
            agent_app.agent_v2_final_answer(
                "Prüfe blackjack",
                observations,
            )

        self.assertNotIn(
            "Es wurde KEIN code_test erfolgreich ausgeführt",
            captured["system"],
        )

    def test_coding_final_answer_detects_unsupported_runtime_claims(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script></script>",
            },
        }]

        reasons = agent_app.coding_final_answer_requires_repair(
            "Der Code ist strukturell funktionsfähig und korrekt implementiert.",
            observations,
        )

        self.assertTrue(reasons)

    def test_coding_final_answer_allows_explicit_negative_disclaimer(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script></script>",
            },
        }]

        answer = (
            "Das Laufzeitverhalten wurde nicht getestet. "
            "Es kann nicht garantiert werden, dass der Code fehlerfrei "
            "ausgeführt wird oder korrekt funktioniert."
        )

        reasons = agent_app.coding_final_answer_requires_repair(
            answer,
            observations,
        )

        self.assertEqual(reasons, [])

    def test_coding_final_answer_allows_static_language_without_tests(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script></script>",
            },
        }]

        reasons = agent_app.coding_final_answer_requires_repair(
            (
                "Im statisch gelesenen Code ist kein offensichtlicher Widerspruch "
                "erkennbar. Das Laufzeitverhalten wurde nicht getestet."
            ),
            observations,
        )

        self.assertEqual(reasons, [])

    def test_final_answer_repairs_unsupported_runtime_claim_once(self):
        observations = [{
            "action": "code_read",
            "status": "completed",
            "result": {
                "path": "blackjack.html",
                "content": "<script></script>",
            },
        }]

        responses = iter([
            "Der Code ist strukturell funktionsfähig und korrekt implementiert.",
            (
                "Die statische Analyse zeigt eine plausible Struktur. "
                "Das Laufzeitverhalten wurde nicht getestet."
            ),
        ])

        with mock.patch.object(
            agent_app,
            "agent_llm",
            side_effect=lambda *args, **kwargs: next(responses),
        ) as llm:
            answer = agent_app.agent_v2_final_answer(
                "Analysiere blackjack.html",
                observations,
            )

        self.assertEqual(llm.call_count, 2)
        self.assertIn("statische Analyse", answer)
        self.assertIn("nicht getestet", answer)

    def test_unclear_delete_reference_asks_instead_of_planning(self):
        self.add_workspace()
        with mock.patch.object(agent_app, "agent_llm") as llm:
            result = agent_app.run_agent_v2(
                "Lösche das wieder.",
                mode="coding",
                conversation_context=[],
            )
        llm.assert_not_called()
        self.assertEqual(result["status"], "completed")
        self.assertIn("Welche konkrete", result["answer"])
        self.assertEqual(result["steps"], [])

    def test_coding_agent_has_24_step_budget_and_reports_max_steps(self):
        self.add_workspace()
        calls = 0

        def planner(messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls <= 24:
                return json.dumps({"action": "not_allowed"})
            return "Budget erreicht; keine Änderung vorbereitet."

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner):
            result = agent_app.run_agent_v2("Überarbeite das Projekt", mode="coding")

        self.assertEqual(result["status"], "max_steps")
        self.assertEqual(len(result["steps"]), 24)
        self.assertEqual(calls, 25)

    def test_agent_progress_reports_real_planner_and_tool_steps(self):
        self.add_workspace()
        progress_events = []

        def planner(messages, **kwargs):
            content = messages[1]["content"]
            if "BISHERIGE OBSERVATIONS:\n" not in content:
                return "Analyse fertig."
            observations = json.loads(
                content.split("BISHERIGE OBSERVATIONS:\n", 1)[1]
            )
            if not observations:
                return json.dumps({
                    "action": "code_files",
                    "reason": "Projektstruktur analysieren",
                    "query": "",
                })
            return json.dumps({"action": "final", "answer": "Analyse fertig."})

        def progress(status, steps, current_step=None, pending_action=None):
            progress_events.append({
                "status": status,
                "actions": [step.get("action") for step in steps],
                "current": (current_step or {}).get("action"),
            })

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner):
            result = agent_app.run_agent_v2(
                "Analysiere das Projekt",
                mode="coding",
                progress_callback=progress,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(any(event["current"] == "agent_plan" for event in progress_events))
        self.assertTrue(any(event["current"] == "code_files" for event in progress_events))
        self.assertTrue(any("code_files" in event["actions"] for event in progress_events))
        self.assertEqual(progress_events[-1]["status"], "completed")

    def test_diagnostic_agent_rejects_prepare_tools(self):
        self.add_workspace()

        def planner(messages, **kwargs):
            observations = json.loads(
                messages[1]["content"].split("BISHERIGE OBSERVATIONS:\n", 1)[1]
            )
            if not observations:
                return json.dumps({
                    "action": "code_patch",
                    "instruction": "not allowed",
                    "files": [{
                        "path": "blocked.txt",
                        "operation": "DELETE",
                        "proposed_content": None,
                    }],
                })
            return json.dumps({"action": "final", "answer": "Nur Diagnose."})

        with mock.patch.object(agent_app, "agent_llm", side_effect=planner):
            result = agent_app.run_agent_v2(
                "Diagnostiziere das System",
                mode="diagnostic",
            )

        self.assertEqual(result["steps"][0]["action"], "code_patch")
        self.assertEqual(result["steps"][0]["status"], "rejected")
        self.assertFalse((self.workspace_one / "blocked.txt").exists())
        self.assertNotIn("code_patch", agent_app.allowed_agent_tools("diagnostic"))

    def test_coding_agent_blocks_shell_writes_and_outside_patches(self):
        self.add_workspace()

        with self.assertRaises(ValueError):
            agent_app.execute_read_only_agent_tool(
                "shell_read",
                "Create file",
                query="echo Hallo > test.txt",
            )

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_WORKSPACE"):
            agent_app.execute_read_only_agent_tool(
                "code_patch",
                "Create file",
                instruction="Outside write",
                files=[{
                    "path": "../outside.txt",
                    "proposed_content": "blocked",
                }],
            )

    def test_frontend_routes_new_text_files_to_file_pipeline(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/assets/chat/generation.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "textFiles.length > 0 ||",
            source,
        )
        self.assertIn(
            "fileOperationPattern.test(prompt) ||",
            source,
        )
        self.assertIn(
            "fileExcerptPattern.test(prompt)",
            source,
        )
        self.assertIn(
            "refersToExistingFile &&",
            source,
        )
        self.assertIn(
            "priorFileAttachments.length > 0",
            source,
        )

        # A newly attached file must not depend on a keyword match.
        routing_start = source.index(
            "const routesFileOperation ="
        )
        routing_end = source.index(
            "if (",
            routing_start,
        )
        routing_block = source[
            routing_start:routing_end
        ]

        self.assertLess(
            routing_block.index("textFiles.length > 0"),
            routing_block.index("fileOperationPattern.test(prompt)"),
        )

    def test_frontend_recognizes_file_followup_language(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/assets/chat/generation.js"
        ).read_text(encoding="utf-8")

        self.assertIn("zeile|zeilen", source)
        self.assertIn("inhalt|inhaltlich", source)
        self.assertIn("darin|davon|daraus", source)
        self.assertIn("datensatz|datensätze", source)

    def test_frontend_routes_explicit_line_excerpt_followups(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/assets/chat/generation.js"
        ).read_text(encoding="utf-8")

        self.assertIn("const fileExcerptPattern", source)
        self.assertIn("fileExcerptPattern.test(prompt)", source)
        self.assertIn("fileOperationPattern.test(prompt) ||", source)

    def test_frontend_file_pipeline_keeps_audit_exclusion(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/assets/chat/generation.js"
        ).read_text(encoding="utf-8")

        routing_start = source.index(
            "const routesFileOperation ="
        )
        routing_end = source.index(
            "if (",
            routing_start,
        )
        routing_block = source[
            routing_start:routing_end
        ]

        self.assertIn(
            "!auditPattern.test(prompt)",
            routing_block,
        )

    def test_frontend_forwards_router_mode_from_data(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/assets/chat/generation.js"
        ).read_text(encoding="utf-8")
        self.assertIn("toolResult.data?.mode ||", source)
        self.assertIn("conversation_context: conversationContext", source)
        self.assertIn("buildAgentConversationContext", source)
        self.assertIn("run_id: runId", source)
        self.assertIn("/api/mlx/agent/runs/", source)



    def test_agent_progress_callback_failure_is_non_fatal_and_logged(self):
        progress_calls = []

        def broken_progress(*args, **kwargs):
            progress_calls.append((args, kwargs))
            raise RuntimeError("progress persistence failed")

        with (
            mock.patch.object(
                agent_app,
                "ambiguous_delete_reference",
                return_value=True,
            ),
            self.assertLogs(
                agent_app.logger.name,
                level="ERROR",
            ) as captured,
        ):
            result = agent_app.run_agent_v2(
                "Lösche das",
                mode="coding",
                progress_callback=broken_progress,
            )

        self.assertEqual(
            result["status"],
            "completed",
        )

        self.assertIn(
            "Welche konkrete Datei",
            result["answer"],
        )

        self.assertGreaterEqual(
            len(progress_calls),
            1,
        )

        logged = "\n".join(captured.output)

        self.assertIn(
            "Agent progress callback failed",
            logged,
        )

        self.assertIn(
            "progress persistence failed",
            logged,
        )




    def test_workspace_file_listing_question_routes_to_coding_agent(self):
        with mock.patch.object(
            agent_app.code_workspaces,
            "active_workspace",
            return_value={
                "workspace_id": "workspace-1",
                "root_path": "/tmp/workspace-1",
            },
        ):
            result = agent_app._deterministic_chat_action(
                "Welche Dateien befinden sich im Workspace?"
            )

        self.assertEqual(
            result,
            "coding_agent",
            "read-only workspace inspection must route to coding_agent",
        )

    def test_active_workspace_is_primary_context_for_local_requests(self):
        workspace = {
            "workspace_id": "workspace-1",
            "root_path": "/tmp/workspace-1",
        }

        prompts = (
            "Siehst du das blackjack Spiel?",
            "Siehst du blackjack.html?",
            "Schau dir blackjack.html an.",
            "Öffne index.html.",
            "Was steht in app.js?",
            "Prüfe diese Datei style.css.",
            "Wie funktioniert das hier?",
            "Findest du den Fehler?",
            "Mach das schöner.",
            "Kann man das besser machen?",
        )

        with mock.patch.object(
            agent_app.code_workspaces,
            "active_workspace",
            return_value=workspace,
        ):
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    self.assertEqual(
                        agent_app._deterministic_chat_action(
                            prompt
                        ),
                        "coding_agent",
                    )

    def test_active_workspace_does_not_capture_general_questions(self):
        workspace = {
            "workspace_id": "workspace-1",
            "root_path": "/tmp/workspace-1",
        }

        cases = {
            "Was ist ein Workspace?": "normal_chat",
            "Was ist der Satz des Pythagoras?": "normal_chat",
            "Heute hatte ich einen schlechten Tag.": None,
            "Was sind die aktuellen Nachrichten aus Deutschland?":
                "web_search",
        }

        with mock.patch.object(
            agent_app.code_workspaces,
            "active_workspace",
            return_value=workspace,
        ):
            for prompt, expected in cases.items():
                with self.subTest(prompt=prompt):
                    self.assertEqual(
                        agent_app._deterministic_chat_action(
                            prompt
                        ),
                        expected,
                    )

    def test_workspace_definition_question_stays_normal_chat(self):
        with mock.patch.object(
            agent_app.code_workspaces,
            "active_workspace",
            return_value={
                "workspace_id": "workspace-1",
                "root_path": "/tmp/workspace-1",
            },
        ):
            result = agent_app._deterministic_chat_action(
                "Was ist ein Workspace?"
            )

        self.assertEqual(
            result,
            "normal_chat",
            "general knowledge about workspaces must not trigger coding_agent",
        )


    def test_workspace_file_listing_question_chooses_code_files(self):
        response = (
            '{"action":"code_files",'
            '"query":"",'
            '"reason":"Workspace-Dateien auflisten"}'
        )

        with mock.patch.object(
            agent_app.code_workspaces,
            "active_workspace",
            return_value={
                "workspace_id": "workspace-1",
                "root_path": "/tmp/workspace-1",
            },
        ), mock.patch.object(
            agent_app,
            "agent_llm",
            return_value=response,
        ) as llm:
            decision = agent_app.agent_choose_next_step_v2(
                "Welche Dateien befinden sich im Workspace?",
                [],
                mode="coding",
            )

        self.assertEqual(
            decision["action"],
            "code_files",
        )

        llm.assert_called_once()


    def test_deactivate_workspace_leaves_workspace_registered(self):
        workspace = code_workspaces.add_workspace(
            str(self.workspace_one),
            activate=True,
        )

        self.assertIsNotNone(
            code_workspaces.active_workspace()
        )

        result = code_workspaces.deactivate_workspace()

        self.assertIsNone(
            code_workspaces.active_workspace()
        )

        workspace_ids = {
            item["workspace_id"]
            for item in code_workspaces.list_workspaces()
        }

        self.assertIn(
            workspace["workspace_id"],
            workspace_ids,
            "closing a workspace must not remove it from the workspace list",
        )

        self.assertEqual(
            result,
            {"active_workspace": None},
        )



class FolderPickerTests(unittest.TestCase):
    def test_folder_picker_cancel_returns_clean_status(self):
        cancelled = subprocess.CompletedProcess(
            args=["osascript"],
            returncode=1,
            stdout="",
            stderr="execution error: User canceled. (-128)",
        )

        with mock.patch.object(agent_app.subprocess, "run", return_value=cancelled) as run:
            result = agent_app.pick_code_workspace_folder()

        self.assertEqual(result, {"status": "cancelled"})
        self.assertEqual(run.call_args.args[0][0], "osascript")
        self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
