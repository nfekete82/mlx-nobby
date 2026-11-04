"""Backup validation uses synthetic chats and a live synthetic WAL database."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('backup_local_state',
    Path(__file__).resolve().parents[1] / 'scripts/backup-local-state.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_backup_restores_committed_wal_pages_and_chat_files(tmp_path):
    root = tmp_path / 'source'
    chats = root / 'chats'
    chats.mkdir(parents=True)
    (chats / 'synthetic.json').write_text(json.dumps({'id': 'synthetic', 'messages': []}))
    connection = sqlite3.connect(root / 'memory.db')
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE facts (value TEXT)')
        connection.execute("INSERT INTO facts VALUES ('SYNTHETIC_BACKUP_FACT')")
        connection.commit()
        destination = tmp_path / 'backup'
        backup.create(destination, {'mlx-web': root})
        assert backup.verify(destination) == {'verified': True, 'files': 2, 'databases': 1}
        assert destination.stat().st_mode & 0o777 == 0o700
        db = destination / 'data/mlx-web/memory.db'
        with sqlite3.connect(db) as restored:
            assert restored.execute('SELECT value FROM facts').fetchone()[0] == 'SYNTHETIC_BACKUP_FACT'
        assert db.stat().st_mode & 0o777 == 0o600
        db.write_bytes(b'corrupt')
        with pytest.raises(RuntimeError, match='checksum'):
            backup.verify(destination)
    finally:
        connection.close()


def test_private_backup_rejects_git_destinations_and_changing_sources(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    (root / 'chats').mkdir(parents=True)
    file = root / 'chats/example.json'
    file.write_text('{}')
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').write_text('gitdir: example')
    with pytest.raises(ValueError, match='Git worktrees'):
        backup.create(repo / 'backup', {'mlx-web': root})
    copy = backup.shutil.copy2

    def changing(source, target):
        result = copy(source, target)
        file.write_text('{"changed": true}')
        return result

    monkeypatch.setattr(backup.shutil, 'copy2', changing)
    with pytest.raises(RuntimeError, match='Source changed'):
        backup.create(tmp_path / 'backup', {'mlx-web': root})
    assert not (tmp_path / 'backup/manifest.json').exists()


def test_external_sqlite_snapshot_does_not_replay_old_wal_sidecars(tmp_path):
    source = tmp_path / 'external'
    source.mkdir()
    connection = sqlite3.connect(source / 'eml.db')
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE uploads (id INTEGER)')
        connection.execute('INSERT INTO uploads VALUES (1)')
        connection.commit()
        destination = tmp_path / 'backup'
        backup.create(destination, {'extra-eml': source})
        assert backup.verify(destination)['databases'] == 1
        assert not list(destination.rglob('*-wal'))
        assert not list(destination.rglob('*-shm'))
    finally:
        connection.close()


def test_backup_includes_private_long_term_chat_memory_sources(tmp_path):
    root = tmp_path / "source"
    archived = root / "long-term-chat-memory" / "deleted-chat"
    archived.mkdir(parents=True)
    data = {"id": "deleted-chat", "messages": [{"role": "user", "content": "synthetic memory"}]}
    source = archived / "revision.json"
    source.write_text(json.dumps(data))
    destination = tmp_path / "backup"
    backup.create(destination, {"mlx-web": root})
    restored = destination / "data/mlx-web/long-term-chat-memory/deleted-chat/revision.json"
    assert restored.is_file()
    assert json.loads(restored.read_text()) == data
    assert restored.stat().st_mode & 0o777 == 0o600
    assert backup.verify(destination)["verified"] is True


def test_backup_changed_sources_reports_paths_without_contents(tmp_path):
    first = {
        str(tmp_path / "memory.sqlite3"): (32, 10),
        str(tmp_path / "old-chat.json"): (11, 5),
    }
    second = {
        str(tmp_path / "memory.sqlite3"): (34, 11),
        str(tmp_path / "new-chat.json"): (10, 6),
    }
    result = backup.changed_sources(first, second)
    assert result["changed_count"] == 3
    assert set(result["changed_paths"]) == set(first) | set(second)
    assert result["truncated"] is False
    assert "private contents" not in str(result)


def test_readonly_writer_diagnosis_is_non_destructive(tmp_path, monkeypatch):
    root = tmp_path / "source"
    chats = root / "chats"
    chats.mkdir(parents=True)
    file = chats / "fictional.json"
    file.write_text('{"id": "fictional"}')

    def synthetic_tick(_seconds):
        file.write_text('{"id": "fictional", "updated": true}')

    monkeypatch.setattr(backup.time, "sleep", synthetic_tick)
    result = backup.diagnose_writers({"mlx-web": root}, seconds=0)
    assert result["changed_count"] == 1
    assert result["changed_paths"] == [str(file)]
    assert file.read_text().endswith('true}')


def test_live_sqlite_wal_updates_do_not_reject_consistent_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "memory.db"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE facts (value TEXT)")
    writer.execute("INSERT INTO facts VALUES ('original')")
    writer.commit()
    destination = tmp_path / "backup"
    old_digest = backup.digest
    updated = False

    def update_source_during_snapshot_digest(path):
        nonlocal updated
        # Simulate an independent writer committing after SQLite backup()
        # completed but before the raw-file-change comparison.
        if not updated and path == destination / "data/mlx-web/memory.db":
            writer.execute("INSERT INTO facts VALUES ('newer')")
            writer.commit()
            updated = True
        return old_digest(path)

    monkeypatch.setattr(backup, "digest", update_source_during_snapshot_digest)
    try:
        backup.create(destination, {"mlx-web": root})
        assert updated
        assert backup.verify(destination)["verified"] is True
        with sqlite3.connect(destination / "data/mlx-web/memory.db") as restored:
            assert restored.execute("SELECT value FROM facts").fetchall() == [("original",)]
        assert writer.execute("SELECT count(*) FROM facts").fetchone()[0] == 2
    finally:
        writer.close()


def test_fingerprint_keeps_chat_edits_guarded_but_ignores_sqlite_wal(tmp_path):
    root = tmp_path / "source"
    (root / "chats").mkdir(parents=True)
    chat = root / "chats/source.json"
    chat.write_text("{}")
    db = root / "memory.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE notes (content TEXT)")
    files = backup.inventory({"mlx-web": root})
    baseline = backup.fingerprint(files, include_sqlite=False)
    db.write_bytes(db.read_bytes())  # SQLite file mtime changes without logical edits.
    assert backup.fingerprint(backup.inventory({"mlx-web": root}), include_sqlite=False) == baseline
    chat.write_text('{"changed": true}')
    assert backup.fingerprint(backup.inventory({"mlx-web": root}), include_sqlite=False) != baseline
