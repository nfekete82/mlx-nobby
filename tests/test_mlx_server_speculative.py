import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mlx-server-start"


class MlxServerSpeculativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.config = self.home / ".config" / "mlx-server" / "config"
        self.config.parent.mkdir(parents=True)
        self.target = self.root / "target"
        self.target.mkdir()
        (self.target / "config.json").write_text("{}\n", encoding="utf-8")
        self.draft = self.root / "draft"
        self.draft.mkdir()
        self.fake_python = self.root / "fake-python"
        self.fake_python.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "if len(sys.argv) > 1 and sys.argv[1] == '-':\n"
            "    print(os.environ.get('FAKE_BACKEND', 'vlm'))\n"
            "else:\n"
            "    print('FAKE_ARGS=' + json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        self.fake_python.chmod(0o755)

    def run_script(self, *, configured_target=None, draft=None, kind="mtp", block="3"):
        configured_target = self.target if configured_target is None else configured_target
        draft = self.draft if draft is None else draft
        self.config.write_text(
            "\n".join(
                [
                    f'MODEL="{self.target}"',
                    'PORT="8000"',
                    'THINKING="false"',
                    f'SPECULATIVE_TARGET="{configured_target}"',
                    f'SPECULATIVE_DRAFT_MODEL="{draft}"',
                    f'SPECULATIVE_DRAFT_KIND="{kind}"',
                    f'SPECULATIVE_DRAFT_BLOCK_SIZE="{block}"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(self.home),
                "MLX_RUNTIME_PYTHON": str(self.fake_python),
                "MLX_PREFILL_STEP_SIZE": "512",
                "FAKE_BACKEND": "vlm",
            }
        )
        return subprocess.run(
            ["bash", str(SCRIPT)],
            text=True,
            capture_output=True,
            env=environment,
        )

    @staticmethod
    def final_args(result):
        line = next(
            item for item in result.stdout.splitlines() if item.startswith("FAKE_ARGS=")
        )
        return json.loads(line.split("=", 1)[1])

    def test_matching_vlm_target_enables_mtp_draft(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn("Speculative: enabled (mtp, block 3)", result.stdout)
        self.assertEqual(args[:3], ["-m", "mlx_vlm", "server"])
        self.assertEqual(args[args.index("--draft-model") + 1], str(self.draft))
        self.assertEqual(args[args.index("--draft-kind") + 1], "mtp")
        self.assertEqual(args[args.index("--draft-block-size") + 1], "3")

    def test_target_mismatch_never_passes_draft_flags(self):
        result = self.run_script(configured_target=self.root / "other-target")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn("Speculative: disabled (target mismatch)", result.stdout)
        self.assertNotIn("--draft-model", args)

    def test_missing_local_draft_degrades_to_normal_runtime(self):
        result = self.run_script(draft=self.root / "missing-draft")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn("draft model is not cached locally", result.stdout)
        self.assertNotIn("--draft-model", args)

    def test_invalid_matching_configuration_fails_fast(self):
        result = self.run_script(kind="unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SPECULATIVE_DRAFT_KIND", result.stderr)


if __name__ == "__main__":
    unittest.main()
