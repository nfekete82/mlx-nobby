#!/usr/bin/env python3
"""Check tracked public files for sensitive data (does not scan Git history)."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

# SHA256 of normalized identifiers; do not publish their plaintext.
IDENTIFIER_HASHES = frozenset({
    "a88339a2513d552a3c582a5b409ff4fff2a7155bde26c2f14ae142ccfe4f1de8",
    "d80478df558fde0fbeeba327be4b0860cf8b7cafd458f4e194230022dea54c2f",
    "5d2652ea676ec37f94f28377a1cecf6a647447efc3ca5390cb3df37274e570d7",
})
# Human-reviewed public UI screenshots, pinned to exact Git blob content.
REVIEWED_SCREENSHOTS = {
    "docs/screenshots/chat.png": "1a6b8a73d93865de2cc06be6d80db1cc929e3bed",
    "docs/screenshots/models.png": "0faf3338551b7be5b9944808258817af0287edbf",
    "docs/screenshots/routing-observatory.png": "e434042f7ae9fce25b275748d12f52be31b90cee",
    "docs/screenshots/startscreen.png": "42d6ebb22787926a5c47c539de4b3955f1d04cb3",
}
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".mp4",
    ".mov", ".wav", ".mp3", ".m4a", ".pdf", ".zip", ".eml",
    ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx",
    ".docx", ".xlsx",
}
EXAMPLE_USERS = {"runner", "example", "user", "username", "yourname", "test", "demo", "nobody", "ubuntu", "oai", "shared", "name"}
UNIX_HOME = re.compile(r"/(?:Users|home)/([A-Za-z][A-Za-z0-9._-]{1,60})(?=[/\\\s\"']|$)")
WIN_HOME = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}([A-Za-z][A-Za-z0-9._-]{1,60})", re.I)
PRIVATE_EMAIL = re.compile(r"\b[\w.+-]+@(?:gmail|googlemail|icloud|me|outlook|hotmail|yahoo|protonmail|proton|gmx|web|dpolg-service)\.[a-z.]+\b", re.I)
SECRET = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b")
PRIVATE_KEY = re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
TOKENS = re.compile(r"[A-Za-z0-9._-]+")

def has_identifier(content: str, hashes=IDENTIFIER_HASHES) -> bool:
    words = TOKENS.findall(content.casefold())
    for index, word in enumerate(words):
        candidates = (word, word + " " + words[index + 1]) if index + 1 < len(words) else (word,)
        if any(hashlib.sha256(value.encode()).hexdigest() in hashes for value in candidates):
            return True
    return False

def scan_text(content: str, hashes=IDENTIFIER_HASHES) -> list[str]:
    found = []
    if has_identifier(content, hashes):
        found.append("private identifier")
    if SECRET.search(content) or PRIVATE_KEY.search(content):
        found.append("credential or private-key pattern")
    if PRIVATE_EMAIL.search(content):
        found.append("personal email")
    if any(m.group(1).casefold() not in EXAMPLE_USERS for pattern in (UNIX_HOME, WIN_HOME) for m in pattern.finditer(content)):
        found.append("machine-specific home path")
    return found

def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [os.fsdecode(part) for part in raw.split(b"\0") if part]

def audit() -> list[tuple[str, str]]:
    issues = []
    for name in tracked_files():
        path = ROOT / name
        if not path.is_file():
            continue
        if path.suffix.lower() in BINARY_EXTS:
            expected = REVIEWED_SCREENSHOTS.get(name)
            if not expected:
                issues.append((name, "unreviewed binary artifact"))
            elif subprocess.check_output(["git", "hash-object", "--", name], cwd=ROOT, text=True).strip() != expected:
                issues.append((name, "documentation screenshot modified without approval"))
            continue
        if path.stat().st_size > 5_000_000:
            issues.append((name, "oversized file needs review"))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            issues.append((name, "non-UTF8 content needs review"))
            continue
        issues.extend((name, category) for category in scan_text(content))
    return issues

def main() -> int:
    issues = audit()
    for name, category in issues:
        print(f"FAIL: {name}: {category}", file=sys.stderr)
    if issues:
        print("Public privacy check failed; matched contents are not displayed.", file=sys.stderr)
        return 1
    print(f"Public privacy check passed: {len(tracked_files())} tracked files.")
    print("Does NOT scan historical commits, PR discussions, forks or GitHub Actions logs.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
