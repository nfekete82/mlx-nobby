"""SearXNG source-specific discovery via documented !engine syntax.

Routing selects a search provider, not a source of verified facts.
"""
import re

_ENGINES = {"bpb": "!bpb", "google": "!go", "bing": "!bi"}
_PUBLISHER = re.compile(
    r"(?i)(?<![\w.-])(?:site:bpb\.de|bpb\.de|bpb|"
    r"bundeszentrale\s+f(?:ü|ue)r\s+politische\s+bildung)(?![\w.-])"
)
_STOP = frozenset(
    "an am bei bitte das dem den der des die einer ein eine einen für im "
    "ist laut mit nach nenne nennen quelle quellen und von wann was welche "
    "welchen welcher welchem welches wer wie wird wurde wurden zum zur datum"
    .split()
)

def provider_query(query, engine=None):
    original = str(query or "").strip()
    if not original:
        return original
    if engine is not None:
        if engine not in _ENGINES:
            raise ValueError("Unsupported SearXNG engine")
        remaining = re.sub(r"^![^\s]+\s+", "", original)
        return f"{_ENGINES[engine]} {remaining}"
    if re.match(r"^![^\s]+\s+", original) or not _PUBLISHER.search(original):
        return original
    topic = _PUBLISHER.sub(" ", original)
    words = [
        word for word in re.findall(r"[^\W_]+(?:-[^\W_]+)*", topic)
        if word.casefold() not in _STOP
    ]
    return "!bpb " + " ".join(words[:12]) if words else original
