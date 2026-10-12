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
