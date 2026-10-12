"""SearXNG outages degrade to a bounded, public search."""
import unittest
from unittest.mock import patch
import urllib.error
from agent.app import searxng_search_results


class SearxngFallbackTests(unittest.TestCase):
    def test_unavailable_local_instance_falls_back(self):
        expected = {"provider": "Google News RSS (fallback)", "results": [], "count": 0}
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")), \
             patch("agent.app._fallback_public_search", return_value=expected) as fallback:
            result = searxng_search_results("Elektroautos 2026", limit=4)
        self.assertEqual(result["provider"], expected["provider"])
        fallback.assert_called_once_with("Elektroautos 2026", limit=4)


if __name__ == "__main__":
    unittest.main()
