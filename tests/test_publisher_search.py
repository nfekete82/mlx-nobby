"""bpb sources use an official SearXNG engine, not hardcoded facts or URLs."""
import io
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest

from agent.publisher_search import provider_query
from agent.search_status import request_searxng


def test_bpb_query_uses_specialized_engine_and_strips_question_boilerplate():
    assert provider_query("bpb.de wurde berliner mauer geöffnet nenne quelle mauerfall") == (
        "!bpb berliner mauer geöffnet mauerfall"
    )
    assert provider_query("site:bpb.de Berliner Mauer Mauerfall") == (
        "!bpb Berliner Mauer Mauerfall"
    )
    assert provider_query(
        "An welchem Datum wurde die Berliner Mauer geöffnet? "
        "Bitte nenne eine Quelle der Bundeszentrale für politische Bildung."
    ) == "!bpb Berliner Mauer geöffnet"
    assert provider_query("Mauerfall Berliner Mauer") == "Mauerfall Berliner Mauer"


def test_manual_engine_selection_keeps_source_terms():
    assert provider_query("site:nasa.gov Apollo 11", engine="google") == (
        "!go site:nasa.gov Apollo 11"
    )
    assert provider_query("site:nasa.gov Apollo 11", engine="bing") == (
        "!bi site:nasa.gov Apollo 11"
    )
    assert provider_query("!go Apollo 11") == "!go Apollo 11"
    with pytest.raises(ValueError):
        provider_query("Apollo 11", engine="not-an-engine")


def test_searxng_transport_sends_bang_not_unofficial_engine_parameter():
    result_url = "https://www.bpb.de/themen/deutsche-einheit/mauerfall/"
    payload = json.dumps({
        "results": [{"url": result_url, "title": "Mauerfall"}],
        "unresponsive_engines": [],
    }).encode()
    with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)) as opener, \
         patch.dict("os.environ", {"SEARXNG_FALLBACK_URLS": ""}):
        result, attempts = request_searxng(
            "http://127.0.0.1:8081",
            "q=bpb.de+wurde+berliner+mauer+ge%C3%B6ffnet+nenne+quelle+mauerfall&format=json",
        )
    search_url = opener.call_args.args[0].full_url
    query = parse_qs(urlsplit(search_url).query)
    assert query["q"] == ["!bpb berliner mauer geöffnet mauerfall"]
    assert "engines" not in query
    assert result["results"][0]["url"] == result_url
    assert attempts[0]["status"] == "available"


def test_unrelated_search_remains_unchanged():
    assert provider_query("PostgreSQL supported versions") == "PostgreSQL supported versions"
    assert provider_query("nasa.gov Apollo moon landing") == "nasa.gov Apollo moon landing"
