import os
import asyncio
import httpx
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_security import LocalRequestGuard


TAILSCALE_HOST = "macbook.example-tailnet.ts.net"
ALLOWED_HOSTS = f"localhost,127.0.0.1,::1,{TAILSCALE_HOST}"


def guarded_app():
    app = FastAPI()
    app.add_middleware(LocalRequestGuard)

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/chat")
    async def chat():
        return {"page": "chat"}

    @app.get("/settings/{page:path}")
    async def settings(page: str):
        return {"page": page}

    @app.get("/api/health")
    async def api_health():
        return {"ok": True}

    @app.post("/api/mutate")
    async def mutate():
        return {"changed": True}

    return app


class LocalRequestGuardTests(unittest.TestCase):
    def request(self, base_url, *, allowed_hosts=ALLOWED_HOSTS, headers=None):
        with patch.dict(os.environ, {"MLX_ALLOWED_HOSTS": allowed_hosts}, clear=False):
            # Exercise the actual ASGI guard for IPv4 and bracketed IPv6.
            # Starlette 1.6's deprecated httpx TestClient splits IPv6 netloc
            # at the first colon before the request can reach the guard.
            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded_app()), base_url=base_url) as client:
                    return await client.get('/', headers=headers or {})
            return asyncio.run(send())

    def test_allows_https_origin_behind_tls_terminating_proxy(self):
        response = self.request(
            f"http://{TAILSCALE_HOST}",
            headers={
                "Origin": f"https://{TAILSCALE_HOST}",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})

    def test_allows_same_port_literal_loopback_aliases(self):
        for base, origin in (
            ("http://127.0.0.1:8091", "http://localhost:8091"),
            ("http://localhost:8091", "http://127.0.0.1:8091"),
            ("http://[::1]:8091", "http://localhost:8091"),
        ):
            with self.subTest(base=base, origin=origin):
                result = self.request(base, headers={
                    "Origin": origin,
                    "Sec-Fetch-Site": "cross-site",
                })
                self.assertEqual(result.status_code, 200, result.text)

    def test_rejects_loopback_alias_on_other_port(self):
        response = self.request(
            "http://127.0.0.1:8091",
            headers={
                "Origin": "http://localhost:8090",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_external_origin_even_for_loopback_host(self):
        response = self.request(
            "http://127.0.0.1:8091",
            headers={
                "Origin": "https://external.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_loopback_alias_requires_literal_host(self):
        response = self.request(
            "http://macbook.example-tailnet.ts.net:8091",
            headers={
                "Origin": "http://localhost:8091",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_null_origin_from_sandbox(self):
        response = self.request(
            "http://localhost:8091",
            headers={"Origin": "null"},
        )
        self.assertEqual(response.status_code, 403)

    def test_clicked_external_link_can_open_local_chat_page(self):
        navigation = {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-User": "?1",
        }
        with patch.dict(os.environ, {"MLX_ALLOWED_HOSTS": ALLOWED_HOSTS}, clear=False):
            with TestClient(guarded_app(), base_url="http://127.0.0.1:8091") as client:
                for path in ("/", "/chat", "/settings/appearance"):
                    with self.subTest(path=path):
                        result = client.get(path, headers=navigation)
                        self.assertEqual(result.status_code, 200, result.text)

    def test_cross_site_api_and_noninteractive_requests_remain_blocked(self):
        navigation = {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-User": "?1",
        }
        with patch.dict(os.environ, {"MLX_ALLOWED_HOSTS": ALLOWED_HOSTS}, clear=False):
            with TestClient(guarded_app(), base_url="http://127.0.0.1:8091") as client:
                # Even user-activated cross-site navigation cannot reach API routes.
                self.assertEqual(client.get("/api/health", headers=navigation).status_code, 403)
                self.assertEqual(client.post("/api/mutate", headers=navigation).status_code, 403)
                # An iframe or programmatic cross-origin fetch must not open pages.
                for changed in (
                    {"Sec-Fetch-Mode": "cors"},
                    {"Sec-Fetch-Dest": "iframe"},
                    {"Sec-Fetch-User": "?0"},
                    {"Origin": "https://example.org"},
                ):
                    with self.subTest(changed=changed):
                        headers = {**navigation, **changed}
                        self.assertEqual(client.get("/chat", headers=headers).status_code, 403)
                self.assertEqual(client.get("/chat", headers={
                    **navigation, "Host": "untrusted.example",
                }).status_code, 403)

    def test_rejects_host_not_in_allowlist(self):
        response = self.request(
            "http://untrusted.example-tailnet.ts.net",
            allowed_hosts="localhost,127.0.0.1,::1",
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_foreign_origin_even_when_host_is_allowed(self):
        response = self.request(
            f"http://{TAILSCALE_HOST}",
            headers={
                "Origin": "https://other.example-tailnet.ts.net",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_cross_site_request(self):
        response = self.request(
            f"http://{TAILSCALE_HOST}",
            headers={
                "Origin": f"https://{TAILSCALE_HOST}",
                "Sec-Fetch-Site": "cross-site",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_non_http_origin_scheme(self):
        response = self.request(
            f"http://{TAILSCALE_HOST}",
            headers={
                "Origin": f"ftp://{TAILSCALE_HOST}",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
