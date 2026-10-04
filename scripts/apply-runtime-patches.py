#!/usr/bin/env python3
"""Apply a commit-bound patch series without accepting unrelated local changes."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


class PatchError(RuntimeError):
    pass


def apply_patches(runtime, commit, patch_root, *, check_state=False):
    runtime, patch_root = Path(runtime).resolve(), Path(patch_root).resolve()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise PatchError('Expected a full, lowercase upstream commit hash')
    if not (patch_root / commit).is_dir():
        raise PatchError('Missing patch directory for the expected upstream commit')

    def git(*args, env=None, data=None, check=True):
        result = subprocess.run(['git', '-C', str(runtime), *args], env=env,
                                input=data, capture_output=True)
        if check and result.returncode:
            raise PatchError(result.stderr.decode(errors='replace').strip() or 'Git validation failed')
        return result

    def verify_pin():
        if git('rev-parse', 'HEAD').stdout.decode().strip() != commit:
            raise PatchError('Upstream HEAD does not match the expected pin')

    verify_pin()
    if git('diff', '--cached', '--quiet', commit, '--', check=False).returncode:
        raise PatchError('Unexpected staged changes in runtime checkout')
    patches = sorted((patch_root / commit).glob('*.patch'))
    if any(p.is_symlink() or not p.is_file() for p in patches):
        raise PatchError('Patch files must be regular files, not symlinks')
    if not patches:
        if git('status', '--porcelain', '--untracked-files=all').stdout:
            raise PatchError('Unexpected dirty runtime checkout')
        print('Upstream pin verified; runtime patches: 0')
        return

    # Only this disposable index is changed during series preflight. The actual
    # runtime index and worktree are untouched, including on a later patch failure.
    with tempfile.TemporaryDirectory(prefix='mlx-runtime-patches-') as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git('read-tree', commit, env=env)
        for patch in patches:
            content = patch.read_bytes()
            verify_pin()
            git('apply', '--cached', '--check', '--whitespace=error', '-', env=env, data=content)
            git('apply', '--cached', '--whitespace=error', '-', env=env, data=content)
        expected_tree = git('write-tree', env=env).stdout.decode().strip()
        matches = git('diff', '--quiet', '--', env=env, check=False).returncode == 0
        extra = git('ls-files', '--others', '--exclude-standard', '-z', env=env).stdout
        if matches and not extra:
            print(f'Upstream pin verified; runtime patches: {len(patches)} already applied')
            return
        if git('status', '--porcelain', '--untracked-files=all').stdout:
            raise PatchError('Unexpected dirty or partial runtime patch state')
        combined = git('diff', '--binary', '--full-index', commit, expected_tree, '--').stdout
        verify_pin()
        git('apply', '--check', '--whitespace=error', '-', data=combined)
        if check_state:
            print(f'Upstream pin verified; runtime patches: {len(patches)} ready')
            return
        verify_pin()
        git('apply', '--whitespace=error', '-', data=combined)
        if git('diff', '--quiet', '--', env=env, check=False).returncode or git(
                'ls-files', '--others', '--exclude-standard', '-z', env=env).stdout:
            raise PatchError('Runtime patch application did not produce the expected state')
    print(f'Upstream pin verified; runtime patches: {len(patches)} applied')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime')
    parser.add_argument('commit')
    parser.add_argument('patch_root')
    parser.add_argument('--check-state', action='store_true', help='Validate without modifying worktree')
    args = parser.parse_args()
    try:
        apply_patches(args.runtime, args.commit, args.patch_root, check_state=args.check_state)
    except (PatchError, OSError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
