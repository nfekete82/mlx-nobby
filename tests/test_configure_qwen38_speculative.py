import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure-qwen38-speculative"
DRAFT_REPO = "z-lab/Qwen3.8-27B-DFlash2"


class ConfigureQwen38SpeculativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.config = self.home / ".config" / "mlx-server" / "config"
        self.config.parent.mkdir(parents=True)
        self.target = self.root / "Qwen3.8-27B-Abliterated-MLX-4bit"
        self.target.mkdir()
        self.config.write_text(
            f'MODEL="{self.target}"\nPORT="8000"\nTHINKING="false"\n',
            encoding="utf-8",
        )

    def environment(self):
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(self.home),
                "MLX_RUNTIME_PYTHON": sys.executable,
            }
        )
        return environment

    def make_hf_symlink_cache(self):
        cache_name = "models--" + DRAFT_REPO.replace("/", "--")
        model_cache = self.home / ".cache" / "huggingface" / "hub" / cache_name
        blobs = model_cache / "blobs"
        snapshot = model_cache / "snapshots" / "revision"
        blobs.mkdir(parents=True)
        snapshot.mkdir(parents=True)
        blob = blobs / "config-blob"
        blob.write_text("{}\n", encoding="utf-8")
        (snapshot / "config.json").symlink_to(blob)

    def run_script(self, command):
        return subprocess.run(
            ["bash", str(SCRIPT), command],
            text=True,
            capture_output=True,
            env=self.environment(),
        )

    def test_status_recognizes_hugging_face_symlink_snapshot(self):
        self.make_hf_symlink_cache()
        result = self.run_script("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Qwen3.8 DFlash2:      ready", result.stdout)

    def test_enable_accepts_hugging_face_symlink_snapshot(self):
        self.make_hf_symlink_cache()
        result = self.run_script("enable")
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = self.config.read_text(encoding="utf-8")
        self.assertIn(f'SPECULATIVE_TARGET="{self.target}"', updated)
        self.assertIn(f'SPECULATIVE_DRAFT_MODEL="{DRAFT_REPO}"', updated)
        self.assertIn('SPECULATIVE_DRAFT_KIND="dflash"', updated)
        self.assertIn('SPECULATIVE_DRAFT_BLOCK_SIZE=""', updated)


if __name__ == "__main__":
    unittest.main()
