import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "mlx_agent", Path(__file__).resolve().parents[1] / "agent" / "app.py"
)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class BatchTransformTests(unittest.TestCase):
    def test_fast_replaces_email_and_phone(self):
        value = agent.apply_deterministic_transform(
            "Mail anna@example.org, Telefon +49 30 1234567",
            ["replace_emails", "replace_phone_numbers"],
        )
        self.assertIn("<EMAIL>", value)
        self.assertIn("<TELEFON>", value)

    def test_hybrid_detects_remaining_name_and_address(self):
        plan = agent.classify_batch_instruction("Anonymisiere Namen, Adressen, E-Mail und Telefon")
        value = agent.apply_deterministic_transform(
            "Frau Anna Müller, Hauptstraße 12, 12345 Berlin, anna@example.org, +49 30 1234567",
            plan["fast_operations"],
        )
        self.assertTrue(agent.hybrid_chunk_needs_llm(value, plan["llm_operations"]))

    def test_summary_stays_llm(self):
        self.assertEqual(agent.classify_batch_instruction("Fasse diese Datei zusammen")["mode"], "llm")

    def test_json_chunks_and_fast_output_remain_valid(self):
        original = [{"Date": "2026-01-01", "Subject": "sample@example.org", "Body": "Ruf 030 1234567 an"}]
        chunks = agent.split_batch_content(json.dumps(original), "json", 500)
        transformed = [
            agent.apply_deterministic_transform(part, ["replace_emails", "replace_phone_numbers"])
            for part in chunks
        ]
        rebuilt = [entry for chunk in transformed for entry in json.loads(chunk)]
        self.assertEqual(rebuilt[0]["Date"], "2026-01-01")
        self.assertEqual(rebuilt[0]["Subject"], "<EMAIL>")

    def test_hybrid_skip_does_not_need_mlx_for_clean_chunk(self):
        value = agent.apply_deterministic_transform("Kontakt: sample@example.org, +49 30 1234567", ["replace_emails", "replace_phone_numbers"])
        self.assertFalse(agent.hybrid_chunk_needs_llm(value, ["replace_names", "replace_addresses"]))

    def test_large_json_inspection_returns_structure_without_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mails.json"
            path.write_text(json.dumps([
                {"Date": "2026-01-01", "Subject": "Hallo", "Body": "Text"},
                {"Date": "2026-02-01", "Subject": "Welt", "Body": "Text"},
            ]), encoding="utf-8")
            result = agent.analyze_file_structure(path)
        self.assertEqual(result["record_count"], 2)
        self.assertIn("Subject", result["frequent_keys"])
        self.assertEqual(result["date_range_sample"]["min"], "2026-01-01")

    def test_chat_action_router_uses_metadata_only_actions(self):
        self.assertEqual(agent.classify_chat_action("Welches Modell läuft?"), "model_list")
        self.assertEqual(agent.classify_chat_action("Wie viel RAM nutzt das Modell?"), "system_status")
        self.assertEqual(agent.classify_chat_action("Zeig mir die letzten Fehler."), "logs_query")
        self.assertEqual(agent.classify_chat_action("Fasse sie zusammen.", {"stored_path": "/tmp/a.json"}), "file_summarize")
        self.assertEqual(agent.classify_chat_action("Mach einen PII Audit.", {"stored_path": "/tmp/a.json"}), "pii_audit")

    def test_chat_action_router_keeps_normal_chat_normal(self):
        with mock.patch.object(
            agent,
            "semantic_intent_classifier",
            return_value={
                "intent": "normal_chat",
                "confidence": 0.99,
                "requires_tools": False,
                "reason": "Allgemeine Wissensfrage",
            },
        ):
            self.assertEqual(
                agent.classify_chat_action("Erkläre mir Rekursion."),
                "normal_chat",
            )

    def test_workspace_artifact_context_survives_chat_normalization(self):
        raw = {
            "id": "artifact-test", "title": "Test", "created": 1, "updated": 1,
            "messages": [], "workspace": {"active_artifact_id": "artifact-1"},
        }
        self.assertEqual(agent.normalize_chat(raw)["workspace"]["active_artifact_id"], "artifact-1")


if __name__ == "__main__":
    unittest.main()
