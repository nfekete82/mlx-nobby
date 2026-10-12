"""Provider diagnostic classification; never infer success from HTTP alone."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def classify_search_failure(reason="", status=None):
    value = str(reason or "").casefold()
    if status == 429 or "too many requests" in value or "rate limit" in value:
        return "rate_limited"
    if "captcha" in value or "verify you are human" in value:
        return "captcha"
    if status in {401, 403} or "access denied" in value or "forbidden" in value:
        return "access_denied"
    if "timeout" in value or "timed out" in value:
        return "timeout"
    if "invalid" in value or "decode" in value:
        return "invalid_response"
    return "unavailable"


def blocked_page_status(text):
    """Recognize challenge pages only in their short leading page content."""
    value = str(text or "")[:1500].casefold()
    if any(marker in value for marker in (
        "verify you are human", "complete the captcha", "unusual traffic",
        "checking your browser before accessing", "enable javascript and cookies to continue",
    )):
        return "captcha"
    if value.strip().startswith(("access denied", "403 forbidden")):
        return "access_denied"
    if value.strip().startswith(("too many requests", "429 too many")):
        return "rate_limited"
    return None


def request_searxng(primary_url, params):
    """Try operator-configured endpoints once; no challenge bypass or sleeps.

    Endpoints are trusted process configuration, never supplied by web content.
    Up to two explicit secondary instances may follow the primary instance.
    """
    # Use the dedicated official publisher engine when the query explicitly
    # names that publisher. SearXNG ignores the unofficial engines= parameter;
    # its documented !engine syntax is part of q instead.
    from agent.publisher_search import provider_query
    pairs = urllib.parse.parse_qsl(params, keep_blank_values=True)
    rewritten = []
    for key, value in pairs:
        rewritten.append((key, provider_query(value) if key == "q" else value))
    params = urllib.parse.urlencode(rewritten)

    endpoints = [primary_url]
    endpoints.extend(os.environ.get("SEARXNG_FALLBACK_URLS", "").split(","))
    attempts, last_payload, seen = [], None, set()
    for endpoint in endpoints:
        endpoint = endpoint.strip().rstrip("/")
        if not endpoint or endpoint in seen or len(attempts) >= 3:
            continue
        seen.add(endpoint)
        try:
            parsed = urllib.parse.urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("invalid configured endpoint")
            request = urllib.request.Request(endpoint + "/search?" + params,
                headers={"Accept": "application/json", "User-Agent": "MLX-Nobby/2.0"})
            with urllib.request.urlopen(request, timeout=3) as response:
                raw = response.read(1_500_001)
            if len(raw) > 1_500_000:
                raise ValueError("invalid oversized response")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError("invalid provider schema")
            if not isinstance(payload.get("unresponsive_engines", []), list):
                raise ValueError("invalid engine schema")
            last_payload = payload
            status = "available" if payload["results"] else (
                "degraded" if payload.get("unresponsive_engines") else "empty")
            attempts.append({"provider": "SearXNG", "instance": len(attempts) + 1, "status": status})
            if status != "degraded":
                return payload, attempts
        except (OSError, TimeoutError, ValueError) as exc:
            attempts.append({"provider": "SearXNG", "instance": len(attempts) + 1,
                "status": classify_search_failure(str(exc), getattr(exc, "code", None))})
    return last_payload, attempts
