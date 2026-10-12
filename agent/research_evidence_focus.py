"""Remove navigation-only context after an exact, fetched primary document exists.

This is a token-budget optimization, not a source-authority decision. Every
remaining fact must pass ordinary source anchoring and model verification.
"""
import re
from urllib.parse import urlsplit

from agent.official_source_navigation import (
    _nasa_numbered_mission, _safe_official_url,
)


def evidence_focus_observations(goal, observations):
    """Keep raw observations intact until an exact NASA mission article loads.

    Drop only the NASA homepage and A-to-Z directory from the *model evidence*
    payload. They remain in the agent's research trace and URL-provenance log.
    Unknown institutions, failed fetches and unrelated articles are untouched.
    """
    if not isinstance(observations, (list, tuple)):
        return observations
    # A focused reread of a real Python download page supersedes only its
    # earlier broad 18k-character chunk for LLM evidence ranking. Both fetch
    # steps remain in the original immutable research trace.
    from agent.software_release_navigation import python_latest_version_question
    if python_latest_version_question(goal):
        focused_urls = set()
        for item in observations:
            if not isinstance(item, dict) or item.get("action") != "fetch_url":
                continue
            result = item.get("result")
            if (item.get("status") != "completed" or not isinstance(result, dict)
                    or result.get("ok") is not True
                    or result.get("focus") != "Active Python releases"):
                continue
            url = result.get("final_url") or result.get("url")
            parsed = urlsplit(str(url or ""))
            if (parsed.scheme == "https" and parsed.hostname in
                    {"www.python.org", "python.org"}
                    and parsed.path.rstrip("/") == "/downloads"):
                focused_urls.add(url)
        if focused_urls:
            return [
                item for item in observations
                if not (
                    isinstance(item, dict) and item.get("action") == "fetch_url"
                    and isinstance(item.get("result"), dict)
                    and item["result"].get("ok") is True
                    and item["result"].get("focus") is None
                    and (item["result"].get("final_url") or item["result"].get("url"))
                        in focused_urls
                )
            ]
        # Another officially fetched stable-release directory can supersede
        # a broad /downloads/ source which contains no usable current-release
        # passage. Keep the original trace and all newly loaded sources.
        alternate_release_loaded = False
        for item in observations:
            if not isinstance(item, dict) or item.get("action") != "fetch_url":
                continue
            result = item.get("result")
            if (item.get("status") != "completed" or not isinstance(result, dict)
                    or result.get("ok") is not True):
                continue
            parsed = urlsplit(str(result.get("final_url") or result.get("url") or ""))
            if (parsed.scheme != "https" or
                    parsed.hostname not in {"www.python.org", "python.org"}):
                continue
            content = str(result.get("text") or "")
            index = parsed.path.rstrip("/") in {
                "/downloads/macos", "/downloads/windows", "/downloads/source",
            } and re.search(r"(?i)\bpython\s+3\.\d", content)
            # A fetched official final release article with an explicit
            # stable/newest assertion is stronger than the generic catalog
            # for verifying the current stable Python version.
            article = (
                re.fullmatch(r"/downloads/release/python-3\d{2,4}/?",
                             parsed.path)
                and re.search(r"(?i)\bpython\s+3\.\d{1,2}\.\d{1,2}\b", content)
                and re.search(r"(?i)\b(?:newest|latest|stable)\b", content)
            )
            if index or article:
                alternate_release_loaded = True
        if alternate_release_loaded:
            return [
                item for item in observations
                if not (
                    isinstance(item, dict) and item.get("action") == "fetch_url"
                    and isinstance(item.get("result"), dict)
                    and item["result"].get("ok") is True
                    and urlsplit(str(
                        item["result"].get("final_url") or item["result"].get("url") or ""
                    )).path.rstrip("/") == "/downloads"
                    and urlsplit(str(
                        item["result"].get("final_url") or item["result"].get("url") or ""
                    )).hostname in {"www.python.org", "python.org"}
                )
            ]
    mission = _nasa_numbered_mission(goal)
    if not mission:
        return observations

    parts = mission.split()
    path_name = re.compile(
        r"(?i)(?:^|/)" + re.escape(parts[0]) + r"[-_/]?" +
        re.escape(parts[1]) + r"(?:/|$)"
    )
    eligible = False
    for item in observations:
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or item.get("status") != "completed"):
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        url = result.get("final_url") or result.get("url")
        parsed = _safe_official_url(url, "nasa.gov")
        if (parsed is not None and path_name.search(parsed.path)
                and isinstance(result.get("text"), str)
                and len(result["text"].strip()) >= 80):
            eligible = True
            break
    if not eligible:
        return observations

    def discovery_only(item):
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            return False
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            return False
        parsed = _safe_official_url(
            result.get("final_url") or result.get("url"), "nasa.gov",
        )
        if parsed is None:
            return False
        return parsed.path.casefold().rstrip("/") in {
            "", "/a-to-z-of-nasa-missions",
        }

    return [item for item in observations if not discovery_only(item)]
