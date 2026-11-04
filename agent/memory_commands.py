"""Deterministic local memory controls for real chat requests, never archived text."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta

from agent import knowledge_memory as km, memory_dashboard, personal_memory as pm

_REMEMBER = re.compile(r'^\s*(?:bitte\s+)?(?:merk(?:e)?\s+dir|speicher(?:e)?\s+dir|remember)\s*[:,]?\s*(.+)$', re.I | re.S)
_PREVIOUS = re.compile(r'^(?:das|dies|it|that)(?:\s+(?:bitte|unbedingt|dauerhaft|please))*[.!]?$', re.I)
_FORGET = re.compile(r'^\s*(?:bitte\s+)?(?:vergiss|forget)\s+(.+)$', re.I | re.S)
_EXAMPLE = re.compile(r'^\s*(?:das\s+war\s+nur\s+ein\s+beispiel|that\s+was\s+(?:just\s+)?an\s+example)', re.I)
_CORRECT = re.compile(r'^\s*(?:das\s+stimmt\s+nicht\s+mehr|that\s+is\s+no\s+longer\s+true)[.!,:;\s]*(?:stattdessen|instead)\s*[:,]?\s*(.+)$', re.I | re.S)
_TODAY = re.compile(r'^\s*(?:was\s+hast\s+du\s+dir\s+(?:heute|gestern)\s+gemerkt|what\s+did\s+you\s+remember\s+(?:today|yesterday))\s*[?!.]*$', re.I)


def _reply(text, *, persisted=False, action='', **extra):
    return {'text': text, 'persisted': persisted, 'action': action, **extra}


def execute(messages, *, chat_id=None, chat_host=None):
    """Return a factual receipt or None; only the current user turn is executable."""
    if not isinstance(messages, list): return None
    users = [(i, m['content']) for i, m in enumerate(messages) if isinstance(m, dict) and m.get('role') == 'user' and isinstance(m.get('content'), str)]
    if not users: return None
    ordinal, text = users[-1]
    remember, forget, correction = _REMEMBER.match(text), _FORGET.match(text), _CORRECT.match(text)
    example, today = _EXAMPLE.match(text), _TODAY.match(text)
    if not any((remember, forget, correction, example, today)): return None
    de = not re.match(r'^\s*(?:remember|forget|that|what)', text, re.I)
    if memory_dashboard.paused():
        return _reply('Das Gedächtnis ist pausiert. Es wurde nichts geändert.' if de else 'Memory is paused. Nothing was changed.', action='paused')
    if not pm.enabled():
        return _reply('Das persönliche Gedächtnis ist deaktiviert. Bitte aktiviere es zuerst in den Gedächtniseinstellungen; es wurde nichts gespeichert.' if de else 'Personal memory is disabled. Enable it in memory settings first; nothing was saved.', action='disabled')
    if forget:
        from agent import memory_forgetting
        original = memory_forgetting.ORIGINAL.match(forget[1])
        if original:
            return memory_forgetting.forget_originals(original[1], chat_host=chat_host)
    previous = users[-2][1] if len(users) > 1 else None
    # A source ID is necessary for a reliable, retry-safe command receipt.
    if not isinstance(chat_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', chat_id):
        return _reply('Die Chat-Quellenreferenz fehlt. Es wurde nichts geändert.' if de else 'The chat source reference is missing. Nothing was changed.', action='missing_source')
    # Prompt-only system messages are not part of the authoritative chat ordinal.
    ordinal = sum(1 for m in messages[:ordinal] if isinstance(m, dict) and m.get('role') != 'system')
    receipt = km.digest(chat_id + '\0' + str(ordinal) + '\0' + text)
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        conn.execute('CREATE TABLE IF NOT EXISTS memory_command_receipts(id TEXT PRIMARY KEY,result TEXT NOT NULL)')
        existing = conn.execute('SELECT result FROM memory_command_receipts WHERE id=?', (receipt,)).fetchone()
        if existing: return json.loads(existing[0])
        if conn.execute('SELECT 1 FROM excluded WHERE chat_id=?', (chat_id,)).fetchone():
            return _reply('Dieser Chat ist vom Gedächtnis ausgeschlossen.' if de else 'This chat is excluded from memory.', action='excluded')
        if today:
            day = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            if re.search(r'gestern|yesterday', text, re.I): day -= timedelta(days=1)
            rows = conn.execute("SELECT id,value FROM facts WHERE status='active' AND created_at>=? AND created_at<? ORDER BY created_at", (day.timestamp(), (day + timedelta(days=1)).timestamp())).fetchall()
            lines = [f"- {r['value']} [Erinnerung {r['id']}]" for r in rows[:100]]
            return _reply(('Neue gespeicherte Erinnerungen: ' if de else 'New stored memories: ') + str(len(rows)) + '\n' + '\n'.join(lines) + ('\nWeitere Einträge findest du im Gedächtnis mit Datumsfilter.' if len(rows) > 100 else ''), action='inventory')
        if remember:
            value = remember[1].strip()
            if _PREVIOUS.fullmatch(value):
                if not previous:
                    return _reply('Welche Aussage soll ich mir merken?' if de else 'Which statement should I remember?', action='clarify')
                value = previous
            if km._SECRET.search(value) or km._NO_LEARN.search(value):
                return _reply('Diese Angabe wurde nicht als persönliche Erinnerung gespeichert.' if de else 'This statement was not stored as personal memory.', action='rejected')
            if len(value) > pm.MAX_VALUE:
                # Explicit long stories receive source-linked notes in lossless parts.
                parts = [value[a:b] for a, b in km.chunks(value, size=450)]
            else: parts = [value]
            if _PREVIOUS.fullmatch(remember[1].strip()):
                previous_ordinal = max(0, ordinal - 1)
                # Use the actual preceding user ordinal, allowing intervening assistant turns.
                if len(users) > 1:
                    previous_ordinal = sum(1 for m in messages[:users[-2][0]] if isinstance(m, dict) and m.get('role') != 'system')
                sid = km.source(conn, chat_id, previous_ordinal, value)
            else:
                sid = km.source(conn, chat_id, ordinal, text)
            ids = []
            for part in parts:
                field = 'notiz.' + km.digest(km.normalized(part))[:16]
                event = pm._propose(conn, 'ich', field, part, True, chat_id, ordinal, explicit=True)
                fid = event.get('fact_id')
                if fid:
                    from agent import semantic_personal_memory as smart
                    conn.execute('UPDATE fact_metadata SET kind=? WHERE fact_id=?', ('assumption' if smart._HYPOTHETICAL.search(part) else 'fact', fid))
                    km.annotate(conn, fid, subject='ich', field=field, pinned=bool(re.search(r'unbedingt|important', text, re.I)), sid=sid, evidence=part)
                    ids.append(fid)
            if not ids:
                return _reply('Diese Erinnerung ist durch eine Löschregel gesperrt und wurde nicht wiederhergestellt.' if de else 'A deletion rule blocks this memory; it was not restored.', action='excluded')
            result = _reply(('Dauerhaft lokal gespeichert. ' if de else 'Permanently saved locally. ') + f"{len(ids)} " + ('Erinnerung(en); Quellenbezug und Speicherung bestätigt.' if de else 'memory item(s); source and persistence confirmed.'), persisted=True, action='remembered', fact_ids=ids)
        elif correction:
            value = correction[1].strip()
            if not value or len(value) > pm.MAX_VALUE or km._SECRET.search(value):
                return _reply('Die Korrektur wurde nicht gespeichert. Bitte nenne eine konkrete Aussage.' if de else 'The correction was not saved. Please provide a specific statement.', action='clarify')
            # Only an unambiguous existing attribute can be corrected automatically.
            extracted = pm._extract(value)
            candidates = []
            for subject, field, val, sensitive in extracted:
                row = pm._fact_for(conn, subject, field)
                if row: candidates.append((row, val))
            if not candidates and previous:
                terms = km.normalized(previous)
                for row in conn.execute("SELECT * FROM facts WHERE status='active'"):
                    if km.normalized(row['value']) in terms: candidates.append((row, value))
            unique = {r['id']: (r, v) for r, v in candidates}
            if len(unique) != 1:
                return _reply('Welche gespeicherte Erinnerung soll ich korrigieren? Bitte nenne die bisherige Aussage und den neuen Wert.' if de else 'Which stored memory should I correct? Specify the previous statement and new value.', action='clarify')
            old, val = next(iter(unique.values()))
            result_event = pm._propose(conn, old['subject'], old['field'], val, bool(old['sensitive']), chat_id, ordinal, explicit=True)
            if not result_event.get('fact_id'):
                return _reply('Die Korrektur wurde durch eine Löschregel verhindert.' if de else 'A deletion rule blocked the correction.', action='excluded')
            sid = km.source(conn, chat_id, ordinal, text, message_key='command:' + receipt)
            km.annotate(conn, result_event['fact_id'], subject=old['subject'], field=old['field'], sid=sid, evidence=value)
            result = _reply('Lokal korrigiert. Die frühere Version bleibt in der Änderungshistorie.' if de else 'Corrected locally. The previous version remains in history.', persisted=True, action='corrected', fact_id=result_event['fact_id'])
        else:
            if example:
                if not previous: return _reply('Es ist keine vorherige Aussage zugeordnet.' if de else 'No preceding statement is available.', action='clarify')
                target, scope = previous, 'active'
            else:
                target = forget[1].strip(' .')
                match = re.match(r'(?:nur\s+)?(?:die\s+)?(?:aktive\s+erinnerung|active\s+memory|abgeleiteten?\s+daten|derived\s+data)\s*(?:über|zu|an|about|:)?\s*(.+)', target, re.I | re.S)
                if not match:
                    return _reply('Was soll gelöscht werden: nur die aktive Erinnerung, alle abgeleiteten Daten zum Thema oder auch die ursprünglichen Chat-Nachrichten? Bitte nenne den Umfang und die konkrete Aussage.' if de else 'What should be deleted: the active memory, all derived data about the topic, or the original chat messages too? Specify the scope and statement.', action='clarify')
                target, scope = match[1].strip(), ('derived' if re.search(r'abgeleitet|derived',forget[1],re.I) else 'active')
            if len(km.normalized(target)) < 3:
                return _reply('Bitte nenne die konkrete Erinnerung.' if de else 'Specify the memory.', action='clarify')
            rows = conn.execute("SELECT * FROM facts WHERE status='active'").fetchall()
            matching = [r for r in rows if km.normalized(target) in km.normalized(r['value']) or (example and km.normalized(r['value']) in km.normalized(target))]
            if not matching and not example:
                return _reply('Keine passende aktive Erinnerung gefunden; es wurde nichts gelöscht.' if de else 'No matching active memory found; nothing was deleted.', action='not_found')
            if scope == 'derived':
                from agent import memory_forgetting
                refs = [ref for row in matching for ref in km._sources(conn,'fact',row['id'])]
                memory_forgetting.purge_derived_transcripts(refs)
            for row in matching:
                # Same transaction, including lineage and durable tombstones.
                root = pm._lineage(conn, row['id'])
                revisions = conn.execute('SELECT f.id,f.subject,f.field FROM facts f JOIN fact_lineage l ON l.fact_id=f.id WHERE l.root_id=?', (root,)).fetchall()
                for rev in revisions:
                    km.forget(conn, rev['id'])
                    conn.execute('INSERT OR IGNORE INTO forgotten VALUES(?,?)', (rev['subject'], rev['field']))
                    conn.execute('DELETE FROM facts WHERE id=?', (rev['id'],))
            km.purge_orphans(conn)
            if example:
                # Block all source versions of the hypothetical preceding turn.
                for src in conn.execute('SELECT id FROM memory_sources WHERE chat_id=? AND digest=?', (chat_id, km.digest(previous))).fetchall(): km.forget_source(conn, src['id'])
                sid = km.source(conn, chat_id, max(0, ordinal-1), previous)
                km.forget_source(conn, sid)
            result = _reply(('Abgeleitete Gesprächsdaten entfernt. ' if scope == 'derived' and de else '') + ('Aus dem aktiven persönlichen Gedächtnis entfernt und gegen automatische Wiederherstellung gesperrt. Die Original-Chats bleiben erhalten.' if de else 'Removed from active personal memory and blocked from automatic restoration. Original chats are preserved.'), persisted=True, action='forgotten', removed=len(matching))
        conn.execute('INSERT INTO memory_command_receipts VALUES(?,?)', (receipt, json.dumps(result, ensure_ascii=False)))
    # The connection has committed and closed before success reaches the caller.
    return result
