import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import app as agent_app
from agent import disk_usage


class DiskUsageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "home"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def scan(self, **options):
        return disk_usage.scan_disk_usage(
            {
                "path": str(self.root),
                "min_size_bytes": 0,
                "max_depth": 8,
                **options,
            },
            home=self.root,
        )

    def test_finds_largest_files_in_descending_order(self):
        (self.root / "small.bin").write_bytes(b"x" * 10)
        (self.root / "large.bin").write_bytes(b"x" * 30)
        (self.root / "medium.bin").write_bytes(b"x" * 20)

        result = self.scan(mode="files")

        self.assertEqual(
            [item["size_bytes"] for item in result["largest_files"]],
            [30, 20, 10],
        )

    def test_respects_limit_and_minimum_size(self):
        for name, size in (("a", 10), ("b", 20), ("c", 30)):
            (self.root / name).write_bytes(b"x" * size)

        result = self.scan(mode="files", limit=1, min_size_bytes=15)

        self.assertEqual(len(result["largest_files"]), 1)
        self.assertEqual(result["largest_files"][0]["size_bytes"], 30)

    def test_recursive_directory_sizes_preserve_ranking(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        (first / "one.bin").write_bytes(b"x" * 40)
        (second / "two.bin").write_bytes(b"x" * 15)

        result = self.scan(mode="directories")

        self.assertEqual(
            [Path(item["path"]).name for item in result["largest_directories"]],
            ["first", "second"],
        )
        self.assertEqual(
            result["directory_size_method"],
            "sum_of_scanned_unique_regular_files",
        )

    def test_respects_max_depth_and_marks_partial(self):
        level_one = self.root / "one"
        level_two = level_one / "two"
        level_two.mkdir(parents=True)
        (level_one / "visible.bin").write_bytes(b"x" * 10)
        (level_two / "hidden.bin").write_bytes(b"x" * 100)

        result = self.scan(mode="files", max_depth=1)

        self.assertEqual(
            [Path(item["path"]).name for item in result["largest_files"]],
            ["visible.bin"],
        )
        self.assertTrue(result["partial"])
        self.assertIn("max_depth", result["partial_reasons"])

    def test_permission_error_does_not_abort_scan(self):
        readable = self.root / "readable"
        blocked = self.root / "blocked"
        readable.mkdir()
        blocked.mkdir()
        (readable / "visible.bin").write_bytes(b"x" * 20)
        real_scandir = disk_usage.os.scandir
        blocked = blocked.resolve()

        def guarded_scandir(path):
            if Path(path).resolve() == blocked:
                raise PermissionError(errno.EACCES, "denied", str(path))
            return real_scandir(path)

        with mock.patch.object(
            disk_usage.os,
            "scandir",
            side_effect=guarded_scandir,
        ):
            result = self.scan(mode="files")

        self.assertEqual(result["permission_errors"], 1)
        self.assertTrue(result["partial"])
        self.assertEqual(
            Path(result["largest_files"][0]["path"]).name,
            "visible.bin",
        )

    def test_does_not_follow_directory_symlinks(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "large.bin").write_bytes(b"x" * 200)
        (self.root / "outside-link").symlink_to(outside, target_is_directory=True)

        result = self.scan(mode="both")

        self.assertEqual(result["largest_files"], [])
        self.assertEqual(result["skipped_symlinks"], 1)

    def test_rejects_traversal_and_disallowed_paths(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()

        with self.assertRaisesRegex(ValueError, "traversal"):
            disk_usage.resolve_scan_root(
                str(self.root / ".." / "outside"),
                home=self.root,
            )
        with self.assertRaisesRegex(ValueError, "outside approved roots"):
            disk_usage.resolve_scan_root(outside, home=self.root)

    def test_entry_limit_returns_partial_result(self):
        for index in range(3):
            (self.root / f"{index}.bin").write_bytes(b"x")

        result = disk_usage.scan_disk_usage(
            {
                "path": str(self.root),
                "min_size_bytes": 0,
                "max_depth": 2,
            },
            home=self.root,
            max_entries=1,
        )

        self.assertTrue(result["partial"])
        self.assertIn("entry_limit", result["partial_reasons"])
        self.assertEqual(result["scanned_entries"], 1)

    def test_deadline_returns_partial_result(self):
        (self.root / "file.bin").write_bytes(b"x")
        clock = iter((10.0, 11.0))

        result = disk_usage.scan_disk_usage(
            {"path": str(self.root), "min_size_bytes": 0},
            home=self.root,
            deadline_seconds=0.5,
            monotonic=lambda: next(clock),
        )

        self.assertTrue(result["partial"])
        self.assertIn("deadline", result["partial_reasons"])
        self.assertEqual(result["scanned_entries"], 0)

    def test_can_exclude_hidden_entries(self):
        (self.root / ".hidden.bin").write_bytes(b"x" * 20)
        (self.root / "visible.bin").write_bytes(b"x" * 10)

        result = self.scan(mode="files", include_hidden=False)

        self.assertEqual(
            [Path(item["path"]).name for item in result["largest_files"]],
            ["visible.bin"],
        )

    def test_empty_directory_and_unicode_filename(self):
        empty = self.scan()
        self.assertFalse(empty["partial"])
        self.assertEqual(empty["largest_files"], [])

        (self.root / "größte-datei.bin").write_bytes(b"123")
        result = self.scan(mode="files")
        self.assertEqual(
            Path(result["largest_files"][0]["path"]).name,
            "größte-datei.bin",
        )

    def test_default_path_resolves_to_home(self):
        result = disk_usage.scan_disk_usage(
            {"min_size_bytes": 0},
            home=self.root,
        )
        self.assertEqual(result["root"], str(self.root.resolve()))


class DiskUsageAgentIntegrationTests(unittest.TestCase):
    def test_storage_requests_choose_disk_usage_without_planner_call(self):
        prompts = (
            "größte Dateien auf meinem Rechner",
            "welche Ordner brauchen am meisten Speicher",
        )
        with mock.patch.object(agent_app, "agent_llm") as llm:
            for prompt in prompts:
                decision = agent_app.agent_choose_next_step_v2(
                    prompt,
                    [],
                    mode="diagnostic",
                )
                self.assertEqual(decision["action"], "disk_usage")
                self.assertEqual(
                    agent_app._deterministic_chat_action(prompt),
                    "diagnostic_agent",
                )
        llm.assert_not_called()

    def test_disk_usage_options_reach_native_tool(self):
        options = {
            "path": "/Users/test/Downloads",
            "mode": "files",
            "limit": 5,
        }
        with mock.patch.object(
            agent_app,
            "tool_disk_usage",
            return_value={"root": options["path"]},
        ) as native_tool:
            result = agent_app.execute_read_only_agent_tool(
                "disk_usage",
                "Find large downloads",
                options=options,
            )

        native_tool.assert_called_once_with(options)
        self.assertEqual(result["root"], options["path"])

    def test_unrelated_diagnostic_still_uses_planner(self):
        response = '{"action":"system_status","reason":"Status prüfen"}'
        with mock.patch.object(
            agent_app,
            "agent_llm",
            return_value=response,
        ) as llm:
            decision = agent_app.agent_choose_next_step_v2(
                "Prüfe den Status des MLX-Servers",
                [],
                mode="diagnostic",
            )

        self.assertEqual(decision["action"], "system_status")
        llm.assert_called_once()

        self.assertFalse(agent_app._looks_like_disk_usage_request(
            "Welche Prozesse brauchen am meisten RAM?"
        ))
        self.assertFalse(agent_app._looks_like_disk_usage_request(
            "Zeige die größten Dateien im aktiven Workspace"
        ))

    def test_disk_usage_flow_never_invokes_shell_read_first(self):
        disk_result = {
            "root": "/Users/test",
            "partial": False,
            "largest_files": [],
            "largest_directories": [],
            "warnings": [],
        }
        final = '{"action":"final","answer":"Speicheranalyse abgeschlossen."}'
        with mock.patch.object(
            agent_app,
            "tool_disk_usage",
            return_value=disk_result,
        ) as native_tool, mock.patch.object(
            agent_app,
            "tool_shell_read",
        ) as shell_tool, mock.patch.object(
            agent_app,
            "agent_llm",
            return_value=final,
        ):
            result = agent_app.run_agent_v2(
                "Zeig mir die größten Dateien",
                mode="diagnostic",
            )

        native_tool.assert_called_once_with({})
        shell_tool.assert_not_called()
        self.assertEqual(result["steps"][0]["action"], "disk_usage")
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
