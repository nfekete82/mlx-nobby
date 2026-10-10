"""Product launches require model names in actually fetched article text."""
import unittest
from agent.prompts import verify_product_launch_items


class ProductLaunchEvidenceTests(unittest.TestCase):
    def test_only_models_present_in_fetched_text_remain(self):
        observations = [
            {"action": "fetch_url", "status": "completed", "result": {
                "ok": True, "url": "https://example.org/phones",
                "text": "Pixel 11 was officially introduced on 12 August 2026. " * 12}},
            {"action": "web_search", "status": "completed", "result": {
                "results": [{"url": "https://example.org/other"}]}}
        ]
        result = verify_product_launch_items(
            "1. **Pixel 11** – vorgestellt\n2. **Phantom 42** – vorgestellt",
            observations)
        self.assertIn("Pixel 11", result)
        self.assertIn("https://example.org/phones", result)
        self.assertNotIn("Phantom 42", result)

    def test_forecast_is_not_proof_of_presentation(self):
        observations = [{"action": "fetch_url", "status": "completed",
            "result": {"ok": True, "url": "https://example.org/forecast",
                       "text": "The Pixel 11 will likely be introduced on 12 August 2026. " * 12}}]
        result = verify_product_launch_items("1. **Pixel 11** (12.08.2026)", observations)
        self.assertIn("nicht ausreichend", result)

    def test_wrong_date_is_not_proof(self):
        observations = [{"action": "fetch_url", "status": "completed",
            "result": {"ok": True, "url": "https://example.org/event",
                       "text": "The Pixel 11 was introduced on 12 August 2026. " * 12}}]
        result = verify_product_launch_items("1. **Pixel 11** (13.08.2026)", observations)
        self.assertIn("nicht ausreichend", result)

    def test_search_hits_alone_are_not_proof(self):
        observations = [{"action": "web_search", "status": "completed",
                         "result": {"results": [{"title": "Pixel 11"}]}}]
        result = verify_product_launch_items("1. **Pixel 11**", observations)
        self.assertIn("nicht ausreichend", result)


if __name__ == "__main__":
    unittest.main()
