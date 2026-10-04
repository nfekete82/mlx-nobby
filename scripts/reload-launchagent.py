#!/usr/bin/env python3
"""Install a rendered LaunchAgent with bounded unload and transactional restore."""
import argparse
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
import time


class ReloadError(RuntimeError):
    pass


def install(domain, label, candidate, target, *, timeout=10):
    candidate, target = Path(candidate), Path(target)
    if candidate.is_symlink() or target.is_symlink():
        raise ReloadError('LaunchAgent files must not be symlinks')
    rendered = candidate.read_bytes()
    if plistlib.loads(rendered).get('Label') != label:
        raise ReloadError('Rendered LaunchAgent label mismatch')
    previous = target.read_bytes() if target.exists() else None
    if previous == rendered:
        candidate.unlink()
        return False
    if previous is not None and plistlib.loads(previous).get('Label') != label:
        raise ReloadError('Previous LaunchAgent label mismatch')
    service = f'{domain}/{label}'

    def run(*args):
        return subprocess.run(['launchctl', *args], capture_output=True, text=True, timeout=5)

    def loaded():
        result = run('print', service)
        if result.returncode == 113:  # launchctl: service not found
            return False
        if result.returncode:
            raise ReloadError(f'Cannot inspect {service}: {result.stderr.strip()}')
        match = re.search(r'^\s*path = (.+)$', result.stdout, re.MULTILINE)
        if not match or Path(match[1]).resolve() != target.resolve():
            raise ReloadError(f'Unexpected loaded service path for {service}')
        return True

    def unload():
        result = run('bootout', service)
        if result.returncode:
            raise ReloadError(f'bootout failed for {service}: {result.stderr.strip()}')
        deadline = time.monotonic() + timeout
        while loaded():
            if time.monotonic() >= deadline:
                raise ReloadError(f'Timed out waiting for {service} to be unloaded')
            time.sleep(0.05)

    def bootstrap():
        result = run('bootstrap', domain, str(target))
        if result.returncode:
            raise ReloadError(f'bootstrap failed for {service}: {result.stderr.strip()}')
        if not loaded():
            raise ReloadError(f'bootstrap did not load {service}')

    was_loaded = loaded()
    if was_loaded and previous is None:
        raise ReloadError('Loaded LaunchAgent has no previous configuration to restore')
    backup = None
    try:
        if was_loaded:
            fd, name = tempfile.mkstemp(prefix=f'.{target.name}.restore-', dir=target.parent)
            os.close(fd)
            backup = Path(name)
            shutil.copy2(target, backup)
            # bootout is asynchronous: do not publish/bootstrap the candidate
            # until launchd confirms the old service has actually disappeared.
            unload()
        if (target.read_bytes() if target.exists() else None) != previous:
            raise ReloadError('LaunchAgent configuration changed during reload')
        os.replace(candidate, target)
        if was_loaded:
            try:
                bootstrap()
            except (ReloadError, subprocess.TimeoutExpired) as error:
                try:
                    if loaded():
                        unload()  # remove only our verified partially loaded candidate
                    os.replace(backup, target)
                    backup = None
                    bootstrap()  # one restore attempt, never retry the candidate
                except (ReloadError, OSError, subprocess.TimeoutExpired) as restore_error:
                    raise ReloadError(f'{error}; restore failed: {restore_error}') from error
                raise ReloadError(f'{error}; previous configuration restored and loaded') from error
        if backup is not None:
            backup.unlink()
            backup = None
        return True
    finally:
        candidate.unlink(missing_ok=True)
        if backup is not None:
            # Preserve a recovery copy if the original file has not survived.
            if target.exists() and target.read_bytes() == previous:
                backup.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domain')
    parser.add_argument('label')
    parser.add_argument('candidate')
    parser.add_argument('target')
    args = parser.parse_args()
    try:
        changed = install(args.domain, args.label, args.candidate, args.target)
    except (ReloadError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Error: {error}\n')
    print(f'Installed: {args.target} ({"changed" if changed else "unchanged"})')


if __name__ == '__main__':
    main()
