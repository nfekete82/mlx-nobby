"""Source-exact release-summary windows, never guessed version numbers."""
import re


_LATEST = re.compile(
    r"(?i)\b(?:latest\s+python\s+3\s+release|"
    r"latest\s+stable\s+python\s+3\s+release|"
    r"neueste\s+(?:stabile\s+)?python(?:\s*3)?[- ]version)\b"
)
_VERSION = re.compile(r"(?i)\b(?:Python\s+)?3\.\d{1,2}\.\d{1,2}(?![.\w-])")
_ACTIVE = re.compile(r"(?i)\bactive\s+python\s+releases\b")
_STABLE = re.compile(r"(?i)\b(?:stable\s+releases|python\s+releases\s+by\s+version\s+number)\b")


def python_latest_release_windows(goal, text, *, max_windows=2):
    """Prioritize the loaded publisher's actual current-release headings.

    Search hints and version matching merely select byte-exact original text
    for the normal independent semantic verifier. No derived version or
    availability fact is emitted here.
    """
    request = str(goal or "").casefold()
    if (not isinstance(text, str) or
            not ("python.org" in request or re.search(r"\bpython\s*-?\s*3\b", request))
            or not re.search(r"(?i)\b(?:neueste|aktuell|latest|newest|stable|stabile)\b", request)):
        return []
    windows = []
    markers = list(_LATEST.finditer(text)) + list(_ACTIVE.finditer(text)) + list(_STABLE.finditer(text))
    markers.sort(key=lambda m: m.start())
    for marker in markers:
        # Each candidate is contiguous from the actual publisher text. The
        # window includes original context so a preview/release candidate
        # must not be mistaken for an actual final stable release.
        start = max(0, marker.start() - 80)
        end = min(len(text), marker.end() + 420)
        excerpt = text[start:end]
        if not _VERSION.search(excerpt):
            continue
        if any(abs(start - previous[0]) < 250 for previous in windows):
            continue
        if len(excerpt.strip()) < 40:
            continue
        windows.append((start, end, excerpt))
        if len(windows) >= max_windows:
            break
    return windows
