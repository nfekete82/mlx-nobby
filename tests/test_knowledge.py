import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import knowledge


class KnowledgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.old_root = knowledge.ROOT
        self.old_db = knowledge.DB

        knowledge.ROOT = self.root / "knowledge"
        knowledge.DB = knowledge.ROOT / "knowledge.db"

    def tearDown(self):
        knowledge.ROOT = self.old_root
        knowledge.DB = self.old_db
        self.temp_dir.cleanup()


class KnowledgeHelperTests(KnowledgeTestCase):
    def test_hash_is_stable_sha256(self):
        value = knowledge._hash("hello")

        self.assertEqual(len(value), 64)
        self.assertEqual(value, knowledge._hash("hello"))
        self.assertNotEqual(value, knowledge._hash("world"))

    def test_language_detection(self):
        self.assertEqual(
            knowledge._language(Path("example.py")),
            "python",
        )
        self.assertEqual(
            knowledge._language(Path("example.php")),
            "php",
        )
        self.assertEqual(
            knowledge._language(Path("example.js")),
            "javascript",
        )
        self.assertEqual(
            knowledge._language(Path("example.ts")),
            "typescript",
        )
        self.assertEqual(
            knowledge._language(Path("README.md")),
            "markdown",
        )
        self.assertEqual(
            knowledge._language(Path("example.txt")),
            "text",
        )

    def test_allowed_accepts_text_files(self):
        self.assertTrue(
            knowledge._allowed(Path("example.py"))
        )
        self.assertTrue(
            knowledge._allowed(Path("README.md"))
        )
        self.assertTrue(
            knowledge._allowed(Path("data.json"))
        )

    def test_allowed_rejects_sensitive_and_binary_files(self):
        self.assertFalse(
            knowledge._allowed(Path(".env"))
        )
        self.assertFalse(
            knowledge._allowed(Path("id_rsa"))
        )
        self.assertFalse(
            knowledge._allowed(Path("private.key"))
        )
        self.assertFalse(
            knowledge._allowed(Path("certificate.pem"))
        )
        self.assertFalse(
            knowledge._allowed(Path("credentials.json"))
        )
        self.assertFalse(
            knowledge._allowed(Path("secrets.txt"))
        )
        self.assertFalse(
            knowledge._allowed(Path("image.png"))
        )

    def test_chunks_returns_small_document_as_single_chunk(self):
        chunks = knowledge._chunks(
            "def hello():\n    return 'world'\n",
            "python",
        )

        self.assertEqual(len(chunks), 1)

        body, start, end, symbol, symbol_type = chunks[0]

        self.assertIn("def hello()", body)
        self.assertEqual(start, 1)
        self.assertEqual(end, 2)
        self.assertEqual(symbol, "hello")
        self.assertEqual(symbol_type, "symbol")

    def test_chunks_splits_large_document(self):
        text = "\n".join(
            f"line {index} " + ("x" * 80)
            for index in range(100)
        )

        chunks = knowledge._chunks(text, "text")

        self.assertGreater(len(chunks), 1)

        for body, start, end, _, _ in chunks:
            self.assertTrue(body)
            self.assertGreaterEqual(start, 1)
            self.assertGreaterEqual(end, start)

    def test_document_text_chunks_empty(self):
        self.assertEqual(
            knowledge._document_text_chunks(""),
            [],
        )

    def test_document_text_chunks_small(self):
        self.assertEqual(
            knowledge._document_text_chunks("hello"),
            ["hello"],
        )

    def test_document_text_chunks_large_with_overlap(self):
        text = (
            ("A" * 900)
            + ". "
            + ("B" * 900)
            + ". "
            + ("C" * 900)
        )

        chunks = knowledge._document_text_chunks(
            text,
            target_chars=1000,
            overlap_chars=100,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunks))

    def test_fts_query(self):
        self.assertEqual(
            knowledge._fts_query("hello world"),
            '"hello" OR "world"',
        )
        self.assertEqual(
            knowledge._fts_query("a x"),
            "",
        )
        self.assertEqual(
            knowledge._fts_query(None),
            "",
        )

    def test_pack_unpack_round_trip(self):
        vector = [0.25, -0.5, 1.0]

        packed = knowledge._pack(vector)
        unpacked = knowledge._unpack(packed)

        self.assertEqual(len(unpacked), len(vector))

        for expected, actual in zip(vector, unpacked):
            self.assertAlmostEqual(expected, actual)


class KnowledgeDatabaseTests(KnowledgeTestCase):
    def test_db_creates_schema(self):
        con = knowledge._db()

        names = {
            row[0]
            for row in con.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                """
            )
        }

        con.close()

        self.assertIn("knowledge_sources", names)
        self.assertIn("knowledge_documents", names)
        self.assertIn("knowledge_chunks", names)
        self.assertIn("knowledge_embeddings", names)
        self.assertIn("knowledge_fts", names)

    @patch(
        "agent.knowledge.embedding_health",
        return_value=None,
    )
    def test_index_source_fts_fallback(self, _health):
        source = self.root / "source"
        source.mkdir()

        (source / "example.py").write_text(
            "def hello():\n"
            "    return 'world'\n",
            encoding="utf-8",
        )

        result = knowledge.index_source(
            source,
            name="Example",
        )

        self.assertEqual(result["name"], "Example")
        self.assertEqual(result["mode"], "fts_fallback")
        self.assertGreater(result["indexed"], 0)
        self.assertEqual(result["skipped"], 0)

        state = knowledge.status()

        self.assertEqual(state["documents"], 1)
        self.assertGreater(state["chunks"], 0)
        self.assertEqual(len(state["sources"]), 1)

    @patch(
        "agent.knowledge.embedding_health",
        return_value=None,
    )
    def test_index_source_skips_unchanged_file(self, _health):
        source = self.root / "source"
        source.mkdir()

        (source / "example.txt").write_text(
            "hello world",
            encoding="utf-8",
        )

        first = knowledge.index_source(source)
        second = knowledge.index_source(source)

        self.assertGreater(first["indexed"], 0)
        self.assertEqual(second["indexed"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_index_source_rejects_missing_directory(self):
        with self.assertRaises(ValueError):
            knowledge.index_source(
                self.root / "does-not-exist"
            )

    @patch(
        "agent.knowledge.embedding_health",
        return_value=None,
    )
    def test_source_lifecycle(self, _health):
        source = self.root / "source"
        source.mkdir()

        (source / "example.txt").write_text(
            "hello knowledge",
            encoding="utf-8",
        )

        indexed = knowledge.index_source(
            source,
            name="Lifecycle",
        )

        source_id = indexed["source_id"]

        stored = knowledge.get_source(source_id)

        self.assertEqual(stored["name"], "Lifecycle")
        self.assertEqual(stored["enabled"], 1)

        disabled = knowledge.set_source_enabled(
            source_id,
            False,
        )

        self.assertEqual(disabled["enabled"], 0)
        self.assertEqual(
            knowledge.get_source(source_id)["enabled"],
            0,
        )

        deleted = knowledge.delete_source(source_id)

        self.assertTrue(deleted["deleted"])
        self.assertEqual(
            deleted["source_id"],
            source_id,
        )

        with self.assertRaises(ValueError):
            knowledge.get_source(source_id)

    def test_get_source_rejects_empty_id(self):
        with self.assertRaises(ValueError):
            knowledge.get_source("")


class UploadedDocumentKnowledgeTests(KnowledgeTestCase):
    @staticmethod
    def _health():
        return {
            "ok": True,
            "model": "test-embedding",
            "dimensions": 3,
        }

    @staticmethod
    def _fake_request(path, payload=None):
        if path == "/embeddings":
            return {
                "vectors": [
                    [1.0, 0.0, 0.0]
                    for _ in payload["texts"]
                ]
            }

        if path == "/embedding":
            return {
                "vectors": [
                    [1.0, 0.0, 0.0]
                ]
            }

        raise AssertionError(
            f"unexpected embedding request: {path}"
        )

    def test_index_uploaded_document_validates_arguments(self):
        with self.assertRaises(ValueError):
            knowledge.index_uploaded_document(
                "",
                "Example.pdf",
                [],
            )

        with self.assertRaises(ValueError):
            knowledge.index_uploaded_document(
                "doc-1",
                "",
                [],
            )

        with self.assertRaises(ValueError):
            knowledge.index_uploaded_document(
                "doc-1",
                "Example.pdf",
                "not-a-list",
            )

    @patch(
        "agent.knowledge.embedding_health",
        return_value=None,
    )
    def test_index_uploaded_document_requires_embeddings(
        self,
        _health,
    ):
        with self.assertRaises(RuntimeError):
            knowledge.index_uploaded_document(
                "doc-1",
                "Example.pdf",
                [
                    {
                        "page": 1,
                        "text": "hello",
                    }
                ],
            )

    @patch(
        "agent.knowledge.embedding_health",
    )
    @patch(
        "agent.knowledge._request",
    )
    def test_index_uploaded_document_and_page_round_trip(
        self,
        request,
        health,
    ):
        health.return_value = self._health()
        request.side_effect = self._fake_request

        progress = []

        result = knowledge.index_uploaded_document(
            "doc-1",
            "Example.pdf",
            [
                {
                    "page": 1,
                    "text": "Alpha knowledge text.",
                },
                {
                    "page": 2,
                    "text": "Beta knowledge text.",
                },
            ],
            progress_callback=lambda done, total: progress.append(
                (done, total)
            ),
        )

        self.assertEqual(result["document_id"], "doc-1")
        self.assertEqual(result["name"], "Example.pdf")
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["chunks"], 2)
        self.assertEqual(result["model"], "test-embedding")
        self.assertEqual(result["dimensions"], 3)

        self.assertEqual(progress[0], (0, 2))
        self.assertEqual(progress[-1], (2, 2))

        page = knowledge.get_uploaded_document_page(
            "doc-1",
            2,
        )

        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_count"], 2)
        self.assertEqual(page["chunks"], 1)
        self.assertEqual(
            page["text"],
            "Beta knowledge text.",
        )

    @patch(
        "agent.knowledge.embedding_health",
    )
    @patch(
        "agent.knowledge._request",
    )
    def test_index_uploaded_document_reuses_cache(
        self,
        request,
        health,
    ):
        health.return_value = self._health()
        request.side_effect = self._fake_request

        pages = [
            {
                "page": 1,
                "text": "Cached document.",
            }
        ]

        first = knowledge.index_uploaded_document(
            "cached-doc",
            "Cached.pdf",
            pages,
        )

        request.reset_mock()

        second = knowledge.index_uploaded_document(
            "cached-doc",
            "Cached.pdf",
            pages,
        )

        self.assertNotIn("cached", first)
        self.assertTrue(second["cached"])
        self.assertEqual(second["chunks"], 1)

        request.assert_not_called()

    @patch(
        "agent.knowledge.embedding_health",
    )
    @patch(
        "agent.knowledge._request",
    )
    def test_search_uploaded_document_ranks_vectors(
        self,
        request,
        health,
    ):
        health.return_value = self._health()

        def fake_request(path, payload=None):
            if path == "/embeddings":
                vectors = []

                for text in payload["texts"]:
                    if "Alpha" in text:
                        vectors.append(
                            [1.0, 0.0, 0.0]
                        )
                    else:
                        vectors.append(
                            [0.0, 1.0, 0.0]
                        )

                return {"vectors": vectors}

            if path == "/embedding":
                return {
                    "vectors": [
                        [1.0, 0.0, 0.0]
                    ]
                }

            raise AssertionError(path)

        request.side_effect = fake_request

        knowledge.index_uploaded_document(
            "search-doc",
            "Search.pdf",
            [
                {
                    "page": 1,
                    "text": "Alpha relevant material.",
                },
                {
                    "page": 2,
                    "text": "Beta unrelated material.",
                },
            ],
        )

        result = knowledge.search_uploaded_document(
            "search-doc",
            "Alpha",
            limit=2,
        )

        self.assertEqual(
            result["document_id"],
            "search-doc",
        )
        self.assertEqual(result["query"], "Alpha")
        self.assertEqual(len(result["results"]), 2)

        self.assertEqual(
            result["results"][0]["page"],
            1,
        )
        self.assertGreater(
            result["results"][0]["score"],
            result["results"][1]["score"],
        )

    def test_uploaded_document_page_validation(self):
        with self.assertRaises(ValueError):
            knowledge.get_uploaded_document_page(
                "",
                1,
            )

        with self.assertRaises(ValueError):
            knowledge.get_uploaded_document_page(
                "doc",
                "invalid",
            )

        with self.assertRaises(ValueError):
            knowledge.get_uploaded_document_page(
                "doc",
                0,
            )

        with self.assertRaises(ValueError):
            knowledge.get_uploaded_document_page(
                "missing",
                1,
            )

    def test_uploaded_document_search_validation(self):
        with self.assertRaises(ValueError):
            knowledge.search_uploaded_document(
                "",
                "query",
            )

        with self.assertRaises(ValueError):
            knowledge.search_uploaded_document(
                "doc",
                "",
            )


if __name__ == "__main__":
    unittest.main()


class KnowledgeSearchTests(KnowledgeTestCase):
    def _seed_search_data(self):
        con = knowledge._db()

        con.execute(
            """
            INSERT INTO knowledge_sources
                (source_id, name, root_path, enabled)
            VALUES (?, ?, ?, ?)
            """,
            ("source-1", "Alpha Workspace", "/tmp/alpha", 1),
        )

        con.execute(
            """
            INSERT INTO knowledge_sources
                (source_id, name, root_path, enabled)
            VALUES (?, ?, ?, ?)
            """,
            ("source-2", "Beta Workspace", "/tmp/beta", 1),
        )

        con.execute(
            """
            INSERT INTO knowledge_documents
                (
                    document_id,
                    source_id,
                    relative_path,
                    absolute_path,
                    content_hash
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "doc-1",
                "source-1",
                "alpha.py",
                "/tmp/alpha/alpha.py",
                "hash-alpha",
            ),
        )

        con.execute(
            """
            INSERT INTO knowledge_documents
                (
                    document_id,
                    source_id,
                    relative_path,
                    absolute_path,
                    content_hash
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "doc-2",
                "source-2",
                "beta.py",
                "/tmp/beta/beta.py",
                "hash-beta",
            ),
        )

        con.execute(
            """
            INSERT INTO knowledge_chunks
                (
                    chunk_id,
                    document_id,
                    content,
                    start_line,
                    end_line,
                    symbol
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk-1",
                "doc-1",
                "alpha search target",
                1,
                3,
                "alpha_function",
            ),
        )

        con.execute(
            """
            INSERT INTO knowledge_chunks
                (
                    chunk_id,
                    document_id,
                    content,
                    start_line,
                    end_line,
                    symbol
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk-2",
                "doc-2",
                "beta search target",
                10,
                12,
                "beta_function",
            ),
        )

        try:
            con.execute(
                """
                INSERT INTO knowledge_fts(chunk_id, content)
                VALUES (?, ?)
                """,
                ("chunk-1", "alpha search target"),
            )
            con.execute(
                """
                INSERT INTO knowledge_fts(chunk_id, content)
                VALUES (?, ?)
                """,
                ("chunk-2", "beta search target"),
            )
        except Exception:
            pass

        con.commit()
        con.close()

    @patch("agent.knowledge.embedding_health", return_value=None)
    def test_search_fts_fallback(self, _health):
        self._seed_search_data()

        result = knowledge.search("alpha", limit=5)

        self.assertEqual(result["mode"], "fts_fallback")
        self.assertEqual(result["query"], "alpha")
        self.assertIsNone(result["scope"])
        self.assertLessEqual(len(result["results"]), 5)

        if result["results"]:
            first = result["results"][0]
            self.assertEqual(first["source"], "Alpha Workspace")
            self.assertEqual(first["path"], "alpha.py")
            self.assertEqual(first["symbol"], "alpha_function")
            self.assertIsNone(first["similarity"])

    @patch("agent.knowledge.embedding_health", return_value=None)
    def test_search_scope_filters_fts_results(self, _health):
        self._seed_search_data()

        result = knowledge.search(
            "search",
            scope="Alpha",
            limit=10,
        )

        self.assertEqual(result["mode"], "fts_fallback")

        for item in result["results"]:
            self.assertEqual(item["source"], "Alpha Workspace")

    @patch("agent.knowledge.embedding_health", return_value={"ok": True})
    @patch("agent.knowledge._request")
    def test_search_vector_mode(self, request_mock, _health):
        self._seed_search_data()

        con = knowledge._db()
        con.execute(
            """
            INSERT INTO knowledge_embeddings(chunk_id, vector)
            VALUES (?, ?)
            """,
            ("chunk-1", knowledge._pack([1.0, 0.0])),
        )
        con.execute(
            """
            INSERT INTO knowledge_embeddings(chunk_id, vector)
            VALUES (?, ?)
            """,
            ("chunk-2", knowledge._pack([0.0, 1.0])),
        )
        con.commit()
        con.close()

        request_mock.return_value = {
            "vectors": [[1.0, 0.0]]
        }

        result = knowledge.search(
            "term-that-does-not-exist",
            limit=10,
        )

        self.assertEqual(result["mode"], "vector")
        self.assertGreaterEqual(len(result["results"]), 2)
        self.assertEqual(
            result["results"][0]["source"],
            "Alpha Workspace",
        )
        self.assertAlmostEqual(
            result["results"][0]["similarity"],
            1.0,
        )

    @patch("agent.knowledge.embedding_health", return_value={"ok": True})
    @patch("agent.knowledge._request")
    def test_search_hybrid_mode(self, request_mock, _health):
        self._seed_search_data()

        con = knowledge._db()
        con.execute(
            """
            INSERT INTO knowledge_embeddings(chunk_id, vector)
            VALUES (?, ?)
            """,
            ("chunk-1", knowledge._pack([1.0, 0.0])),
        )
        con.execute(
            """
            INSERT INTO knowledge_embeddings(chunk_id, vector)
            VALUES (?, ?)
            """,
            ("chunk-2", knowledge._pack([0.0, 1.0])),
        )
        con.commit()
        con.close()

        request_mock.return_value = {
            "vectors": [[1.0, 0.0]]
        }

        result = knowledge.search("alpha", limit=10)

        self.assertIn(
            result["mode"],
            {"hybrid", "vector"},
        )
        self.assertTrue(result["results"])

        first = result["results"][0]
        self.assertEqual(first["source"], "Alpha Workspace")
        self.assertAlmostEqual(first["similarity"], 1.0)

    @patch("agent.knowledge.embedding_health", return_value={"ok": True})
    @patch(
        "agent.knowledge._request",
        side_effect=RuntimeError("embedding failure"),
    )
    def test_search_embedding_failure_falls_back_to_fts(
        self,
        _request_mock,
        _health,
    ):
        self._seed_search_data()

        result = knowledge.search("alpha", limit=10)

        self.assertEqual(result["mode"], "fts_fallback")
        self.assertTrue(result["results"])
        self.assertEqual(
            result["results"][0]["source"],
            "Alpha Workspace",
        )

    @patch("agent.knowledge.embedding_health", return_value=None)
    def test_search_respects_limit(self, _health):
        self._seed_search_data()

        result = knowledge.search("search", limit=1)

        self.assertLessEqual(len(result["results"]), 1)


class KnowledgeRemainingBranchTests(KnowledgeTestCase):
    def test_embedding_health_success_and_failure(self):
        with patch.object(
            knowledge,
            "_request",
            return_value={"ok": True, "model": "test"},
        ):
            result = knowledge.embedding_health()

        self.assertEqual(result["model"], "test")

        with patch.object(
            knowledge,
            "_request",
            return_value={"ok": False},
        ):
            self.assertIsNone(knowledge.embedding_health())

        with patch.object(
            knowledge,
            "_request",
            side_effect=ValueError("invalid response"),
        ):
            self.assertIsNone(knowledge.embedding_health())

    def test_index_uploaded_document_skips_invalid_pages(self):
        pages = [
            None,
            "invalid",
            {"page": "invalid", "text": "ignored"},
            {"page": 1, "text": ""},
            {"page": 2, "text": "valid page text"},
        ]

        with patch.object(
            knowledge,
            "embedding_health",
            return_value={"ok": True, "model": "test", "dimensions": 2},
        ), patch.object(
            knowledge,
            "_request",
            return_value={"vectors": [[1.0, 0.0]]},
        ):
            result = knowledge.index_uploaded_document(
                "invalid-pages-document",
                "fixture.txt",
                pages,
                document_type="text",
            )

        self.assertEqual(result["document_id"], "invalid-pages-document")

        page = knowledge.get_uploaded_document_page(
            "invalid-pages-document",
            2,
        )

        self.assertIn("valid page text", page["text"])

    def test_uploaded_document_page_out_of_range(self):
        with patch.object(
            knowledge,
            "embedding_health",
            return_value={"ok": True, "model": "test", "dimensions": 2},
        ), patch.object(
            knowledge,
            "_request",
            return_value={"vectors": [[1.0, 0.0]]},
        ):
            knowledge.index_uploaded_document(
                "page-range-document",
                "fixture.txt",
                [{"page": 1, "text": "page one"}],
                document_type="text",
            )

        with self.assertRaises(ValueError):
            knowledge.get_uploaded_document_page(
                "page-range-document",
                2,
            )

    def test_uploaded_document_page_without_chunks(self):
        with patch.object(
            knowledge,
            "embedding_health",
            return_value={"ok": True, "model": "test", "dimensions": 2},
        ), patch.object(
            knowledge,
            "_request",
            return_value={"vectors": [[1.0, 0.0]]},
        ):
            knowledge.index_uploaded_document(
                "empty-page-document",
                "fixture.txt",
                [{"page": 1, "text": "temporary text"}],
                document_type="text",
            )

        con = knowledge._db()
        con.execute(
            """
            DELETE FROM uploaded_document_chunks
            WHERE document_id=?
            """,
            ("empty-page-document",),
        )
        con.commit()
        con.close()

        result = knowledge.get_uploaded_document_page(
            "empty-page-document",
            1,
        )

        self.assertEqual(result["document_id"], "empty-page-document")
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["text"], "")

    def test_uploaded_document_page_reconstructs_overlap(self):
        text = (
            ("A" * 1000)
            + ("B" * 500)
            + ("C" * 1000)
        )

        chunks = knowledge._document_text_chunks(text)

        self.assertGreaterEqual(len(chunks), 2)

        vectors = [
            [1.0, 0.0]
            for _ in chunks
        ]

        with patch.object(
            knowledge,
            "embedding_health",
            return_value={"ok": True, "model": "test", "dimensions": 2},
        ), patch.object(
            knowledge,
            "_request",
            return_value={"vectors": vectors},
        ):
            knowledge.index_uploaded_document(
                "overlap-document",
                "fixture.txt",
                [{"page": 1, "text": text}],
                document_type="text",
            )

        result = knowledge.get_uploaded_document_page(
            "overlap-document",
            1,
        )

        self.assertEqual(result["text"], text)

    def test_reindex_source_preserves_disabled_state(self):
        source_root = self.root / "source"
        source_root.mkdir()
        (source_root / "example.txt").write_text(
            "hello knowledge",
            encoding="utf-8",
        )

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            created = knowledge.index_source(
                source_root,
                "Reindex fixture",
            )

        source_id = created["source_id"]

        knowledge.set_source_enabled(
            source_id,
            False,
        )

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            result = knowledge.reindex_source(source_id)

        self.assertEqual(result["source_id"], source_id)

        source = knowledge.get_source(source_id)

        self.assertEqual(source["enabled"], 0)

    def test_request_builds_post_and_decodes_json(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"vectors":[[1.0,2.0]]}'

        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["req"] = req
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.object(
            knowledge.urllib.request,
            "urlopen",
            side_effect=fake_urlopen,
        ):
            result = knowledge._request(
                "/embeddings",
                {"texts": ["hello"]},
            )

        self.assertEqual(result, {"vectors": [[1.0, 2.0]]})
        self.assertEqual(captured["timeout"], 20)
        self.assertEqual(
            captured["req"].get_method(),
            "POST",
        )
        self.assertEqual(
            captured["req"].full_url,
            knowledge.EMBEDDINGS_URL + "/embeddings",
        )
        self.assertIsNotNone(captured["req"].data)

    def test_index_source_skips_unreadable_file(self):
        source = self.root / "unreadable"
        source.mkdir()

        good = source / "good.txt"
        bad = source / "bad.txt"

        good.write_text("good content", encoding="utf-8")
        bad.write_text("bad content", encoding="utf-8")

        original = Path.read_text

        def fake_read_text(path, *args, **kwargs):
            if path.name == "bad.txt":
                raise OSError("fixture read failure")
            return original(path, *args, **kwargs)

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ), patch.object(
            Path,
            "read_text",
            fake_read_text,
        ):
            result = knowledge.index_source(source)

        self.assertEqual(result["indexed"], 1)

    def test_index_source_removes_deleted_document(self):
        source = self.root / "stale"
        source.mkdir()

        path = source / "remove-me.txt"
        path.write_text("temporary knowledge", encoding="utf-8")

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            first = knowledge.index_source(source)

        source_id = first["source_id"]

        con = knowledge._db()
        before = con.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_documents
            WHERE source_id=?
            """,
            (source_id,),
        ).fetchone()[0]
        con.close()

        self.assertEqual(before, 1)

        path.unlink()

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            knowledge.index_source(source)

        con = knowledge._db()
        after = con.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_documents
            WHERE source_id=?
            """,
            (source_id,),
        ).fetchone()[0]
        con.close()

        self.assertEqual(after, 0)

    def test_index_source_persists_embeddings(self):
        source = self.root / "embedded"
        source.mkdir()

        (source / "example.txt").write_text(
            "knowledge embedding fixture",
            encoding="utf-8",
        )

        def fake_request(path, payload=None):
            self.assertEqual(path, "/embeddings")
            texts = payload["texts"]
            return {
                "vectors": [
                    [float(i + 1), 0.5]
                    for i, _ in enumerate(texts)
                ]
            }

        with patch.object(
            knowledge,
            "embedding_health",
            return_value={
                "ok": True,
                "model": "fixture-model",
                "dimensions": 2,
            },
        ), patch.object(
            knowledge,
            "_request",
            side_effect=fake_request,
        ):
            result = knowledge.index_source(source)

        self.assertEqual(result["mode"], "hybrid")

        con = knowledge._db()
        rows = con.execute(
            "SELECT model,dimensions FROM knowledge_embeddings"
        ).fetchall()
        con.close()

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "fixture-model")
        self.assertEqual(rows[0]["dimensions"], 2)

    def test_search_handles_fts_operational_error(self):
        source = self.root / "fts-error"
        source.mkdir()
        (source / "fixture.txt").write_text(
            "fixture searchable knowledge",
            encoding="utf-8",
        )

        with patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            knowledge.index_source(source)

        real_db = knowledge._db

        class ConnectionProxy:
            def __init__(self, con):
                self._con = con

            def execute(self, sql, params=()):
                if "knowledge_fts MATCH" in sql:
                    raise knowledge.sqlite3.OperationalError(
                        "fixture FTS failure"
                    )
                return self._con.execute(sql, params)

            def close(self):
                return self._con.close()

            def __getattr__(self, name):
                return getattr(self._con, name)

        con = real_db()

        with patch.object(
            knowledge,
            "_db",
            return_value=ConnectionProxy(con),
        ), patch.object(
            knowledge,
            "embedding_health",
            return_value=None,
        ):
            result = knowledge.search("fixture")

        self.assertEqual(result["mode"], "fts_fallback")
        self.assertEqual(result["results"], [])

    def test_uploaded_document_page_ignores_empty_chunk(self):
        with patch.object(
            knowledge,
            "embedding_health",
            return_value={
                "ok": True,
                "model": "fixture",
                "dimensions": 2,
            },
        ), patch.object(
            knowledge,
            "_request",
            return_value={"vectors": [[1.0, 0.0]]},
        ):
            knowledge.index_uploaded_document(
                "empty-chunk-document",
                "fixture.txt",
                [{"page": 1, "text": "visible content"}],
                document_type="text",
            )

        con = knowledge._db()

        row = con.execute(
            """
            SELECT *
            FROM uploaded_document_chunks
            WHERE document_id=?
            LIMIT 1
            """,
            ("empty-chunk-document",),
        ).fetchone()

        self.assertIsNotNone(row)

        columns = [
            item[1]
            for item in con.execute(
                "PRAGMA table_info(uploaded_document_chunks)"
            ).fetchall()
        ]

        values = dict(row)
        values["chunk_id"] = "empty-fixture-chunk"
        values["chunk_index"] = int(values["chunk_index"]) + 100
        values["content"] = ""

        insert_columns = [
            column
            for column in columns
            if column in values
        ]

        placeholders = ",".join(
            "?" for _ in insert_columns
        )

        con.execute(
            f"""
            INSERT INTO uploaded_document_chunks
            ({",".join(insert_columns)})
            VALUES ({placeholders})
            """,
            tuple(values[column] for column in insert_columns),
        )

        con.commit()
        con.close()

        result = knowledge.get_uploaded_document_page(
            "empty-chunk-document",
            1,
        )

        self.assertEqual(result["text"], "visible content")
