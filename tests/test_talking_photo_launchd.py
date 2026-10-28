"""Exercise the installer's actual Agent environment renderer without launchctl."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


def test_agent_installer_preserves_seed_and_explicit_environment_overrides():
    source = Path('scripts/install-launchd.sh').read_text()
    block = source.split('= "de.nobby.mlx-agent.plist.template" ]; then', 1)[1]
    code = block.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, previous = root / 'candidate.plist', root / 'previous.plist'
        previous.write_bytes(plistlib.dumps({'EnvironmentVariables': {
            'LTX_TALKING_PHOTO_SEED': '1337', 'LTX_TALKING_PHOTO_DEBUG': '1'}}))
        baseline = {'EnvironmentVariables': {'PATH': '/usr/bin'}, 'Label': 'de.nobby.mlx-agent'}
        candidate.write_bytes(plistlib.dumps(baseline))
        env = {k:v for k,v in os.environ.items() if not k.startswith('LTX_TALKING_PHOTO_')}
        subprocess.run([sys.executable, '-', str(candidate), str(previous)], input=code,
                       text=True, env=env, check=True)
        rendered = plistlib.loads(candidate.read_bytes())
        assert rendered['EnvironmentVariables'] == {
            'PATH': '/usr/bin', 'LTX_TALKING_PHOTO_SEED': '1337', 'LTX_TALKING_PHOTO_DEBUG': '1'}
        candidate.write_bytes(plistlib.dumps(baseline))
        env.update(LTX_TALKING_PHOTO_SEED='42', LTX_TALKING_PHOTO_DEBUG_ROOT='/tmp/ltx-debug')
        subprocess.run([sys.executable, '-', str(candidate), str(previous)], input=code,
                       text=True, env=env, check=True)
        rendered = plistlib.loads(candidate.read_bytes())
        assert rendered['EnvironmentVariables']['LTX_TALKING_PHOTO_SEED'] == '42'
        assert rendered['EnvironmentVariables']['LTX_TALKING_PHOTO_DEBUG_ROOT'] == '/tmp/ltx-debug'
        assert rendered['EnvironmentVariables']['PATH'] == '/usr/bin'
        # An explicit 0.18 Talking Photo switch must survive future launchd installs.
        previous.write_bytes(plistlib.dumps({'EnvironmentVariables': {
            'LTX_MLX_RUNTIME_ROOT': '/home/test/ltx-2-mlx-v0.18.0',
            'LTX_MLX_MODEL_ROOT': '/home/test/models',
        }}))
        candidate.write_bytes(plistlib.dumps(baseline))
        env.pop('LTX_MLX_RUNTIME_ROOT', None)
        env.pop('LTX_MLX_MODEL_ROOT', None)
        subprocess.run([sys.executable, '-', str(candidate), str(previous)], input=code,
                       text=True, env=env, check=True)
        migrated = plistlib.loads(candidate.read_bytes())['EnvironmentVariables']
        assert migrated['LTX_MLX_RUNTIME_ROOT'] == '/home/test/ltx-2-mlx-v0.18.0'
        assert migrated['LTX_MLX_MODEL_ROOT'] == '/home/test/models'
        assert migrated['PATH'] == '/usr/bin'
