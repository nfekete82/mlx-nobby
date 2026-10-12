"""Publisher-specific readable article selection and source-identity checks.

These helpers never infer facts or create URLs. They operate only on the
original HTML response and the exact URL already fetched by the transport.
"""
import re
from urllib.parse import urlsplit


def prefer_publisher_main(url, html, extracted, text_extractor):
    """Prefer a substantive BMAS HTML <main> region over global site menus."""
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return extracted
    if parsed.scheme != "https" or parsed.hostname not in {"www.bmas.de", "bmas.de"}:
        return extracted
    if not isinstance(html, str):
        return extracted
    main = re.search(r"<main\b[^>]*>.*?</main\s*>", html,
                     flags=re.IGNORECASE | re.DOTALL)
    if not main:
        return extracted
    candidate = text_extractor(main.group(0)).strip()
    return candidate if len(candidate) >= 500 else extracted


def python_download_identity_missing(url, extracted):
    """A Python download landing page without 'Python' is not usable evidence."""
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname in {"www.python.org", "python.org"}
        and parsed.path.rstrip("/") == "/downloads"
        and not re.search(r"(?i)\bpython\b", str(extracted or ""))
    )
