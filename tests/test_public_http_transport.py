"""No DNS rebinding after a validated public address is selected."""
import socket
import urllib.request
from unittest.mock import Mock, patch

import pytest

from agent import public_http_transport as transport


PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
           ("8.8.8.8", 443))]
MIXED = PUBLIC + [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                   ("127.0.0.1", 443))]


def test_private_and_mixed_resolution_fail_closed():
    with patch.object(socket, "getaddrinfo", return_value=MIXED):
        with patch.object(socket, "socket") as make_socket:
            with pytest.raises(OSError, match="Non-public"):
                transport._pinned_connection(("example.org", 443), 2)
            make_socket.assert_not_called()


def test_socket_connects_to_verified_numeric_address_not_hostname():
    sock = Mock()
    with patch.object(socket, "getaddrinfo", return_value=PUBLIC) as resolver:
        with patch.object(socket, "socket", return_value=sock):
            assert transport._pinned_connection(("example.org", 443), 2) is sock
    resolver.assert_called_once_with("example.org", 443,
        type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.connect.assert_called_once_with(("8.8.8.8", 443))
    sock.settimeout.assert_called_once_with(2)


def test_does_not_connect_when_resolution_fails():
    with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror):
        with patch.object(socket, "socket") as make_socket:
            with pytest.raises(OSError, match="Public DNS"):
                transport._pinned_connection(("example.org", 443))
            make_socket.assert_not_called()


def test_connection_retains_original_hostname_for_tls_and_host_header():
    https = transport._PinnedHTTPSConnection("www.example.org")
    http = transport._PinnedHTTPConnection("www.example.org")
    assert https.host == "www.example.org"
    assert http.host == "www.example.org"
    assert https._create_connection is transport._pinned_connection
    assert http._create_connection is transport._pinned_connection


def test_public_article_opener_uses_only_pinned_handlers():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = transport.build_public_article_opener(NoRedirect)
    assert any(isinstance(h, transport._PinnedHTTPSHandler) for h in opener.handlers)
    assert any(isinstance(h, transport._PinnedHTTPHandler) for h in opener.handlers)
    assert not any(type(h) is urllib.request.HTTPSHandler for h in opener.handlers)
    assert not any(type(h) is urllib.request.HTTPHandler for h in opener.handlers)
    assert any(isinstance(h, NoRedirect) for h in opener.handlers)
