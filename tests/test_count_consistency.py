"""Regression checks for final-response enumeration consistency."""
import unittest
from agent.count_consistency import align_enumerated_count


class CountConsistencyTests(unittest.TestCase):
    def test_real_iphone_response(self):
        answer = ("Apple bietet aktuell offiziell sechs iPhone-Modelle an:\n\n"
                  + "\n".join(f"{n}. **iPhone Modell {n}**" for n in range(1, 8)))
        self.assertIn("sieben iPhone-Modelle", align_enumerated_count(answer))

    def test_matching_count_unchanged(self):
        text = "Zwei Modelle:\n1. Alpha\n2. Beta"
        self.assertEqual(align_enumerated_count(text), text)

    def test_nonconsecutive_list_unchanged(self):
        text = "Drei Modelle:\n1. Alpha\n3. Gamma"
        self.assertEqual(align_enumerated_count(text), text)

    def test_no_enumerated_list_unchanged(self):
        text = "Sechs Modelle insgesamt."
        self.assertEqual(align_enumerated_count(text), text)


if __name__ == "__main__":
    unittest.main()
