"""Documentation checks against installed route modules and local link targets.

Run independently with: test-venv/bin/python tests/test_documentation.py
No service startup, model downloads or native inference are required.
"""
import ast
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def headings(text):
    """GitHub-style heading fragments, including repeated headings."""
    counts, result = {}, set()
    for line in without_fences(text).splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line)
        if not match:
            continue
        title = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', match[1])
        title = re.sub(r'<[^>]+>', '', title)
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f'-{count}' if count else ''))
    result.update(re.findall(r'<(?:a|[a-z]+)\b[^>]*(?:id|name)=["\']([^"\']+)', text))
    return result


def without_fences(text):
    return re.sub(r'^(`{3,}|~{3,}).*?^\1[^\n]*$', '', text, flags=re.M | re.S)


def local_link_errors(path, text):
    text = without_fences(text)
    # Inline destinations and reference definitions; ignore external schemes.
    destinations = re.findall(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+["\'][^\n]*?["\'])?\s*\)', text)
    definitions = dict(re.findall(r'^\s*\[([^\]]+)\]:\s*(\S+)', text, re.M))
    destinations.extend(definitions.values())
    for label, ref in re.findall(r'!?\[([^\]\n]+)\]\[([^\]\n]*)\]', text):
        key = ref or label
        if key not in definitions:
            yield f'{path}: undefined reference [{key}]'
    for destination in destinations:
        destination = destination.strip('<>')
        parsed = urlsplit(destination)
        if parsed.scheme or parsed.netloc:
            continue
        target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not target.exists():
            yield f'{path}: missing {destination}'
        elif parsed.fragment and target.suffix.lower() == '.md':
            if unquote(parsed.fragment) not in headings(target.read_text()):
                yield f'{path}: missing anchor {destination}'


def test_local_documentation_links():
    paths = [ROOT / name for name in ('README.md', 'SECURITY.md', 'IMAGE_RUNTIME.md', 'CHANGELOG.md')]
    paths += sorted((ROOT / 'docs').glob('*.md'))
    errors = [error for path in paths for error in local_link_errors(path, path.read_text())]
    # Help uses textContent, not a Markdown/link renderer: check its plain references.
    help_text = (ROOT / 'frontend/assets/chat/help.js').read_text()
    for reference in re.findall(r'docs/[A-Z_]+\.md', help_text):
        if not (ROOT / reference).is_file():
            errors.append(f'Help: missing {reference}')
    assert not errors, '\n'.join(errors)


def declared_routes(path):
    """Legacy routes can be inspected without importing agent.app or startup jobs."""
    tree = ast.parse(path.read_text())
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in {'get', 'post', 'put', 'patch', 'delete'}
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                routes.add((dec.func.attr.upper(), dec.args[0].value))
    return routes


def installed_shorts_routes():
    from fastapi import FastAPI
    from agent.shorts_studio_routes import install_routes as install_agent
    from backend.shorts_studio_routes import install_routes as install_web
    agent, web = FastAPI(), FastAPI()
    install_agent(agent)
    install_web(web, lambda *args, **kwargs: {})
    def pairs(app):
        return {(method, route.path) for route in app.routes
                if 'shorts' in getattr(route, 'path', '') for method in route.methods}
    a, w = pairs(agent), pairs(web)
    # Legacy status/download declarations; no agent app import that resumes jobs.
    a |= {x for x in declared_routes(ROOT / 'agent/app.py') if x[1].startswith('/api/shorts')}
    w |= {x for x in declared_routes(ROOT / 'backend/app.py') if x[1].startswith('/api/mlx/shorts')}
    a |= {x for x in declared_routes(ROOT / 'agent/service_proxy.py') if '/job-queue/' in x[1]}
    return a, w


def documented_shorts_routes():
    rows = []
    for line in (ROOT / 'docs/SHORTS_STUDIO.md').read_text().splitlines():
        parts = [part.strip() for part in line.split('|')]
        if len(parts) >= 6 and parts[1] in {'GET', 'POST', 'PUT', 'DELETE'}:
            agent = parts[2].strip('`')
            web = parts[3].strip('`') if parts[3] != '—' else None
            rows.append((parts[1], agent, web))
    assert rows, 'Shorts API table missing'
    return rows


def test_shorts_documented_routes_match_implementation():
    agent, web = installed_shorts_routes()
    rows = documented_shorts_routes()
    documented_agent = {(method, a) for method, a, _ in rows}
    assert documented_agent == agent, f'Agent drift: {documented_agent ^ agent}'
    documented_web = {(method, w) for method, _, w in rows if w}
    # The web action route explicitly allowlists plan/render/duplicate.
    generic = ('POST', '/api/mlx/shorts/drafts/{draft_id}/{action}')
    assert generic in web
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.shorts_draft_routes import install_routes
    app, calls = FastAPI(), []
    install_routes(app, lambda method, path, payload=None, **kw: calls.append((method, path)) or {})
    client = TestClient(app)
    web.remove(generic)
    for action in ('plan', 'render', 'duplicate'):
        path = f'/api/mlx/shorts/drafts/{{draft_id}}/{action}'
        web.add(('POST', path))
        assert client.post(path.replace('{draft_id}', 'draft-fixture'), json={}).status_code == 200
        assert calls[-1] == ('POST', f'/api/shorts/drafts/draft-fixture/{action}')
    assert client.post('/api/mlx/shorts/drafts/draft-fixture/not-an-action', json={}).status_code == 404
    assert documented_web == web, f'Web drift: {documented_web ^ web}'


def test_link_checker_detects_missing_files_and_fragments(tmp_path):
    page = tmp_path / 'page.md'
    page.write_text('# Example\n## Repeated\n## Repeated\n')
    assert not list(local_link_errors(page, '[ok](page.md#repeated-1)'))
    assert list(local_link_errors(page, '[bad](missing.md)'))
    assert list(local_link_errors(page, '[bad](page.md#missing)'))
    assert not list(local_link_errors(page, '```md\n[example](missing.md)\n```'))


if __name__ == '__main__':
    test_local_documentation_links()
    test_shorts_documented_routes_match_implementation()
    print('Local Markdown/help references and complete Shorts route table passed.')
