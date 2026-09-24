import unittest
from pathlib import Path
from unittest.mock import patch

from agent import app as agent_app


class ImageEditModelRoutingTests(unittest.TestCase):
    def test_image_edit_uses_auto_model_instead_of_image_role(self):
        request = agent_app.ChatActionRequest(
            prompt="ändere das bild und mache die unterwäsche rot",
        )

        with (
            patch(
                "agent.app._image_source_path",
                return_value=Path("/tmp/source.png"),
            ),
            patch(
                "agent.app.load_model_roles",
                side_effect=AssertionError(
                    "image edit must not use the normal image role"
                ),
            ),
        ):
            payload = agent_app._image_edit_payload(request)

        self.assertEqual(payload["model"], "auto")
        self.assertEqual(payload["source_path"], "/tmp/source.png")
        self.assertTrue(payload["prompt"])


if __name__ == "__main__":
    unittest.main()
