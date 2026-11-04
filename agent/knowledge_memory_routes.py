"""Same-origin local APIs for paginated knowledge, revisions and safe restore."""
from fastapi import HTTPException
from agent import knowledge_memory as km, personal_memory as pm, memory_commands


def install_routes(app, chat_host=None):
    def controlled(call, *args, **kwargs):
        try: return call(*args, **kwargs)
        except KeyError as error: raise HTTPException(404, 'Memory not found') from error
        except (ValueError, TypeError) as error: raise HTTPException(422, str(error)) from error

    @app.get('/api/knowledge-memory/status')
    def status(): return km.stats()

    @app.get('/api/knowledge-memory/items')
    def items(kind: str = 'fact', query: str = '', category: str = '', project: str = '', since: float = 0, until: float = 0, offset: int = 0, limit: int = 30):
        return controlled(km.items, kind=kind, query=query, category_filter=category, project=project, since=since, until=until, offset=offset, limit=limit)

    @app.get('/api/knowledge-memory/similar')
    def similar(limit: int = 30): return km.similar_items(limit=limit)

    @app.get('/api/knowledge-memory/scopes')
    def scopes(): return {'scopes': km.scopes()}

    @app.post('/api/knowledge-memory/scopes')
    def set_scopes(payload: dict): return controlled(km.set_scopes, payload.get('scopes'))

    @app.get('/api/knowledge-memory/export')
    def export(): return km.export_data()

    @app.post('/api/knowledge-memory/import')
    def restore(payload: dict): return controlled(km.import_data, payload)

    @app.post('/api/knowledge-memory/merge')
    def merge(payload: dict):
        if not pm.enabled(): raise HTTPException(409, 'Personal memory is disabled')
        return controlled(km.merge, payload.get('ids'), payload.get('value'))

    @app.post('/api/knowledge-memory/pin/{fid}')
    def pin(fid: str, payload: dict):
        if not pm.enabled(): raise HTTPException(409, 'Personal memory is disabled')
        return controlled(km.pin, fid, payload.get('pinned'))

    @app.get('/api/knowledge-memory/history/{fid}')
    def history(fid: str):
        if not pm.enabled(): return {'items': []}
        with pm.LOCK, pm._connect() as conn:
            pm._schema(conn)
            root = pm._lineage(conn, fid)
            rows = conn.execute('SELECT f.* FROM facts f JOIN fact_lineage l ON l.fact_id=f.id WHERE l.root_id=? ORDER BY f.created_at', (root,)).fetchall()
            return {'items': [dict(r) for r in rows]}

    @app.delete('/api/knowledge-memory/episode/{eid}')
    def delete_episode(eid: str): return controlled(km.delete_episode, eid)

    @app.post('/api/knowledge-memory/command')
    def command(payload: dict):
        if not isinstance(payload.get('messages'), list): raise HTTPException(422, 'messages must be a list')
        return controlled(memory_commands.execute, payload['messages'], chat_id=payload.get('chat_id'), chat_host=chat_host) or {'action': 'none', 'persisted': False}
