"""Navigate only real publisher links from already fetched HTML.

Discovery does NOT establish authority or product availability. Requests
still pass through normal public-fetch guards and model source verification.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from agent.plan_fastpath import official_catalog_goal, _brand_for_goal, OFFICIAL_HOSTS

# HTML navigation commonly begins with dozens of generic links; keep a
# bounded larger discovery pool for the deterministic topical selector.
# Model planning still gets a smaller projection in planning_context.py.
_MAX_LINKS = 96
_TOPIC = re.compile(r"(?i)(?:iphone|ipad|pixel|galaxy|surface|smartphone|"
                    r"phones|telefone|modelle|products|portfolio|geräte|device|category)")
_EXCLUDE = re.compile(r"(?i)(?:account|login|signin|privacy|cookies|"
                      r"support|help|support\.google\.com)")


def same_site_html_links(page, base_url):
    """Return a small set of original real HTTPS anchor links with labels.

    The destination must be under the exact HTTPS host already fetched.
    Neither script links nor guessed paths are added.
    """
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return []

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []
            self.active = None
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()
            if tag in {"script", "style", "noscript", "template", "svg"}:
                self.skip += 1
            if self.skip or tag != "a":
                return
            href = dict(attrs).get("href")
            self.active = {"href": href, "label": ""} if isinstance(href, str) else None

        def handle_data(self, data):
            if self.active is not None and not self.skip:
                self.active["label"] += data[:160]

        def handle_endtag(self, tag):
            if tag.lower() == "a" and self.active is not None:
                self.items.append(self.active)
                self.active = None
            if tag.lower() in {"script", "style", "noscript", "template", "svg"}:
                self.skip = max(0, self.skip - 1)

    parser = Links()
    try:
        parser.feed(page)
    except (ValueError, TypeError):
        return []
    seen, output = set(), []
    for anchor in parser.items:
        href = anchor["href"].strip() if anchor["href"] else ""
        if not href or href.startswith(("#", "javascript:", "data:", "mailto:")):
            continue
        try:
            target = urlsplit(urljoin(base_url, href))
            acceptable = (
                target.scheme == "https" and target.hostname == parts.hostname
                and not target.username and not target.password
                and target.port in {None, 443}
            )
        except ValueError:
            continue
        if not acceptable:
            continue
        if not target.path or target.path == "/":
            continue
        url = urlunsplit(("https", target.netloc, target.path,
                          target.query[:160], ""))
        if len(url) > 1200 or url in seen:
            continue
        label = re.sub(r"\s+", " ", anchor["label"]).strip()[:120]
        if not label:
            continue
        seen.add(url)
        output.append({"url": url, "title": label})

    if len(output) <= _MAX_LINKS:
        return output

    # Keep the bounded list useful when long global menus appear before the
    # actual article links. A source-exact deep document URL generally carries
    # more navigational information than a generic single-level menu item.
    # Score only already parsed, same-host HTTPS links. Retain source order so
    # existing navigation consumers do not see an arbitrary reordering.
    def specificity(link):
        path = urlsplit(link["url"]).path
        segments = [segment for segment in path.split("/") if segment]
        document = bool(re.search(r"\.(?:html?|pdf)$", path, re.I))
        title = str(link.get("title") or "").casefold()
        # Large institution pages can contain hundreds of deep news links.
        # Keep authentic navigation to alphabetical mission/catalog indexes,
        # plus individual numbered mission links, ahead of that noise. This
        # grants no authority to the link's text; URLs are still fetched and
        # validated separately by the agent.
        mission_index = bool(re.search(
            r"(?i)a\s*(?:to|-|–)\s*z.*missions?|a-to-z-of-.*missions",
            title + " " + path,
        ))
        numbered_mission = bool(re.fullmatch(
            r"(?i)(?:apollo|artemis|gemini|mercury)\s+\d{1,3}", title,
        )) and bool(re.search(r"/mission/", path, re.I))
        return (int(mission_index or numbered_mission),
                min(len(segments), 8), document)

    selected = set(sorted(
        range(len(output)),
        key=lambda i: (
            -specificity(output[i])[0],
            -specificity(output[i])[1],
            -int(specificity(output[i])[2]),
            i,
        ),
    )[:_MAX_LINKS])
    return [link for i, link in enumerate(output) if i in selected]


def choose_catalog_page_link(goal, observations):
    """One actual category/model link from a fetched official landing page.

    No invented URL; requires explicit catalog intent and named manufacturer.
    Does not elevate page text into evidence without a successful fetch.
    """
    if not official_catalog_goal(goal):
        return None
    brand = _brand_for_goal(goal)
    if not brand:
        return None
    attempted = {
        str(item.get("query") or "")
        for item in observations if isinstance(item, dict)
        and item.get("action") == "fetch_url"
    }
    successful = [
        item for item in observations
        if isinstance(item, dict) and item.get("action") == "fetch_url"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
    ]
    if not successful or len(successful) >= 2:
        return None
    options = []
    for item in successful:
        result = item["result"]
        origin = result.get("final_url") or result.get("url") or ""
        try:
            parts = urlsplit(origin)
            hostname = (parts.hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if (parts.scheme != "https" or not any(
            hostname == root or hostname.endswith("." + root)
            for root in OFFICIAL_HOSTS[brand]
        )):
            continue
        links = result.get("page_links")
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            url, title = link.get("url"), link.get("title")
            if not isinstance(url, str) or not isinstance(title, str):
                continue
            try:
                target = urlsplit(url)
                if (target.scheme != "https"
                        or target.hostname != parts.hostname
                        or target.username or target.password
                        or url in attempted):
                    continue
            except ValueError:
                continue
            haystack = (target.path + " " + title).lower()
            if _EXCLUDE.search(haystack) or not _TOPIC.search(haystack):
                continue
            score = 0
            if re.search(r"/category/(?:phones|smartphones)|/phones?/?$|/iphone/?$", target.path, re.I):
                score += 100
            if re.search(r"(?i)smartphones|phones|modelle|alle\s+geräte|portfolio", title):
                score += 75
            if re.search(r"(?i)pixel|iphone|galaxy|surface", haystack):
                score += 30
            if "/product/" in target.path:
                score -= 20  # Prefer a category index over a single model.
            if score > 0:
                options.append((score, url))
    if not options:
        return None
    _, selected = max(options, key=lambda candidate: candidate[0])
    return {"action": "fetch_url", "query": selected,
            "reason": "Echte offizielle Produktübersicht aus geladener Herstellerseite öffnen"}
