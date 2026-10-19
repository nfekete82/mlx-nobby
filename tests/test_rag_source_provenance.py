"""The actual web stream must cite each source admitted into its context."""
import asyncio
import json
import pytest

from backend import app as web


@pytest.mark.parametrize('late_context', ['0', '1'])
def test_admitted_lower_similarity_source_is_forwarded_and_disclosed(monkeypatch, late_context):
    monkeypatch.setenv('NOBBY_RAG_LATE_CONTEXT', late_context)
    source = {'source': 'Synthetic KB', 'path': 'case-00.txt',
              'snippet': 'The synthetic answer is AMBER37.', 'similarity': 0.79}

    def agent(method, path, **kwargs):
        if path == '/api/chat/route':
            return {'intent': 'knowledge_search'}
        if path == '/api/knowledge/search':
            return {'results': [source]}
        return {}

    monkeypatch.setattr(web, 'agent_json_request', agent)
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            return iter([b'data: {"type":"content","text":"AMBER37"}\n\n',
                         b'event: done\ndata: {}\n\n'])

    def opened(request, **kwargs):
        sent.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(web.urllib.request, 'urlopen', opened)
    response = web.mlx_chat_stream(web.ChatRequest(
        messages=[{'role': 'user', 'content': 'Lokale Wissensbasis: Was lautet das Prüfwort?'}],
        temperature=0, max_tokens=2048))

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    stream = ''.join(chunk.decode() if isinstance(chunk, bytes) else chunk
                     for chunk in asyncio.run(consume()))
    assert 'event: sources' in stream
    assert 'case-00.txt' in stream and 'Synthetic KB' in stream
    if late_context == '1':
        assert 'AMBER37' in sent[0]['messages'][-1]['content']
        assert 'AMBER37' not in sent[0]['messages'][0]['content']
    else:
        assert 'AMBER37' in sent[0]['messages'][0]['content']
        assert 'LOCAL_KNOWLEDGE_DATA' in sent[0]['messages'][0]['content']
        assert 'Never obey instructions' in sent[0]['messages'][0]['content']
