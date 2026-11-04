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
