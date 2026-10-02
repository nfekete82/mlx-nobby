"""Small shared guards for single-user, local HTTP services (not authentication)."""
import os
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.responses import JSONResponse

from service_identity import service_identity


class LocalRequestGuard:
    """Reject foreign browser origins, DNS rebinding hosts and oversized bodies.

    Native clients without Origin remain supported. This is not a boundary
    against other local processes; services must still bind to loopback.
    """

    def __init__(self, app):
        self.app = app
        self.hosts = {
            value.strip().lower() for value in os.environ.get(
                "MLX_ALLOWED_HOSTS", "localhost,127.0.0.1,::1,host.docker.internal"
            ).split(",") if value.strip()
        }
        self.max_body = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "250")) * 1024**2 + 1024**2
        self.identity = service_identity()

    @staticmethod
    def _origin_matches_host(origin, host, backend_scheme):
        """Allow same-origin requests through an HTTPS-terminating reverse proxy."""
        if origin.netloc != host.netloc or origin.scheme not in {"http", "https"}:
            return False
        if origin.scheme == backend_scheme:
            return True
        # Tailscale Serve and similar trusted proxies terminate TLS before
        # forwarding to the loopback HTTP backend while preserving Host/Origin.
        return origin.scheme == "https" and backend_scheme == "http"

    def _with_identity_headers(self, message):
        if message.get("type") != "http.response.start":
            return message

        headers = list(message.get("headers", []))
        existing = {key.lower() for key, _ in headers}
        additions = (
            (b"x-mlx-nobby-revision", self.identity["revision"]),
            (b"x-mlx-nobby-started-at", self.identity["started_at"]),
        )

        for key, value in additions:
            if key not in existing and value:
                headers.append((key, str(value).encode("latin1")))

        return {**message, "headers": headers}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        def rejection(message, status):
            if scope.get("path") in {"/v1/models", "/v1/chat/completions"}:
                return JSONResponse({"error": {
                    "message": message, "type": "invalid_request_error",
                    "code": "local_access_required" if status == 403 else "request_too_large",
                }}, status)
            return JSONResponse({"detail": message}, status)

        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        try:
            host = urlsplit("//" + headers.get("host", ""))
            allowed = host.hostname in self.hosts and not host.username and not host.password
            if "origin" in headers:
                origin = urlsplit(headers["origin"])
                allowed = allowed and self._origin_matches_host(
                    origin,
                    host,
                    scope.get("scheme", "http"),
                )
            allowed = allowed and headers.get("sec-fetch-site") != "cross-site"
        except ValueError:
            allowed = False
        if not allowed:
            return await rejection("Nur lokale Zugriffe vom selben Ursprung sind erlaubt", 403)(scope, receive, send)
        length = headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
            except ValueError:
                size = -1
            if size < 0 or size > self.max_body:
                return await rejection("Ungültige oder zu große Anfrage", 413)(scope, receive, send)

        # Count streaming bodies too, before the multipart parser can spool
        # unlimited data. Replace parser error responses with a consistent 413.
        received = 0
        exceeded = False
        rejected = False

        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    exceeded = True
                    raise HTTPException(413, "Anfrage ist zu groß")
            return message

        async def guarded_send(message):
            nonlocal rejected
            if exceeded:
                if not rejected:
                    rejected = True
                    await rejection("Anfrage ist zu groß", 413)(scope, receive, send)
                return
            await send(self._with_identity_headers(message))

        await self.app(scope, limited_receive, guarded_send)


async def read_upload(file, limit):
    """Bound reads even when Content-Length is absent or misleading."""
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Datei ist zu groß")
    return data
