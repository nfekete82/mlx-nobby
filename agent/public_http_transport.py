"""Public HTTP transport with connection-time DNS validation and IP pinning.

Only intended for untrusted public article fetches, not internal services.
The verified socket address is the destination actually used by the socket;
TLS SNI, certificate verification and Host remain bound to the URL hostname.
"""
import http.client
import ipaddress
import socket
import urllib.request


def _public_tcp_addresses(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise OSError("Public DNS lookup failed") from exc
    if not infos:
        raise OSError("Public DNS lookup returned no addresses")
    for family, kind, proto, _, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise OSError("Unsupported public network address")
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise OSError("Invalid public network address") from exc
        if not address.is_global:
            raise OSError("Non-public destination is blocked")
    return infos


def _pinned_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                       source_address=None):
    host, port = address
    addresses = _public_tcp_addresses(host, port)
    previous = None
    for family, kind, proto, _, sockaddr in addresses:
        connection = None
        try:
            connection = socket.socket(family, kind, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            connection.connect(sockaddr)
            return connection
        except OSError as exc:
            previous = exc
            if connection:
                connection.close()
    raise OSError("Cannot connect to any verified public address") from previous


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _pinned_connection


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _pinned_connection


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PinnedHTTPConnection, request)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PinnedHTTPSConnection, request, context=self._context)


def build_public_article_opener(redirect_handler):
    """Force direct validated connections, avoiding environment proxies."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(),
        redirect_handler(),
    )
