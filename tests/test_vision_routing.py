import unittest

from agent.vision_routing import (
    UNCENSORED_VISION_ROLE,
    DEFAULT_VISION_ROLE,
    VisionClassification,
    select_vision_role,
)


class VisionRoutingTests(unittest.TestCase):
    def test_no_classification_prefers_uncensored_vision(self):
        self.assertEqual(
            select_vision_role(None),
            UNCENSORED_VISION_ROLE,
        )

    def test_safe_image_prefers_uncensored_vision(self):
        classification = VisionClassification(
            "safe",
            confidence=0.99,
        )

        self.assertEqual(
            select_vision_role(classification),
            UNCENSORED_VISION_ROLE,
        )

    def test_adult_image_uses_uncensored_vision(self):
        classification = VisionClassification(
            "adult_explicit",
            confidence=0.95,
        )

        self.assertEqual(
            select_vision_role(classification),
            UNCENSORED_VISION_ROLE,
        )

    def test_low_confidence_adult_still_prefers_uncensored_vision(self):
        classification = VisionClassification(
            "adult_explicit",
            confidence=0.40,
        )

        self.assertEqual(
            select_vision_role(classification),
            UNCENSORED_VISION_ROLE,
        )

    def test_ambiguous_content_still_prefers_uncensored_vision(self):
        classification = VisionClassification(
            "age_ambiguous",
            confidence=0.99,
        )

        self.assertEqual(
            select_vision_role(classification),
            UNCENSORED_VISION_ROLE,
        )

    def test_missing_uncensored_runtime_falls_back(self):
        classification = VisionClassification(
            "adult_nudity",
            confidence=0.98,
        )

        self.assertEqual(
            select_vision_role(
                classification,
                uncensored_role_available=False,
            ),
            DEFAULT_VISION_ROLE,
        )

    def test_confidence_validation(self):
        with self.assertRaises(ValueError):
            VisionClassification(
                "safe",
                confidence=1.1,
            )


if __name__ == "__main__":
    unittest.main()
