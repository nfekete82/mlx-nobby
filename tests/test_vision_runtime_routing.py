import tempfile
import types
import unittest

from pathlib import Path
from unittest import mock

from agent import run_state
from agent import runtime_tools
from agent.model_provider import ModelResponse
from agent.vision_classifier import (
    VisionClassifierError,
)
from agent.vision_routing import (
    VisionClassification,
)


class RecordingProvider:
    def __init__(self):
        self.roles = []

    def complete(
        self,
        request,
        *,
        run_context=None,
    ):
        self.roles.append(request.role)

        return ModelResponse(
            text="vision-result",
            model="selected-model",
            role=request.role,
            usage={},
        )


class VisionRuntimeRoutingTests(
    unittest.TestCase
):
    def _run_vision(
        self,
        classification,
        *,
        uncensored_available=True,
        classifier_error=None,
    ):
        from agent import app

        with tempfile.TemporaryDirectory() as directory:
            image = (
                Path(directory)
                / "attached.png"
            )

            # The classifier itself is mocked in these
            # routing tests, so valid image bytes are not
            # required here.
            image.write_bytes(b"image")

            context = (
                run_state.RunContext.start(
                    upload_paths=(image,),
                )
            )

            provider = RecordingProvider()

            if classifier_error is None:
                classifier = mock.Mock(
                    return_value=classification,
                )
            else:
                classifier = mock.Mock(
                    side_effect=classifier_error,
                )

            resolved = {
                "role": "vision_uncensored",
                "repo": (
                    "/models/adult"
                    if uncensored_available
                    else None
                ),
                "available": uncensored_available,
            }

            with (
                run_state.bind_run_context(
                    context
                ),
                mock.patch(
                    "agent.vision_classifier."
                    "classify_image",
                    classifier,
                ),
                mock.patch.object(
                    app,
                    "resolve_model_role",
                    return_value=resolved,
                ),
                mock.patch.object(
                    runtime_tools,
                    "current_runtime",
                    return_value=(
                        types.SimpleNamespace(
                            provider=provider
                        )
                    ),
                ),
            ):
                result = runtime_tools._vision(
                    "",
                    "Describe image",
                    {
                        "upload_path": str(
                            image
                        ),
                    },
                )

        return provider, result

    def test_safe_image_uses_normal_vision(
        self,
    ):
        provider, result = self._run_vision(
            VisionClassification(
                "safe",
                confidence=0.98,
            )
        )

        self.assertEqual(
            provider.roles,
            ["vision"],
        )

        self.assertEqual(
            result["vision_role"],
            "vision",
        )

    def test_nsfw_image_uses_adult_vision(
        self,
    ):
        provider, result = self._run_vision(
            VisionClassification(
                "nsfw",
                confidence=0.95,
            )
        )

        self.assertEqual(
            provider.roles,
            ["vision_uncensored"],
        )

        self.assertEqual(
            result["vision_role"],
            "vision_uncensored",
        )

        self.assertEqual(
            result["classification"]["label"],
            "nsfw",
        )

    def test_unavailable_adult_role_falls_back(
        self,
    ):
        provider, result = self._run_vision(
            VisionClassification(
                "nsfw",
                confidence=0.96,
            ),
            uncensored_available=False,
        )

        self.assertEqual(
            provider.roles,
            ["vision"],
        )

        self.assertEqual(
            result["vision_role"],
            "vision",
        )

    def test_classifier_failure_keeps_vision_working(
        self,
    ):
        provider, result = self._run_vision(
            None,
            classifier_error=(
                VisionClassifierError(
                    "classifier offline"
                )
            ),
        )

        self.assertEqual(
            provider.roles,
            ["vision"],
        )

        self.assertEqual(
            result["vision_role"],
            "vision",
        )

        self.assertIn(
            "classification_error",
            result,
        )

    def test_nsfl_does_not_route_to_adult(
        self,
    ):
        provider, result = self._run_vision(
            VisionClassification(
                "nsfl",
                confidence=0.99,
            )
        )

        self.assertEqual(
            provider.roles,
            ["vision"],
        )

        self.assertEqual(
            result["vision_role"],
            "vision",
        )


if __name__ == "__main__":
    unittest.main()
