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
            "if len(sys.argv) > 1 and sys.argv[1].endswith('runtime-model-guard.py'):\n"
            "    raise SystemExit(0)\n"
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

    def make_hf_symlink_cache(self, repo):
        cache_name = "models--" + repo.replace("/", "--")
        model_cache = self.home / ".cache" / "huggingface" / "hub" / cache_name
        blobs = model_cache / "blobs"
        snapshot = model_cache / "snapshots" / "revision"
        blobs.mkdir(parents=True)
        snapshot.mkdir(parents=True)
        blob = blobs / "config-blob"
        blob.write_text("{}\n", encoding="utf-8")
        (snapshot / "config.json").symlink_to(blob)

    def test_matching_vlm_target_enables_mtp_draft(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn("Speculative: enabled (mtp, block 3)", result.stdout)
        self.assertEqual(args[:3], ["-m", "mlx_vlm", "server"])
        self.assertEqual(args[args.index("--draft-model") + 1], str(self.draft))
        self.assertEqual(args[args.index("--draft-kind") + 1], "mtp")
        self.assertEqual(args[args.index("--draft-block-size") + 1], "3")

    def test_dflash_can_use_model_default_block_size(self):
        result = self.run_script(kind="dflash", block="")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn(
            "Speculative: enabled (dflash, model default block)",
            result.stdout,
        )
        self.assertEqual(args[args.index("--draft-kind") + 1], "dflash")
        self.assertNotIn("--draft-block-size", args)

    def test_hugging_face_symlink_snapshot_is_available(self):
        repo = "z-lab/Qwen3.8-27B-DFlash2"
        self.make_hf_symlink_cache(repo)
        result = self.run_script(draft=repo, kind="dflash", block="")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.final_args(result)
        self.assertIn(
            "Speculative: enabled (dflash, model default block)",
            result.stdout,
        )
        self.assertEqual(args[args.index("--draft-model") + 1], repo)

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
