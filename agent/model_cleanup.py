"""Restricted local-model deletion; callers hold the model/runtime lock."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import stat
import uuid

from fastapi import HTTPException


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def local_model_path(repo, root):
    path = Path(repo)
    if not path.is_absolute() or ".." in path.parts:
        raise HTTPException(400, "Nur absolute lokale Modellpfade ohne Traversal sind erlaubt.")
    # Do not resolve symlinks here: each component is opened with O_NOFOLLOW.
    if path == root or root not in path.parents:
        raise HTTPException(403, "Modell liegt außerhalb des erlaubten Modellbereichs.")
    if any(part.startswith('.') for part in path.relative_to(root).parts):
        raise HTTPException(403, "Versteckte Modell- oder Bereinigungsordner sind geschützt.")
    return path


@contextmanager
def directory_fd(path):
    """Open every component from / without following symlinks (including parents)."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def delete_local_model(alias, models, root, protected_paths, roles, remove_alias, restore_alias):
    matches = [item for item in models if item['alias'] == alias]
    if not matches:
        raise HTTPException(404, "Unbekanntes Modell-Alias: " + alias)
    if len(matches) != 1:
        raise HTTPException(409, "Mehrdeutiger Alias; bitte zuerst die Konfiguration korrigieren.")
    selected = matches[0]
    if not selected.get('local'):
        raise HTTPException(400, "Nur lokale Modelle können mit dieser Aktion gelöscht werden.")
    path = local_model_path(selected['repo'], root)
    canonical = path.resolve()
    for protected in protected_paths:
        if protected and Path(protected).is_absolute() and overlaps(canonical, Path(protected).resolve()):
            raise HTTPException(409, "Das aktive oder von einem Dienst verwendete Modell ist geschützt.")
    assigned = [role for role, value in roles.items() if value == alias]
    if assigned:
        raise HTTPException(409, "Modell ist Rollen zugeordnet: " + ', '.join(assigned) +
                            ". Bitte die Zuordnung zuerst unter Modellrollen ändern.")
    for item in models:
        if item is not selected and Path(item['repo']).is_absolute():
            if overlaps(canonical, Path(item['repo']).resolve()):
                raise HTTPException(409, "Modellpfad wird auch von Alias „" + item['alias'] + "“ verwendet.")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise HTTPException(503, "Diese Python-Plattform unterstützt keine sichere Verzeichnislöschung.")

    try:
        with directory_fd(path.parent) as parent_fd:
            model_fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                original = os.fstat(model_fd)
                config = os.stat('config.json', dir_fd=model_fd, follow_symlinks=False)
                if not stat.S_ISREG(config.st_mode):
                    raise HTTPException(403, "Kein reguläres config.json im Modellordner.")
                # Private sibling prevents replacement between validation and recursive removal.
                staging = '.nobbymlx-delete-' + uuid.uuid4().hex
                os.mkdir(staging, mode=0o700, dir_fd=parent_fd)
                stage_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                moved = False
                alias_removed = False
                try:
                    os.rename(path.name, 'model', src_dir_fd=parent_fd, dst_dir_fd=stage_fd)
                    moved = True
                    staged = os.stat('model', dir_fd=stage_fd, follow_symlinks=False)
                    if (original.st_dev, original.st_ino) != (staged.st_dev, staged.st_ino):
                        raise HTTPException(409, "Modellordner wurde während der Prüfung verändert.")
                    alias_removed = True
                    remove_alias(alias)
                    shutil.rmtree('model', dir_fd=stage_fd)
                    moved = False
                except Exception:
                    # Preserve remaining files and restore the manager alias on partial failure.
                    if moved:
                        if os.path.lexists(path):
                            raise HTTPException(500, "Löschung fehlgeschlagen; Restdaten verbleiben in " +
                                                str(path.parent / staging) + ". Pfad wurde zwischenzeitlich belegt.")
                        os.rename('model', path.name, src_dir_fd=stage_fd, dst_dir_fd=parent_fd)
                    if alias_removed:
                        restore_alias(alias, selected['repo'])
                    raise
                finally:
                    os.close(stage_fd)
                    try:
                        os.rmdir(staging, dir_fd=parent_fd)
                    except OSError:
                        pass  # Never recursively remove unverified leftovers.
            finally:
                os.close(model_fd)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(404, "Modellordner oder config.json nicht gefunden; Alias bleibt erhalten.") from exc
    except OSError as exc:
        raise HTTPException(403 if exc.errno in {1, 13, 20, 40, 62} else 500,
                            "Modell konnte nicht vollständig gelöscht werden (Pfad/Berechtigung/Symlink). "
                            "Alias und verbliebene Dateien wurden soweit möglich wiederhergestellt.") from exc
    return {'ok': True, 'alias': alias, 'repo': selected['repo']}
