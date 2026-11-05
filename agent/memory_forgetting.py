"""Explicit original-source deletion with local source verification and upload guards."""
from __future__ import annotations
import copy
import re
import time
from agent import knowledge_memory as km, personal_memory as pm, chat_archive

ORIGINAL = re.compile(r'^(?:auch\s+)?(?:die\s+)?(?:ursprünglichen?\s+chat[- ]nachrichten|original\s+chat\s+messages)\s*(?:über|zu|about|:)?\s*(.+)$', re.I | re.S)


def filter_deleted_originals(chat):
    """A stale browser save or old source import cannot restore explicitly erased text."""
    if not pm.DB_PATH.exists(): return chat
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        denied = {row[0] for row in conn.execute("SELECT key FROM memory_tombstones WHERE scope='original'")}
    if denied:
        chat['messages'] = [m for m in chat.get('messages', []) if not isinstance(m, dict)
            or not isinstance(m.get('content'),str) or km.digest(m['content']) not in denied]
    return chat


def forget_originals(target, *, chat_host):
    if chat_host is None:
        return {'persisted':False,'action':'unavailable','text':'Die Originalquellen können über diesen Endpunkt nicht sicher bearbeitet werden. Es wurde nichts an Original-Chats geändert.'}
    target = target.strip(' .')
    if len(km.normalized(target)) < 3:
        return {'persisted':False,'action':'clarify','text':'Bitte nenne die konkrete gespeicherte Aussage, deren Original-Nachrichten gelöscht werden sollen.'}
    # Match the write path's lock order. Verify every source before any deletion.
    with chat_host.CHATS_LOCK:
        matches = [r for r in pm.list_facts(target)]
        if not matches:
            return {'persisted':False,'action':'not_found','text':'Keine passende Erinnerung mit Originalquelle gefunden; es wurde nichts gelöscht.'}
        refs = []
        with pm.LOCK, pm._connect() as conn:
            pm._schema(conn)
            for row in matches: refs.extend(km._sources(conn,'fact',row['id']))
        originals = {}
        for ref in refs:
            if ref.get('role') == 'manual': continue
            cid, ordinal = ref['chat_id'], ref['ordinal']
            current = originals.setdefault(cid, {'chat':chat_host.read_chat(cid),'ordinals':set()})
            source = current['chat']
            if not source or not 0 <= ordinal < len(source.get('messages',[])):
                return {'persisted':False,'action':'clarify','text':'Eine Originalquelle hat sich geändert. Bitte prüfe die Quellenanzeige, bevor Originale gelöscht werden.'}
            message = source['messages'][ordinal]
            if km.digest(message.get('content','')) != ref['digest']:
                return {'persisted':False,'action':'clarify','text':'Eine Originalnachricht wurde bearbeitet. Die Quellen stimmen nicht mehr überein; es wurde nichts gelöscht.'}
            current['ordinals'].add(ordinal)
            # Replies to the erased turn may repeat its personal content.
            for n in range(ordinal+1,len(source['messages'])):
                if source['messages'][n].get('role') == 'user': break
                current['ordinals'].add(n)
        if not originals:
            return {'persisted':False,'action':'not_found','text':'Diese Erinnerung hat keine überprüfbare ursprüngliche Chat-Nachricht.'}
        with pm.LOCK, pm._connect() as conn:
            pm._schema(conn)
            for entry in originals.values():
                for n in entry['ordinals']:
                    content = entry['chat']['messages'][n].get('content')
                    if isinstance(content,str):
                        conn.execute('INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?)', ('original',km.digest(content),time.time()))
        for row in matches: pm.delete_fact(row['id'])
        removed = 0
        try:
            for cid, entry in originals.items():
                updated = copy.deepcopy(entry['chat'])
                updated['messages'] = [m for n,m in enumerate(updated['messages']) if n not in entry['ordinals']]
                updated['updated'] = max(time.time(), float(updated.get('updated') or 0) + .001)
                # This explicit scope removes old derived transcript revisions too.
                chat_archive.remove_chat(cid)
                chat_host.write_chat(updated)
                stored = chat_host.read_chat(cid)
                if not stored or stored['messages'] != updated['messages']:
                    raise RuntimeError('Original deletion verification failed')
                removed += len(entry['ordinals'])
        except Exception as error:
            km.diagnose('original_deletion',error)
            return {'persisted':False,'action':'partial_error','text':'Die Löschsperre ist gespeichert, aber das Löschen aller Originalquellen konnte nicht bestätigt werden. Bitte prüfe die Gedächtnisdiagnose.'}
    return {'persisted':True,'action':'forgotten_originals','removed_messages':removed,
        'text':f'{removed} ursprüngliche Chat-Nachricht(en) und zugehörige aktive Erinnerungen wurden lokal entfernt. Alte Browser-Speicherstände dürfen die gelöschten Texte nicht wiederherstellen. Externe Sicherungen bleiben separat.'}


def purge_derived_transcripts(refs):
    """Erase selected indexed turns/replies/revisions while preserving source JSON."""
    if not chat_archive.DB_PATH.exists(): return
    with chat_archive.LOCK,chat_archive._connect() as conn:
        chat_archive._schema(conn)
        for ref in refs:
            cid,ordinal=ref['chat_id'],ref['ordinal']
            next_user=conn.execute("SELECT MIN(ordinal) FROM archive_messages WHERE chat_id=? AND ordinal>? AND role='user'",(cid,ordinal)).fetchone()[0]
            end=next_user if next_user is not None else 2**63-1
            for table in ('archive_messages','archive_activity','archive_activity_details','archive_revisions'):
                conn.execute('DELETE FROM '+table+' WHERE chat_id=? AND ordinal>=? AND ordinal<?',(cid,ordinal,end))
        conn.execute("INSERT INTO archive_fts(archive_fts) VALUES('rebuild')")
