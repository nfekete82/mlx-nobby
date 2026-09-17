import base64
import unittest
from unittest import mock

from agent.vision_classifier import (
    VisionClassifierError,
)
from agent.vision_routing import (
    VisionClassification,
)


def data_url(
    value=b"fake-image",
):
    return (
        "data:image/png;base64,"
        + base64.b64encode(
            value
        ).decode("ascii")
    )


class VisionRouteApiTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        from agent import app
        cls.app = app

    def _runtime(self, role):
        return {
            "ok": True,
            "role": role,
            "resolved": {
                "alias": role,
                "repo": f"/models/{role}",
            },
        }

    def test_safe_image_selects_normal_vision(
        self,
    ):
        classification = (
            VisionClassification(
                "safe",
                confidence=0.98,
            )
        )

        with (
            mock.patch(
                "agent.vision_classifier."
                "classify_image_bytes",
                return_value=classification,
            ),
            mock.patch.object(
                self.app,
                "resolve_model_role",
                return_value={
                    "repo": "/models/adult",
                    "available": True,
                },
            ),
            mock.patch.object(
                self.app,
                "ensure_model_for_role",
                side_effect=lambda role: (
                    self._runtime(role)
                ),
            ) as ensure,
        ):
            result = (
                self.app
                .route_vision_runtime({
                    "images": [
                        data_url(),
                    ],
                })
            )

        self.assertEqual(
            result["role"],
            "vision",
        )

        ensure.assert_called_once_with(
            "vision"
        )

    def test_nsfw_image_selects_adult_vision(
        self,
    ):
        classification = (
            VisionClassification(
                "nsfw",
                confidence=0.97,
            )
        )

        with (
            mock.patch(
                "agent.vision_classifier."
                "classify_image_bytes",
                return_value=classification,
            ),
            mock.patch.object(
                self.app,
                "resolve_model_role",
                return_value={
                    "repo": "/models/adult",
                    "available": True,
                },
            ),
            mock.patch.object(
                self.app,
                "ensure_model_for_role",
                side_effect=lambda role: (
                    self._runtime(role)
                ),
            ) as ensure,
        ):
            result = (
                self.app
                .route_vision_runtime({
                    "images": [
                        data_url(),
                    ],
                })
            )

        self.assertEqual(
            result["role"],
            "vision_uncensored",
        )

        ensure.assert_called_once_with(
            "vision_uncensored"
        )

    def test_any_adult_image_wins_multi_image_route(
        self,
    ):
        classifications = [
            VisionClassification(
                "safe",
                confidence=0.99,
            ),
            VisionClassification(
                "nsfw",
                confidence=0.94,
            ),
        ]

        with (
            mock.patch(
                "agent.vision_classifier."
                "classify_image_bytes",
                side_effect=classifications,
            ),
            mock.patch.object(
                self.app,
                "resolve_model_role",
                return_value={
                    "repo": "/models/adult",
                    "available": True,
                },
            ),
            mock.patch.object(
                self.app,
                "ensure_model_for_role",
                side_effect=lambda role: (
                    self._runtime(role)
                ),
            ),
        ):
            result = (
                self.app
                .route_vision_runtime({
                    "images": [
                        data_url(b"one"),
                        data_url(b"two"),
                    ],
                })
            )

        self.assertEqual(
            result["role"],
            "vision_uncensored",
        )

        self.assertEqual(
            len(
                result[
                    "classifications"
                ]
            ),
            2,
        )

    def test_classifier_failure_falls_back_to_vision(
        self,
    ):
        with (
            mock.patch(
                "agent.vision_classifier."
                "classify_image_bytes",
                side_effect=(
                    VisionClassifierError(
                        "offline"
                    )
                ),
            ),
            mock.patch.object(
                self.app,
                "resolve_model_role",
                return_value={
                    "repo": "/models/adult",
                    "available": True,
                },
            ),
            mock.patch.object(
                self.app,
                "ensure_model_for_role",
                side_effect=lambda role: (
                    self._runtime(role)
                ),
            ) as ensure,
        ):
            result = (
                self.app
                .route_vision_runtime({
                    "images": [
                        data_url(),
                    ],
                })
            )

        self.assertEqual(
            result["role"],
            "vision",
        )

        self.assertIn(
            "error",
            result[
                "classifications"
            ][0],
        )

        ensure.assert_called_once_with(
            "vision"
        )


if __name__ == "__main__":
    unittest.main()
