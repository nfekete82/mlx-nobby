"""Regression tests for the public repository privacy scan."""
import hashlib
from pathlib import Path
import runpy

def get_scan():
    root = Path(__file__).resolve().parents[1]
    return runpy.run_path(str(root / "scripts/check-public-privacy.py"))["scan_text"]

def test_hash_denied_identifier_without_storing_its_plaintext():
    marker = "Example Person"
    digest = hashlib.sha256(marker.casefold().encode()).hexdigest()
    assert "private identifier" in get_scan()(marker, {digest})
    assert get_scan()("different text", {digest}) == []

def test_machine_paths_and_documentation_paths():
    path = "/" + "Users" + "/actualowner/Models/demo"
    example = "/" + "Users" + "/example/Models/demo"
    assert "machine-specific home path" in get_scan()(path)
    assert "machine-specific home path" not in get_scan()(example)

def test_credentials_and_personal_email():
    email = "person@" + "gmail.com"
    token = "gh" + "p_" + "A" * 35
    assert "personal email" in get_scan()(email)
    assert "credential or private-key pattern" in get_scan()(token)

def test_neutral_text():
    assert get_scan()("MLX documentation https://example.org") == []
