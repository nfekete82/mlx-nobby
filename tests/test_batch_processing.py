import tempfile
import unittest
from pathlib import Path

from agent.batch_processing import (
    batch_max_output_tokens,
    build_json_freetext_batches,
    decode_batch_bytes,
    estimate_batch_tokens,
    is_metal_oom_error,
    recommended_batch_chunk_tokens,
    split_batch_part_for_oom,
    split_chunk_hard,
    write_batch_text,
)


class BatchProcessingUnitTests(unittest.TestCase):

    def test_estimate_batch_tokens(self):
        self.assertEqual(estimate_batch_tokens(""), 0)
        self.assertEqual(estimate_batch_tokens("a"), 1)
        self.assertEqual(estimate_batch_tokens("abcd"), 1)
        self.assertEqual(estimate_batch_tokens("abcde"), 2)

    def test_recommended_batch_chunk_tokens(self):
        self.assertEqual(
            recommended_batch_chunk_tokens(0),
            2000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(1000),
            2000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(2000),
            2000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(12000),
            12000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(12001),
            12000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(64000),
            12000,
        )
        self.assertEqual(
            recommended_batch_chunk_tokens(64001),
            8000,
        )

    def test_batch_max_output_tokens(self):
        self.assertEqual(
            batch_max_output_tokens(1),
            384,
        )
        self.assertEqual(
            batch_max_output_tokens(100),
            391,
        )
        self.assertEqual(
            batch_max_output_tokens(100000),
            16000,
        )

    def test_decode_batch_bytes_utf8(self):
        raw = "hello äöü".encode("utf-8")
        self.assertEqual(
            decode_batch_bytes(raw, "utf-8"),
            "hello äöü",
        )

    def test_decode_batch_bytes_utf8_sig(self):
        raw = b"\xef\xbb\xbf" + "hello ä".encode("utf-8")
        self.assertEqual(
            decode_batch_bytes(raw, "utf-8-sig"),
            "hello ä",
        )

    def test_decode_batch_bytes_utf16_le(self):
        raw = b"\xff\xfe" + "hello ä".encode("utf-16-le")
        self.assertEqual(
            decode_batch_bytes(raw, "utf-16-le"),
            "hello ä",
        )

    def test_decode_batch_bytes_utf16_be(self):
        raw = b"\xfe\xff" + "hello ä".encode("utf-16-be")
        self.assertEqual(
            decode_batch_bytes(raw, "utf-16-be"),
            "hello ä",
        )

    def test_decode_batch_bytes_replacement_mode(self):
        self.assertEqual(
            decode_batch_bytes(
                b"abc\xffdef",
                "utf-8",
                errors="replace",
            ),
            "abc\ufffddef",
        )

    def test_write_batch_text_roundtrip(self):
        text = "Hello äöü 世界"

        cases = (
            ("utf-8", b""),
            ("utf-8-sig", b"\xef\xbb\xbf"),
            ("utf-16-le", b"\xff\xfe"),
            ("utf-16-be", b"\xfe\xff"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.txt"

            for encoding, bom in cases:
                with self.subTest(encoding=encoding):
                    write_batch_text(
                        path,
                        text,
                        encoding,
                    )

                    raw = path.read_bytes()

                    if bom:
                        self.assertTrue(
                            raw.startswith(bom)
                        )

                    decoded = decode_batch_bytes(
                        raw,
                        encoding,
                    )

                    self.assertEqual(
                        decoded,
                        text,
                    )

    def test_split_chunk_hard_below_limit(self):
        text = "hello world"

        self.assertEqual(
            split_chunk_hard(
                text,
                max_tokens=100,
            ),
            [text],
        )

    def test_split_chunk_hard_preserves_content(self):
        text = "abcdefghij" * 200

        parts = split_chunk_hard(
            text,
            max_tokens=125,
        )

        self.assertGreater(
            len(parts),
            1,
        )

        self.assertEqual(
            "".join(parts),
            text,
        )

        self.assertTrue(
            all(len(part) <= 500 for part in parts)
        )

    def test_split_chunk_hard_prefers_newline(self):
        first = "a" * 300 + "\n"
        second = "b" * 300
        text = first + second

        parts = split_chunk_hard(
            text,
            max_tokens=125,
        )

        self.assertGreaterEqual(
            len(parts),
            2,
        )

        self.assertEqual(
            parts[0],
            first,
        )

        self.assertEqual(
            "".join(parts),
            text,
        )

    def test_split_chunk_hard_enforces_minimum_limit(self):
        text = "x" * 900

        parts = split_chunk_hard(
            text,
            max_tokens=10,
        )

        self.assertEqual(
            "".join(parts),
            text,
        )

        self.assertTrue(
            all(len(part) <= 400 for part in parts)
        )

    def test_build_json_freetext_batches_empty(self):
        self.assertEqual(
            build_json_freetext_batches([]),
            [],
        )

    def test_build_json_freetext_batches_max_items(self):
        targets = [
            {
                "id": index,
                "text": "hello",
            }
            for index in range(30)
        ]

        batches = build_json_freetext_batches(
            targets,
            max_items=25,
            max_tokens=10000,
        )

        self.assertEqual(
            [len(batch) for batch in batches],
            [25, 5],
        )

        self.assertEqual(
            [
                item["id"]
                for batch in batches
                for item in batch
            ],
            list(range(30)),
        )

    def test_build_json_freetext_batches_preserves_oversized_target(self):
        target = {
            "id": 1,
            "text": "x" * 20000,
        }

        batches = build_json_freetext_batches(
            [target],
            max_tokens=100,
        )

        self.assertEqual(
            batches,
            [[target]],
        )

    def test_split_batch_part_for_oom_non_json(self):
        text = "abcdefghij" * 200

        parts = split_batch_part_for_oom(
            text,
            "txt",
            125,
        )

        self.assertGreater(
            len(parts),
            1,
        )

        self.assertEqual(
            "".join(parts),
            text,
        )

    def test_split_batch_part_for_oom_json(self):
        text = (
            '{"one":"alpha","two":"beta",'
            '"three":"gamma","four":"delta"}'
        )

        parts = split_batch_part_for_oom(
            text,
            "json",
            10,
        )

        self.assertGreaterEqual(
            len(parts),
            1,
        )

        for part in parts:
            self.assertIsInstance(
                part,
                str,
            )

    def test_is_metal_oom_error(self):
        positives = (
            "metal::malloc failed",
            "Maximum allowed buffer size exceeded",
            "Out of memory",
            "Memory allocation failed",
        )

        for message in positives:
            with self.subTest(message=message):
                self.assertTrue(
                    is_metal_oom_error(message)
                )

        self.assertFalse(
            is_metal_oom_error(
                "ordinary model generation error"
            )
        )


if __name__ == "__main__":
    unittest.main()
