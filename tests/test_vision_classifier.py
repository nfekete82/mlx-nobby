import sys
import types
import unittest
from unittest import mock

from agent import vision_classifier
from agent.vision_classifier import (
    VisionClassifierError,
    _classification_from_probabilities,
)


class VisionClassifierTests(unittest.TestCase):
    def test_sfw_classification(self):
        result = _classification_from_probabilities(
            [0.01, 0.04, 0.95],
        )

        self.assertEqual(result.label, "safe")
        self.assertAlmostEqual(
            result.confidence,
            0.95,
        )

        self.assertAlmostEqual(
            result.scores["sfw"],
            0.95,
        )

    def test_nsfw_classification(self):
        result = _classification_from_probabilities(
            [0.01, 0.97, 0.02],
        )

        self.assertEqual(result.label, "nsfw")
        self.assertAlmostEqual(
            result.confidence,
            0.97,
        )

    def test_nsfl_is_not_mapped_to_adult(self):
        result = _classification_from_probabilities(
            [0.91, 0.05, 0.04],
        )

        self.assertEqual(result.label, "nsfl")

    def test_rejects_invalid_output(self):
        with self.assertRaises(
            VisionClassifierError
        ):
            _classification_from_probabilities(
                [0.5, 0.5],
            )


    def test_session_checks_ram_before_loading_onnx_model(self):
        calls = []
        fake_session = object()
        fake_ort = types.SimpleNamespace(
            InferenceSession=lambda *args, **kwargs: fake_session,
        )

        previous = vision_classifier._SESSION
        vision_classifier._SESSION = None
        try:
            with (
                mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}),
                mock.patch.object(
                    vision_classifier,
                    "ensure_model",
                    return_value=vision_classifier.DEFAULT_MODEL_PATH,
                ),
                mock.patch.object(
                    vision_classifier.runtime_coordinator,
                    "ensure_model_load_allowed",
                    side_effect=lambda workload: calls.append(workload),
                ),
            ):
                result = vision_classifier._session()
        finally:
            vision_classifier._SESSION = previous

        self.assertIs(result, fake_session)
        self.assertEqual(calls, ["vision-classifier"])


if __name__ == "__main__":
    unittest.main()
