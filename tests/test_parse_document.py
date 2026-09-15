import asyncio
import hashlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile

from backend import app as backend_app


class ParseDocumentTests(unittest.TestCase):
    def run_parse(self, file):
        return asyncio.run(backend_app.parse_document(file))

    @staticmethod
    def upload(filename="test.pdf", content_type="application/pdf"):
        file = MagicMock(spec=UploadFile)
        file.filename = filename
        file.content_type = content_type
        return file

    def test_rejects_non_pdf(self):
        file = self.upload("notes.txt", "text/plain")

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 415)
        self.assertEqual(
            ctx.exception.detail,
            "Aktuell werden nur PDF-Dateien unterstützt",
        )

    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rejects_empty_pdf(self, read_upload):
        read_upload.return_value = b""
        file = self.upload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Leere PDF-Datei")

    @patch.object(backend_app, "MAX_UPLOAD_SIZE_BYTES", 3)
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rejects_oversized_pdf(self, read_upload):
        read_upload.return_value = b"1234"
        file = self.upload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("PDF ist größer als", ctx.exception.detail)

    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rejects_invalid_pdf(self, read_upload, pdf_reader):
        read_upload.return_value = b"broken-pdf"
        pdf_reader.side_effect = ValueError("kaputt")
        file = self.upload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("PDF konnte nicht gelesen werden", ctx.exception.detail)
        self.assertIn("kaputt", ctx.exception.detail)

    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rejects_locked_encrypted_pdf(self, read_upload, pdf_reader):
        read_upload.return_value = b"encrypted"

        reader = MagicMock()
        reader.is_encrypted = True
        reader.decrypt.return_value = 0
        pdf_reader.return_value = reader

        file = self.upload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail,
            "Passwortgeschützte PDFs werden noch nicht unterstützt",
        )
        reader.decrypt.assert_called_once_with("")

    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rejects_encrypted_pdf_when_decrypt_raises(
        self,
        read_upload,
        pdf_reader,
    ):
        read_upload.return_value = b"encrypted"

        reader = MagicMock()
        reader.is_encrypted = True
        reader.decrypt.side_effect = RuntimeError("decrypt failed")
        pdf_reader.return_value = reader

        file = self.upload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_parse(file)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail,
            "Passwortgeschützte PDFs werden noch nicht unterstützt",
        )

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_successful_pdf_and_rag_indexing(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        data = b"valid-pdf"
        read_upload.return_value = data

        page1 = MagicMock()
        page1.extract_text.return_value = "  Erste Seite  "

        page2 = MagicMock()
        page2.extract_text.return_value = "Zweite Seite"

        page3 = MagicMock()
        page3.extract_text.return_value = "   "

        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [page1, page2, page3]
        pdf_reader.return_value = reader

        agent_request.return_value = {
            "status": "ready",
            "chunks": 7,
            "chunks_done": 7,
            "chunks_total": 7,
            "progress": 1.0,
            "model": "embedding-model",
            "dimensions": 768,
            "cached": True,
        }

        file = self.upload("wissen.pdf")
        result = self.run_parse(file)

        expected_id = hashlib.sha256(data).hexdigest()[:32]

        self.assertEqual(result["document_id"], expected_id)
        self.assertEqual(result["name"], "wissen.pdf")
        self.assertEqual(result["kind"], "document")
        self.assertEqual(result["extension"], "pdf")
        self.assertEqual(result["type"], "application/pdf")
        self.assertEqual(result["pages"], 3)

        self.assertEqual(
            result["page_texts"],
            [
                {"page": 1, "text": "Erste Seite"},
                {"page": 2, "text": "Zweite Seite"},
                {"page": 3, "text": ""},
            ],
        )

        self.assertEqual(
            result["text"],
            "--- Seite 1 ---\nErste Seite\n\n"
            "--- Seite 2 ---\nZweite Seite",
        )
        self.assertEqual(result["characters"], len(result["text"]))

        self.assertEqual(
            result["rag"],
            {
                "indexed": True,
                "status": "ready",
                "chunks": 7,
                "chunks_done": 7,
                "chunks_total": 7,
                "progress": 1.0,
                "model": "embedding-model",
                "dimensions": 768,
                "cached": True,
            },
        )

        agent_request.assert_called_once_with(
            "POST",
            "/api/documents/index",
            {
                "document_id": expected_id,
                "name": "wissen.pdf",
                "document_type": "pdf",
                "pages": [
                    {"page": 1, "text": "Erste Seite"},
                    {"page": 2, "text": "Zweite Seite"},
                    {"page": 3, "text": ""},
                ],
            },
            timeout=30,
        )

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_page_extraction_failure_does_not_abort(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        read_upload.return_value = b"pdf"

        bad_page = MagicMock()
        bad_page.extract_text.side_effect = RuntimeError("extract failed")

        good_page = MagicMock()
        good_page.extract_text.return_value = " Funktioniert "

        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [bad_page, good_page]
        pdf_reader.return_value = reader

        agent_request.return_value = {"status": "queued"}

        result = self.run_parse(self.upload())

        self.assertEqual(
            result["page_texts"],
            [
                {"page": 1, "text": ""},
                {"page": 2, "text": "Funktioniert"},
            ],
        )
        self.assertEqual(
            result["text"],
            "--- Seite 2 ---\nFunktioniert",
        )

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rag_defaults_for_queued_response(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        read_upload.return_value = b"pdf"

        page = MagicMock()
        page.extract_text.return_value = "Text"

        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [page]
        pdf_reader.return_value = reader

        agent_request.return_value = {}

        result = self.run_parse(self.upload())

        self.assertEqual(
            result["rag"],
            {
                "indexed": False,
                "status": "queued",
                "chunks": 0,
                "chunks_done": 0,
                "chunks_total": 0,
                "progress": 0.0,
                "model": None,
                "dimensions": None,
                "cached": False,
            },
        )

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_rag_http_error_does_not_abort_document_parsing(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        read_upload.return_value = b"pdf"

        page = MagicMock()
        page.extract_text.return_value = "Text"

        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [page]
        pdf_reader.return_value = reader

        agent_request.side_effect = HTTPException(
            status_code=503,
            detail="Agent nicht erreichbar",
        )

        result = self.run_parse(self.upload())

        self.assertEqual(result["text"], "--- Seite 1 ---\nText")
        self.assertEqual(
            result["rag"],
            {
                "indexed": False,
                "status": "error",
                "chunks": 0,
                "chunks_done": 0,
                "chunks_total": 0,
                "progress": 0.0,
                "cached": False,
                "error": "Agent nicht erreichbar",
            },
        )

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_encrypted_pdf_with_empty_password_can_continue(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        read_upload.return_value = b"encrypted-but-unlockable"

        page = MagicMock()
        page.extract_text.return_value = "Entschlüsselt"

        reader = MagicMock()
        reader.is_encrypted = True
        reader.decrypt.return_value = 1
        reader.pages = [page]
        pdf_reader.return_value = reader

        agent_request.return_value = {"status": "ready"}

        result = self.run_parse(self.upload())

        reader.decrypt.assert_called_once_with("")
        self.assertEqual(
            result["text"],
            "--- Seite 1 ---\nEntschlüsselt",
        )
        self.assertTrue(result["rag"]["indexed"])

    @patch.object(backend_app, "agent_json_request")
    @patch.object(backend_app, "PdfReader")
    @patch.object(backend_app, "read_upload", new_callable=AsyncMock)
    def test_filename_and_content_type_fallbacks(
        self,
        read_upload,
        pdf_reader,
        agent_request,
    ):
        read_upload.return_value = b"pdf"

        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = []
        pdf_reader.return_value = reader

        agent_request.return_value = {"status": "queued"}

        file = self.upload()
        file.filename = None
        file.content_type = None

        result = self.run_parse(file)

        self.assertEqual(result["name"], "document.pdf")
        self.assertEqual(result["type"], "application/pdf")
        self.assertEqual(result["pages"], 0)
        self.assertEqual(result["text"], "")


if __name__ == "__main__":
    unittest.main()
