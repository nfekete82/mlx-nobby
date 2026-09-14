import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import batch_state


class BatchStateTests(unittest.TestCase):

    def test_save_jobs_removes_temporary_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "jobs.json"

            jobs = {
                "job-1": {
                    "status": "queued",
                },
            }

            original_replace = Path.replace
            observed_temp = []

            def failing_replace(source, destination):
                source = Path(source)
                destination = Path(destination)

                if destination == path:
                    observed_temp.append(source)

                    self.assertTrue(
                        source.exists(),
                        "temporary batch-state file must exist before replace",
                    )

                    raise OSError("simulated batch-state replace failure")

                return original_replace(
                    source,
                    destination,
                )

            with mock.patch.object(
                Path,
                "replace",
                failing_replace,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated batch-state replace failure",
                ):
                    batch_state.save_jobs(
                        root,
                        path,
                        jobs,
                    )

            self.assertEqual(
                len(observed_temp),
                1,
            )

            self.assertFalse(
                observed_temp[0].exists(),
                "failed batch-state atomic write must remove temp file",
            )

            self.assertFalse(
                path.exists(),
                "failed replace must not create destination file",
            )


    def test_atomic_write_text_removes_temporary_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.txt"
            temporary = path.with_suffix(path.suffix + ".tmp")

            original_replace = Path.replace

            def failing_replace(source, destination):
                source = Path(source)
                destination = Path(destination)

                if destination == path:
                    self.assertTrue(source.exists())
                    raise OSError("simulated atomic replace failure")

                return original_replace(
                    source,
                    destination,
                )

            with mock.patch.object(
                Path,
                "replace",
                failing_replace,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated atomic replace failure",
                ):
                    batch_state.atomic_write_text(
                        path,
                        "checkpoint",
                    )

            self.assertFalse(
                temporary.exists(),
                "failed atomic text write must remove temp file",
            )

            self.assertFalse(
                path.exists(),
            )


if __name__ == "__main__":
    unittest.main()
