import unittest

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


if __name__ == "__main__":
    unittest.main()
