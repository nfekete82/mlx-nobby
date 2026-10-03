"""Existing CI syntax/JSON/i18n/shell/plist/help checks for the local release gate."""
import json
from pathlib import Path
import py_compile
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for name in files:
        path = ROOT / name
        if name.endswith('.py'):
            py_compile.compile(str(path), doraise=True)
        elif name.endswith('.json'):
            json.loads(path.read_text())
        elif name.startswith('frontend/') and name.endswith('.js'):
            run(['node', '--check', name])
        elif name.startswith('scripts/') and (name.endswith('.sh') or name in
                {'scripts/mlx', 'scripts/mlx-server-start', 'scripts/setup-ltx-video', 'scripts/setup-ltx-video-mlx'}):
            run(['bash', '-n', name])
        elif name.startswith('launchd/templates/') and name.endswith('.plist.template'):
            run(['plutil', '-lint', name])
    run([sys.executable, 'scripts/i18n-audit.py'])
    run([sys.executable, 'tests/test_documentation.py'])
    run(['bash', 'scripts/mlx', 'help'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
