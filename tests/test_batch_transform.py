import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "mlx_agent", Path(__file__).resolve().parents[1] / "agent" / "app.py"
)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class BatchTransformTests(unittest.TestCase):
    @contextlib.contextmanager
    def batch_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_directory = root / "batch"
            jobs_file = batch_directory / "jobs.json"

            def checkpoint_directory(job_id):
                path = batch_directory / "checkpoints" / job_id
                path.mkdir(parents=True, exist_ok=True)
                return path

            with mock.patch.object(
                agent,
                "BATCH_DIRECTORY",
                batch_directory,
            ), mock.patch.object(
                agent,
                "BATCH_JOBS_FILE",
                jobs_file,
            ), mock.patch.object(
                agent,
                "batch_checkpoint_directory",
                side_effect=checkpoint_directory,
            ):
                yield root

    def create_transform_job(
        self,
        path,
        instruction="Ändere den Inhalt semantisch",
        chunk_tokens=12000,
    ):
        return agent.create_batch_job(
            agent.BatchTransformRequest(
                input_path=str(path),
                instruction=instruction,
                file_type="json",
                chunk_tokens=chunk_tokens,
            )
        )["job"]

    @staticmethod
    def echo_mlx_response(request, **_kwargs):
        payload = json.loads(request.data.decode("utf-8"))
        content = payload["messages"][1]["content"].split(
            "DATEI-ABSCHNITT:\n",
            1,
        )[1]
        body = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return body

        return Response()

    def test_fast_replaces_email_and_phone(self):
        value = agent.apply_deterministic_transform(
            "Mail anna@example.org, Telefon +49 30 1234567",
            ["replace_emails", "replace_phone_numbers"],
        )
        self.assertIn("<EMAIL>", value)
        self.assertIn("<TELEFON>", value)

    def test_hybrid_name_detector_avoids_common_false_positives(self):
        operations = ["replace_names"]

        false_positives = (
            "Sehr geehrte Damen und Herren",
            "Vielen Dank für Ihre Anfrage",
            "Neue Kontaktanfrage wurde erstellt",
            "Gesendet mit meinem Smartphone",
            "Deutsche Telekom",
            "Apple Watch Ultra",
        )

        for value in false_positives:
            with self.subTest(value=value):
                self.assertFalse(
                    agent.hybrid_chunk_needs_llm(
                        value,
                        operations,
                    )
                )

    def test_hybrid_name_detector_keeps_strong_name_context(self):
        operations = ["replace_names"]

        positives = (
            "Sehr geehrte Frau Anna Müller",
            "Ansprechpartner: Max Mustermann",
            "Hallo Max Mustermann",
            "Mit freundlichen Grüßen\nMax Mustermann",
            "Mit freundlichen Grüßen\\r\\nMax Mustermann",
            '{"name": "Max Mustermann"}',
        )

        for value in positives:
            with self.subTest(value=value):
                self.assertTrue(
                    agent.hybrid_chunk_needs_llm(
                        value,
                        operations,
                    )
                )

    def test_invalid_json_fails_before_first_mlx_call(self):
        with self.batch_environment() as root:
            source = root / "invalid.json"
            valid = json.dumps(
                [
                    {"id": index, "text": "x" * 220}
                    for index in range(130)
                ],
                indent=2,
            )
            invalid = valid.replace("  },\n  {", "  }\n  {", 1)
            self.assertGreater(len(invalid.encode("utf-8")), 30_000)
            source.write_text(
                invalid,
                encoding="utf-8",
            )
            job = self.create_transform_job(source)

            with mock.patch.object(
                agent.urllib.request,
                "urlopen",
            ) as urlopen:
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["mlx_calls"], 0)
            self.assertEqual(stored["total_chunks"], 0)
            self.assertEqual(
                stored["analysis"]["chunk_strategy"],
                "json_invalid",
            )
            json_error = stored["analysis"]["json_error"]
            self.assertIn(f"Zeile {json_error['line']}", stored["error"])
            self.assertIn(f"Spalte {json_error['column']}", stored["error"])
            self.assertIn("Expecting ',' delimiter", stored["error"])
            urlopen.assert_not_called()

    def test_invalid_escape_repair_preserves_literal_backslash(self):
        original = r'{"path": "C:\project\qfile"}'
        repaired = agent.sanitize_invalid_json_escapes(original)
        self.assertEqual(
            json.loads(repaired)["path"],
            r"C:\project\qfile",
        )

    def test_valid_json_encodings_and_bom_are_detected(self):
        value = '{"message": "Grüße"}'
        encodings = {
            "utf-8": value.encode("utf-8"),
            "utf-8-sig": b"\xef\xbb\xbf" + value.encode("utf-8"),
            "utf-16-le": b"\xff\xfe" + value.encode("utf-16-le"),
            "utf-16-be": b"\xfe\xff" + value.encode("utf-16-be"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, payload in encodings.items():
                with self.subTest(encoding=expected):
                    path = Path(directory) / f"{expected}.json"
                    path.write_bytes(payload)
                    analysis = agent.analyze_input_file(path)
                    self.assertTrue(analysis["valid"])
                    self.assertEqual(analysis["encoding"], expected)
                    self.assertEqual(
                        analysis["chunk_strategy"],
                        "json_object",
                    )

    def test_fast_json_output_preserves_encoding_and_bom(self):
        value = '{"email": "anna@example.org", "message": "Grüße"}'
        encodings = {
            "utf-8": value.encode("utf-8"),
            "utf-8-sig": b"\xef\xbb\xbf" + value.encode("utf-8"),
            "utf-16-le": b"\xff\xfe" + value.encode("utf-16-le"),
            "utf-16-be": b"\xfe\xff" + value.encode("utf-16-be"),
            "utf-8-replace": (
                b'{"email": "anna@example.org", "message": "\xff"}'
            ),
        }
        expected_bom = {
            "utf-8": b"",
            "utf-8-sig": b"\xef\xbb\xbf",
            "utf-16-le": b"\xff\xfe",
            "utf-16-be": b"\xfe\xff",
            "utf-8-replace": b"",
        }

        for expected, payload in encodings.items():
            with self.subTest(encoding=expected), self.batch_environment() as root:
                source = root / "input.json"
                source.write_bytes(payload)
                job = self.create_transform_job(
                    source,
                    "Ersetze E-Mail-Adressen",
                )
                with mock.patch.object(
                    agent,
                    "load_config",
                    return_value={},
                ):
                    agent.run_batch_transform_job(job["id"])

                stored = agent.load_batch_jobs()[job["id"]]
                self.assertEqual(
                    stored["status"],
                    "completed",
                    stored.get("error"),
                )
                output = Path(stored["output_path"]).read_bytes()
                bom = expected_bom[expected]
                if bom:
                    self.assertTrue(output.startswith(bom))
                else:
                    self.assertFalse(output.startswith(b"\xef\xbb\xbf"))
                    self.assertFalse(output.startswith(b"\xff\xfe"))
                    self.assertFalse(output.startswith(b"\xfe\xff"))

    def test_small_valid_json_uses_one_llm_call_and_full_output_budget(self):
        data = [
            {"id": index, "text": "x" * 220}
            for index in range(120)
        ]
        with self.batch_environment() as root:
            source = root / "small.json"
            source.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            job = self.create_transform_job(source)
            payloads = []

            def response(request, **_kwargs):
                payloads.append(json.loads(request.data.decode("utf-8")))
                return self.echo_mlx_response(request)

            with mock.patch.object(
                agent,
                "load_config",
                return_value={"MODEL": "test", "PORT": 8000},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
                side_effect=response,
            ):
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(
                stored["status"],
                "completed",
                stored.get("error"),
            )
            self.assertEqual(stored["total_chunks"], 1)
            self.assertEqual(stored["mlx_calls"], 1)
            self.assertGreater(payloads[0]["max_tokens"], 2800)
            self.assertEqual(
                json.loads(Path(stored["output_path"]).read_text()),
                data,
            )

    def test_json_array_chunking_and_reassembly_preserve_order(self):
        data = [{"index": index, "text": "x" * 80} for index in range(10)]
        chunks = agent.split_batch_content(
            json.dumps(data),
            "json",
            100,
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(isinstance(json.loads(chunk), list) for chunk in chunks))
        rebuilt = json.loads(
            agent.assemble_batch_json(
                chunks,
                {"chunk_strategy": "json_array"},
            )
        )
        self.assertEqual(rebuilt, data)

    def test_json_object_stays_whole_when_it_fits(self):
        data = {"name": "Katalog", "enabled": True, "count": 3}
        chunks = agent.split_batch_content(json.dumps(data), "json", 500)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(json.loads(chunks[0]), data)

    def test_json_object_list_chunks_without_repeating_static_fields(self):
        data = {
            "source": "export",
            "version": 2,
            "records": [
                {"index": index, "text": "x" * 100}
                for index in range(12)
            ],
        }
        chunks = agent.split_batch_content(json.dumps(data), "json", 180)
        parsed = [json.loads(chunk) for chunk in chunks]
        self.assertGreater(len(parsed), 1)
        self.assertEqual(parsed[0]["source"], "export")
        self.assertTrue(all(set(part) == {"records"} for part in parsed[1:]))
        rebuilt = json.loads(
            agent.assemble_batch_json(
                chunks,
                {
                    "chunk_strategy": "json_object_list",
                    "json_list_key": "records",
                },
            )
        )
        self.assertEqual(rebuilt, data)

    def test_deterministic_pii_job_needs_no_model_or_mlx_call(self):
        data = {"email": "anna@example.org", "phone": "+49 30 1234567"}
        with self.batch_environment() as root:
            source = root / "pii.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            job = self.create_transform_job(
                source,
                "Ersetze E-Mail und Telefonnummer",
            )
            with mock.patch.object(
                agent,
                "load_config",
                return_value={},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
            ) as urlopen:
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(
                stored["status"],
                "completed",
                stored.get("error"),
            )
            self.assertEqual(stored["mlx_calls"], 0)
            self.assertEqual(stored["total_chunks"], 0)
            self.assertEqual(stored["processed_chunks"], 0)
            self.assertEqual(stored["structured_pii_changes"], 2)
            output = json.loads(Path(stored["output_path"]).read_text())
            self.assertEqual(output["email"], "<EMAIL>")
            self.assertEqual(output["phone"], "<TELEFON>")
            urlopen.assert_not_called()

    def test_hybrid_job_calls_mlx_only_for_semantic_chunk(self):
        data = [
            {
                "text": "Neue Kontaktanfrage " + "x" * 2200,
                "email": "a@example.org",
            },
            {
                "text": (
                    "Bitte melden Sie sich bei Herr Mustermann "
                    + "x" * 2200
                ),
            },
        ]
        with self.batch_environment() as root:
            source = root / "hybrid.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            job = self.create_transform_job(
                source,
                "Mach die Datei datenschutzkonform und entferne alle persönlichen Daten",
                chunk_tokens=500,
            )
            with mock.patch.object(
                agent,
                "load_config",
                return_value={"MODEL": "test", "PORT": 8000},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
                side_effect=self.echo_mlx_response,
            ):
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(
                stored["status"],
                "completed",
                stored.get("error"),
            )
            self.assertEqual(stored["mlx_calls"], 1)
            self.assertEqual(stored["llm_freetext_targets"], 1)

    def test_metal_oom_retries_with_valid_json_subparts(self):
        data = [{"index": index, "text": "x" * 500} for index in range(12)]
        with self.batch_environment() as root:
            source = root / "oom.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            job = self.create_transform_job(source, chunk_tokens=2000)
            attempts = []

            def response(request, **_kwargs):
                attempts.append(request)
                if len(attempts) == 1:
                    raise urllib.error.HTTPError(
                        request.full_url,
                        500,
                        "out of memory",
                        {},
                        io.BytesIO(b"Metal out of memory"),
                    )
                return self.echo_mlx_response(request)

            with mock.patch.object(
                agent,
                "load_config",
                return_value={"MODEL": "test", "PORT": 8000},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
                side_effect=response,
            ):
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(stored["status"], "completed")
            self.assertEqual(stored["oom_retries"], 1)
            self.assertEqual(stored["processed_chunks"], stored["total_chunks"])
            self.assertEqual(stored["mlx_calls"], len(attempts))
            self.assertEqual(
                json.loads(Path(stored["output_path"]).read_text()),
                data,
            )

    def test_resume_reuses_completed_checkpoint(self):
        data = [
            {"index": 1, "text": "a" * 2200},
            {"index": 2, "text": "b" * 2200},
        ]
        with self.batch_environment() as root:
            source = root / "resume.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            job = self.create_transform_job(source, chunk_tokens=500)
            chunks = agent.split_batch_content(
                source.read_text(),
                "json",
                500,
            )
            analysis = agent.analyze_input_file(source)
            jobs = agent.load_batch_jobs()
            jobs[job["id"]]["checkpoint_plan_id"] = (
                agent.batch_checkpoint_plan_id(
                    source.read_text(),
                    job["instruction"],
                    "json",
                    500,
                    analysis,
                )
            )
            agent.save_batch_jobs(jobs)
            agent.batch_checkpoint_path(job["id"], 1).write_text(
                chunks[0] + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                agent,
                "load_config",
                return_value={"MODEL": "test", "PORT": 8000},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
                side_effect=self.echo_mlx_response,
            ) as urlopen:
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(
                stored["status"],
                "completed",
                stored.get("error"),
            )
            self.assertEqual(stored["processed_chunks"], 2)
            self.assertEqual(stored["checkpoint_count"], 2)
            self.assertEqual(stored["mlx_calls"], 1)
            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(
                json.loads(Path(stored["output_path"]).read_text()),
                data,
            )

    def test_resume_ignores_checkpoint_from_different_plan(self):
        data = [{"index": 1}, {"index": 2}]
        with self.batch_environment() as root:
            source = root / "stale.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            job = self.create_transform_job(source, chunk_tokens=500)
            jobs = agent.load_batch_jobs()
            jobs[job["id"]]["checkpoint_plan_id"] = "old-plan"
            agent.save_batch_jobs(jobs)
            agent.batch_checkpoint_path(job["id"], 1).write_text(
                '[{"index": "stale"}]\n',
                encoding="utf-8",
            )

            with mock.patch.object(
                agent,
                "load_config",
                return_value={"MODEL": "test", "PORT": 8000},
            ), mock.patch.object(
                agent.urllib.request,
                "urlopen",
                side_effect=self.echo_mlx_response,
            ) as urlopen:
                agent.run_batch_transform_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]
            self.assertEqual(
                stored["status"],
                "completed",
                stored.get("error"),
            )
            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(
                json.loads(Path(stored["output_path"]).read_text()),
                data,
            )

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
        with self.batch_environment() as root:
            source = root / "sample.txt"
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

    def test_file_analysis_tree_reduction_counts_and_order(self):
        cases = (
            (1, 0, 0),
            (12, 0, 0),
            (13, 2, 3),
            (24, 2, 3),
            (25, 2, 4),
            (1000, 3, 92),
        )

        for map_count, expected_depth, expected_reduce_calls in cases:
            with self.subTest(map_count=map_count), self.batch_environment() as root:
                source = root / "sample.txt"
                source.write_text("synthetic input\n", encoding="utf-8")
                chunks = [
                    f"chunk-{index:04d}"
                    for index in range(map_count)
                ]
                expected_total_calls = (
                    map_count + expected_reduce_calls + 1
                )
                calls = []
                final_prompts = []

                def fake_llm(prompt, max_tokens=800):
                    calls.append((prompt, max_tokens))

                    if len(calls) > expected_total_calls:
                        raise RuntimeError("Synthetic runaway call guard")

                    if max_tokens == 500:
                        chunk = prompt.split("EXCERPT:\n", 1)[1]
                        index = int(chunk.removeprefix("chunk-"))
                        return f"<{index}>"

                    if max_tokens == 900:
                        return prompt.split("\n", 1)[1]

                    if max_tokens == 1200:
                        final_prompts.append(prompt)
                        return "final synthesis"

                    self.fail(f"Unexpected max_tokens: {max_tokens}")

                job = agent.create_file_analysis_job(
                    source,
                    "Summarize the synthetic file.",
                    "text",
                    2000,
                    "summarize",
                )

                with mock.patch.object(
                    agent,
                    "analyze_file_structure",
                    return_value={"detected_type": "text"},
                ), mock.patch.object(
                    agent,
                    "split_batch_content",
                    return_value=chunks,
                ), mock.patch.object(
                    agent,
                    "local_file_llm",
                    side_effect=fake_llm,
                ):
                    agent.run_file_analysis_job(job["id"])

                stored = agent.load_batch_jobs()[job["id"]]
                map_calls = [call for call in calls if call[1] == 500]
                reduce_calls = [call for call in calls if call[1] == 900]
                final_calls = [call for call in calls if call[1] == 1200]

                self.assertEqual(stored["status"], "completed")
                self.assertEqual(stored["result"], "final synthesis")
                self.assertEqual(stored["processed_chunks"], map_count)
                self.assertEqual(stored["total_chunks"], map_count)
                self.assertEqual(len(map_calls), map_count)
                self.assertEqual(len(reduce_calls), expected_reduce_calls)
                self.assertEqual(len(final_calls), 1)
                self.assertEqual(len(calls), expected_total_calls)
                self.assertEqual(
                    agent.file_analysis_reduction_limits(map_count),
                    (expected_depth, expected_reduce_calls),
                )

                ordered_results = [
                    int(value)
                    for value in re.findall(r"<(\d+)>", final_prompts[0])
                ]
                self.assertEqual(
                    ordered_results,
                    list(range(map_count)),
                )

    def test_file_analysis_reduction_bound_failure_marks_job_failed(self):
        with self.batch_environment() as root:
            source = root / "sample.txt"
            source.write_text("synthetic input\n", encoding="utf-8")
            chunks = [f"chunk-{index}" for index in range(13)]
            job = agent.create_file_analysis_job(
                source,
                "Summarize the synthetic file.",
                "text",
                2000,
                "summarize",
            )

            with mock.patch.object(
                agent,
                "analyze_file_structure",
                return_value={"detected_type": "text"},
            ), mock.patch.object(
                agent,
                "split_batch_content",
                return_value=chunks,
            ), mock.patch.object(
                agent,
                "file_analysis_reduction_limits",
                return_value=(0, 0),
            ), mock.patch.object(
                agent,
                "local_file_llm",
                return_value="map result",
            ) as llm:
                agent.run_file_analysis_job(job["id"])

            stored = agent.load_batch_jobs()[job["id"]]

            self.assertEqual(stored["status"], "failed")
            self.assertIn("derived depth limit", stored["error"])
            self.assertEqual(stored["processed_chunks"], 13)
            self.assertEqual(stored["total_chunks"], 13)
            self.assertEqual(llm.call_count, 13)

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




    def test_batch_checkpoint_atomic_write_cleans_temp_on_replace_failure(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "00000001.txt"
            temporary = checkpoint.with_suffix(
                checkpoint.suffix + ".tmp"
            )

            original_replace = Path.replace

            def failing_replace(source, destination):
                source = Path(source)
                destination = Path(destination)

                if destination == checkpoint:
                    self.assertTrue(
                        source.exists(),
                        "checkpoint temp file must exist before replace",
                    )
                    raise OSError(
                        "simulated checkpoint replace failure"
                    )

                return original_replace(
                    source,
                    destination,
                )

            with mock.patch.object(
                Path,
                "replace",
                failing_replace,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated checkpoint replace failure",
                ):
                    agent.atomic_write_text(
                        checkpoint,
                        "checkpoint",
                        encoding="utf-8",
                    )

            self.assertFalse(
                temporary.exists(),
                "failed checkpoint write must remove temp file",
            )

            self.assertFalse(
                checkpoint.exists(),
            )


if __name__ == "__main__":
    unittest.main()
