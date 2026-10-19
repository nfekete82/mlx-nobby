"""Prevent scheduler FD exhaustion independently of garbage collection."""
import sqlite3

import pytest

from agent import automations, automation_notifications


@pytest.mark.parametrize('module', [automations, automation_notifications])
@pytest.mark.parametrize('fail', [False, True])
def test_transaction_closes_connection_and_preserves_commit_rollback(tmp_path, monkeypatch, module, fail):
    monkeypatch.setattr(automations, 'ROOT', tmp_path)
    monkeypatch.setattr(automations, 'AUTOMATIONS_DB', tmp_path / 'automations.db')
    with automations._connect() as setup:
        setup.execute('CREATE TABLE lifecycle (value TEXT)')
    handles = []  # Retain references: closure must not rely on GC.
    for _ in range(140):
        try:
            with module._connect() as connection:
                handles.append(connection)
                connection.execute("INSERT INTO lifecycle VALUES ('test')")
                if fail:
                    raise RuntimeError('rollback')
        except RuntimeError:
            pass
    for connection in handles:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
    with automations._connect() as check:
        assert check.execute('SELECT COUNT(*) FROM lifecycle').fetchone()[0] == (0 if fail else 140)
