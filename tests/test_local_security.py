import os
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

    return app


class LocalRequestGuardTests(unittest.TestCase):
    def request(self, base_url, *, allowed_hosts=ALLOWED_HOSTS, headers=None):
        with patch.dict(os.environ, {"MLX_ALLOWED_HOSTS": allowed_hosts}, clear=False):
            with TestClient(guarded_app(), base_url=base_url) as client:
                return client.get("/", headers=headers or {})

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
