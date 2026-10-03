"""One pass through each official validation layer; no full Shorts render by default."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='Opt in to the expensive minimum 5-second Short')
    args = parser.parse_args()
    python = sys.executable
    steps = [
        ('Python and subtests', [python, '-m', 'pytest', '-q']),
        ('JavaScript', ['node', '--test', *map(str, sorted((ROOT / 'tests').glob('*.mjs')))]),
        ('Syntax / translations / metadata', [python, str(ROOT / 'tests/acceptance/validate.py')]),
        ('Dependencies', [python, '-m', 'pip', 'check']),
        ('Compose', ['docker', 'compose', 'config', '--quiet']),
        ('Docker', ['docker', 'compose', 'build', '--build-arg', 'MLX_NOBBY_BUILD_SHA=acceptance', 'mlx-web']),
        ('Diff', ['git', 'diff', '--check']),
        ('Browser acceptance', [python, '-m', 'pytest', '--e2e', 'tests/e2e', '-q']),
        ('Real acceptance', [python, str(ROOT / 'tests/acceptance/runner.py'), *(['--full'] if args.full else [])]),
    ]
    for label, command in steps:
        print('\n' + label, flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
