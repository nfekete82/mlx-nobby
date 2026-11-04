#!/usr/bin/env python3
"""Back up quiesced local chats and SQLite stores; never uploads anything.

Stop every application writer before --create. --verify independently checks
hashes, SQLite integrity/counts and restore copies. Manifests stay private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

SQLITE_HEADER = b'SQLite format 3\x00'


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def connect_readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)


def database_summary(connection):
    integrity = connection.execute('PRAGMA integrity_check').fetchall()
    if integrity != [('ok',)]:
        raise RuntimeError('SQLite integrity check failed')
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts = {name: connection.execute(
        'SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
        for name in tables}
    schema = connection.execute(
        'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    return {'rows': counts, 'schema_sha256': hashlib.sha256(
        json.dumps(schema, sort_keys=True).encode()).hexdigest()}


def inventory(roots):
    files = []
    for label, root in roots.items():
        if not root.exists():
            continue
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('Symlinks in an application data root require explicit handling')
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(path.name.endswith(suffix) and Path(str(path)[:-len(suffix)]).is_file()
                   for suffix in ('-wal', '-shm', '-journal')):
                # The SQLite backup API folds committed WAL data into the main
                # snapshot; copying old sidecars beside it could replay it twice.
                continue
            with path.open('rb') as stream:
                is_sqlite = stream.read(16) == SQLITE_HEADER
            is_chat = label == 'mlx-web' and relative.parts[0] == 'chats'
            # Include all external EML data, not just its SQLite files.
            if is_sqlite or is_chat or label.startswith('extra-'):
                files.append((label, path, relative, is_sqlite))
    return files


def fingerprint(files):
    values = {}
    for label, path, relative, _ in files:
        for target in [path, Path(str(path) + '-wal')]:
            if target.exists():
                info = target.stat()
                values[str(target)] = (info.st_size, info.st_mtime_ns)
    return values


def require_private_destination(destination):
    destination = destination.resolve()
    for parent in [destination, *destination.parents]:
        if (parent / '.git').exists():
            raise ValueError('Private backups must be outside Git worktrees')
    return destination


def create(destination, roots):
    destination = require_private_destination(destination)
    if any(destination == root.resolve() or root.resolve() in destination.parents
           for root in roots.values()):
        raise ValueError('Backup destination must be outside the source data roots')
    files = inventory(roots)
    before = fingerprint(files)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(destination, 0o700)
    manifest = {'format': 1, 'roots': {k: str(v.resolve()) for k, v in roots.items()}, 'files': []}
    for label, source, relative, is_sqlite in files:
        target = destination / 'data' / label / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        summary = None
        if is_sqlite:
            reader = connect_readonly(source)
            writer = sqlite3.connect(target)
            try:
                # An explicit read transaction gives counts and backup the same
                # snapshot, including committed WAL pages.
                reader.execute('BEGIN')
                summary = database_summary(reader)
                reader.backup(writer)
            finally:
                writer.close()
                reader.close()
        else:
            shutil.copy2(source, target)
        os.chmod(target, 0o600)
        manifest['files'].append({'path': str(target.relative_to(destination)),
                                  'sha256': digest(target), 'sqlite': summary})
    if before != fingerprint(inventory(roots)):
        raise RuntimeError('Source changed while backing up; stop all writers and retry')
    manifest_path = destination / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(manifest_path, 0o600)
    verify(destination)
    return manifest


def verify(destination):
    destination = destination.resolve()
    manifest = json.loads((destination / 'manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='mlx-backup-restore-') as directory:
        for index, item in enumerate(manifest['files']):
            source = (destination / item['path']).resolve()
            if destination not in source.parents or source.is_symlink():
                raise ValueError('Invalid backup manifest path')
            if digest(source) != item['sha256']:
                raise RuntimeError('Backup checksum mismatch')
            restored = Path(directory) / str(index)
            shutil.copy2(source, restored)
            if digest(restored) != item['sha256']:
                raise RuntimeError('Restored file checksum mismatch')
            if item['sqlite'] is not None:
                connection = connect_readonly(restored)
                try:
                    if database_summary(connection) != item['sqlite']:
                        raise RuntimeError('Restored SQLite contents/schema differ')
                finally:
                    connection.close()
    return {'files': len(manifest['files']),
            'databases': sum(item['sqlite'] is not None for item in manifest['files']),
            'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--source-home', type=Path, default=Path.home())
    parser.add_argument('--extra-root', action='append', default=[], help='label=/local/path')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        result = verify(args.destination)
    else:
        roots = {'mlx-web': args.source_home / '.config/mlx-web',
                 'mlx-server': args.source_home / '.config/mlx-server'}
        for extra in args.extra_root:
            label, path = extra.split('=', 1)
            if not label.replace('-', '').isalnum():
                parser.error('Invalid extra-root label')
            roots['extra-' + label] = Path(path)
        create(args.destination, roots)
        result = verify(args.destination)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
