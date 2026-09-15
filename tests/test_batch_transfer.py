import asyncio
import io
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, UploadFile

from backend import app as backend_app


class FakeUpload:
    def __init__(
        self,
        data=b"hello",
        filename="batch.txt",
        content_type="text/plain",
    ):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(data)
        self.closed = False

    async def seek(self, offset):
        self.file.seek(offset)

    async def close(self):
        self.closed = True


class BatchUploadTests(unittest.TestCase):
    def run_upload(self, file):
        return asyncio.run(
            backend_app.mlx_batch_upload(file)
        )

    @patch.object(
        backend_app,
        "MAX_UPLOAD_SIZE_BYTES",
        3,
    )
    def test_rejects_oversized_upload_and_closes_file(self):
        file = FakeUpload(b"1234")

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(file)

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn(
            "Datei ist zu groß",
            ctx.exception.detail,
        )
        self.assertTrue(file.closed)

    @patch.object(
        backend_app,
        "AGENT_URL",
        "https://127.0.0.1:8010",
    )
    def test_rejects_non_http_agent_url(self):
        file = FakeUpload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(file)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(
            ctx.exception.detail,
            "Für den lokalen Agent-Upload wird HTTP erwartet",
        )
        self.assertTrue(file.closed)

    @patch.object(
        backend_app,
        "AGENT_URL",
        "http:///missing-host",
    )
    def test_rejects_agent_url_without_host(self):
        file = FakeUpload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(file)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(
            ctx.exception.detail,
            "Ungültige AGENT_URL",
        )
        self.assertTrue(file.closed)

    @patch("http.client.HTTPConnection")
    @patch("uuid.uuid4")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_successfully_streams_multipart_upload(
        self,
        uuid4,
        http_connection,
    ):
        uuid4.return_value.hex = "fixedboundary"

        response = MagicMock()
        response.status = 200
        response.read.return_value = (
            b'{"job_id":"job-1","status":"queued"}'
        )

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        file = FakeUpload(
            b"hello world",
            filename='unsafe"name.txt',
            content_type="text/plain",
        )

        result = self.run_upload(file)

        self.assertEqual(
            result,
            {
                "job_id": "job-1",
                "status": "queued",
            },
        )
        self.assertTrue(file.closed)

        http_connection.assert_called_once_with(
            "127.0.0.1",
            8010,
            timeout=900,
        )

        connection.putrequest.assert_called_once_with(
            "POST",
            "/api/batch/upload",
        )

        connection.endheaders.assert_called_once()
        connection.getresponse.assert_called_once()
        connection.close.assert_called_once()

        sent = b"".join(
            call.args[0]
            for call in connection.send.call_args_list
        )

        self.assertIn(
            b'filename="unsafe_name.txt"',
            sent,
        )
        self.assertIn(
            b"Content-Type: text/plain",
            sent,
        )
        self.assertIn(b"hello world", sent)
        self.assertIn(
            b"----MLXBatchBoundaryfixedboundary",
            sent,
        )

        headers = {
            call.args[0]: call.args[1]
            for call in connection.putheader.call_args_list
        }

        self.assertIn(
            "multipart/form-data; boundary="
            "----MLXBatchBoundaryfixedboundary",
            headers["Content-Type"],
        )
        self.assertEqual(
            int(headers["Content-Length"]),
            len(sent),
        )

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://agent.local/base",
    )
    def test_agent_base_path_is_preserved(
        self,
        http_connection,
    ):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"ok":true}'

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        file = FakeUpload(b"x")

        result = self.run_upload(file)

        self.assertEqual(result, {"ok": True})

        connection.putrequest.assert_called_once_with(
            "POST",
            "/base/api/batch/upload",
        )

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_http_error_with_json_detail(
        self,
        http_connection,
    ):
        response = MagicMock()
        response.status = 422
        response.read.return_value = (
            b'{"detail":"bad batch"}'
        )

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        file = FakeUpload()

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(file)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail,
            "bad batch",
        )
        self.assertTrue(file.closed)

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_http_error_with_plain_text_detail(
        self,
        http_connection,
    ):
        response = MagicMock()
        response.status = 500
        response.read.return_value = b"agent exploded"

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(FakeUpload())

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(
            ctx.exception.detail,
            "agent exploded",
        )

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_success_with_invalid_json_is_bad_gateway(
        self,
        http_connection,
    ):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"not-json"

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        with self.assertRaises(HTTPException) as ctx:
            self.run_upload(FakeUpload())

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(
            ctx.exception.detail,
            "Ungültige Antwort vom MLX-Agent",
        )

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_connection_failure_still_closes_resources(
        self,
        http_connection,
    ):
        connection = MagicMock()
        connection.putrequest.side_effect = OSError(
            "connection failed"
        )
        http_connection.return_value = connection

        file = FakeUpload()

        with self.assertRaises(OSError):
            self.run_upload(file)

        self.assertTrue(file.closed)
        connection.close.assert_called_once()

    @patch("http.client.HTTPConnection")
    @patch.object(
        backend_app,
        "AGENT_URL",
        "http://127.0.0.1:8010",
    )
    def test_filename_and_content_type_fallbacks(
        self,
        http_connection,
    ):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"ok":true}'

        connection = MagicMock()
        connection.getresponse.return_value = response
        http_connection.return_value = connection

        file = FakeUpload(
            b"x",
            filename=None,
            content_type=None,
        )

        result = self.run_upload(file)

        self.assertEqual(result, {"ok": True})

        sent = b"".join(
            call.args[0]
            for call in connection.send.call_args_list
        )

        self.assertIn(
            b'filename="upload.bin"',
            sent,
        )
        self.assertIn(
            b"Content-Type: application/octet-stream",
            sent,
        )


class BatchDownloadTests(unittest.TestCase):
    @patch.object(
        backend_app.urllib.request,
        "urlopen",
    )
    def test_download_success(self, urlopen):
        response = MagicMock()
        response.read.return_value = b"result-data"
        response.headers.get.side_effect = (
            lambda key, default=None: {
                "Content-Disposition":
                    'attachment; filename="result.json"',
                "Content-Type":
                    "application/json",
            }.get(key, default)
        )

        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        urlopen.return_value = context

        result = backend_app.mlx_batch_download(
            "job / weird",
        )

        expected_url = (
            backend_app.AGENT_URL
            + "/api/batch/job%20%2F%20weird/download"
        )

        urlopen.assert_called_once_with(
            expected_url,
            timeout=30,
        )

        self.assertEqual(
            result.body,
            b"result-data",
        )
        self.assertEqual(
            result.media_type,
            "application/json",
        )
        self.assertEqual(
            result.headers["content-disposition"],
            'attachment; filename="result.json"',
        )

    @patch.object(
        backend_app.urllib.request,
        "urlopen",
    )
    def test_download_header_defaults(self, urlopen):
        response = MagicMock()
        response.read.return_value = b"x"
        response.headers.get.side_effect = (
            lambda key, default=None: default
        )

        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        urlopen.return_value = context

        result = backend_app.mlx_batch_download("job")

        self.assertEqual(
            result.media_type,
            "application/octet-stream",
        )
        self.assertEqual(
            result.headers["content-disposition"],
            "attachment",
        )

    @patch.object(
        backend_app.urllib.request,
        "urlopen",
    )
    def test_download_http_error(self, urlopen):
        error = urllib.error.HTTPError(
            url="http://agent",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"missing job"),
        )
        urlopen.side_effect = error

        with self.assertRaises(HTTPException) as ctx:
            backend_app.mlx_batch_download("missing")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(
            ctx.exception.detail,
            "missing job",
        )

    @patch.object(
        backend_app.urllib.request,
        "urlopen",
    )
    def test_download_url_error(self, urlopen):
        urlopen.side_effect = urllib.error.URLError(
            "connection refused"
        )

        with self.assertRaises(HTTPException) as ctx:
            backend_app.mlx_batch_download("job")

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(
            ctx.exception.detail,
            "Agent nicht erreichbar: connection refused",
        )


if __name__ == "__main__":
    unittest.main()
