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

    def test_file_excerpt_selection(self):
        self.assertEqual(
            agent.parse_file_excerpt_selection(
                "Was steht in den ersten 20 Zeilen? Fasse es zusammen."
            ),
            {
                "kind": "line_range",
                "start_line": 1,
                "end_line": 20,
            },
        )

        self.assertEqual(
            agent.parse_file_excerpt_selection(
                "Fasse Zeilen 100 bis 150 zusammen."
            ),
            {
                "kind": "line_range",
                "start_line": 100,
                "end_line": 150,
            },
        )

        self.assertEqual(
            agent.parse_file_excerpt_selection(
                "Zeig mir die letzten 30 Zeilen."
            ),
            {
                "kind": "last_lines",
                "count": 30,
            },
        )

        self.assertIsNone(
            agent.parse_file_excerpt_selection(
                "Fasse die Datei zusammen."
            )
        )

    def test_read_file_excerpt_first_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text(
                "eins\nzwei\ndrei\nvier\nfuenf\n",
                encoding="utf-8",
            )

            result = agent.read_file_excerpt(
                path,
                {
                    "kind": "line_range",
                    "start_line": 1,
                    "end_line": 3,
                },
            )

        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["end_line"], 3)
        self.assertEqual(result["line_count"], 3)
        self.assertEqual(
            result["content"],
            "1: eins\n2: zwei\n3: drei",
        )

    def test_read_file_excerpt_last_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text(
                "eins\nzwei\ndrei\nvier\nfuenf\n",
                encoding="utf-8",
            )

            result = agent.read_file_excerpt(
                path,
                {
                    "kind": "last_lines",
                    "count": 2,
                },
            )

        self.assertEqual(result["start_line"], 4)
        self.assertEqual(result["end_line"], 5)
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(
            result["content"],
            "4: vier\n5: fuenf",
        )

    def test_file_excerpt_selection_caps_large_ranges(self):
        self.assertEqual(
            agent.parse_file_excerpt_selection(
                "Fasse die ersten 5000 Zeilen zusammen."
            ),
            {
                "kind": "line_range",
                "start_line": 1,
                "end_line": 500,
            },
        )

    def test_file_excerpt_job_uses_single_llm_call(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text(
                "\n".join(
                    f"Zeile {index}"
                    for index in range(1, 101)
                ) + "\n",
                encoding="utf-8",
            )

            job = agent.create_file_analysis_job(
                source,
                "Fasse die ersten 20 Zeilen zusammen.",
                "text",
                2000,
                "summarize",
            )

            self.assertEqual(
                job["selection"],
                {
                    "kind": "line_range",
                    "start_line": 1,
                    "end_line": 20,
                },
            )

            with mock.patch.object(
                agent,
                "analyze_file_structure",
            ) as analyzer, mock.patch.object(
                agent,
                "local_file_llm",
                return_value="Kurzfassung",
            ) as llm, mock.patch.object(
                agent,
                "split_batch_content",
            ) as splitter:
                agent.run_file_analysis_job(job["id"])

            analyzer.assert_not_called()
            splitter.assert_not_called()
            llm.assert_called_once()

            stored = agent.load_batch_jobs()[job["id"]]

            self.assertEqual(
                stored["status"],
                "completed",
            )
            self.assertEqual(
                stored["processed_chunks"],
                1,
            )
            self.assertEqual(
                stored["total_chunks"],
                1,
            )
            self.assertEqual(
                stored["mlx_calls"],
                1,
            )
            self.assertEqual(
                stored["excerpt"]["start_line"],
                1,
            )
            self.assertEqual(
                stored["excerpt"]["end_line"],
                20,
            )

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
