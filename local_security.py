"""Small shared guards for single-user, local HTTP services (not authentication)."""
import os
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.responses import JSONResponse


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

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        try:
            host = urlsplit("//" + headers.get("host", ""))
            allowed = host.hostname in self.hosts and not host.username and not host.password
            if "origin" in headers:
                origin = urlsplit(headers["origin"])
                allowed = allowed and origin.scheme == scope.get("scheme", "http") and origin.netloc == host.netloc
            allowed = allowed and headers.get("sec-fetch-site") != "cross-site"
        except ValueError:
            allowed = False
        if not allowed:
            return await JSONResponse({"detail": "Nur lokale Zugriffe vom selben Ursprung sind erlaubt"}, 403)(scope, receive, send)
        length = headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
            except ValueError:
                size = -1
            if size < 0 or size > self.max_body:
                return await JSONResponse({"detail": "Ungültige oder zu große Anfrage"}, 413)(scope, receive, send)

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
                    await JSONResponse({"detail": "Anfrage ist zu groß"}, 413)(scope, receive, send)
                return
            await send(message)

        await self.app(scope, limited_receive, guarded_send)


async def read_upload(file, limit):
    """Bound reads even when Content-Length is absent or misleading."""
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Datei ist zu groß")
    return data
