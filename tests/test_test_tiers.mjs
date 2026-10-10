import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const cli=fs.readFileSync('scripts/mlx','utf8');
const tiers=fs.readFileSync('scripts/test-tiers.sh','utf8');
const docs=fs.readFileSync('docs/TESTING.md','utf8');
test('CLI dispatches both CPU tiers before reading runtime configuration',()=>{
  assert.match(cli,/test-quick\s*\|\|.*test-medium/);
  assert.ok(cli.indexOf('test-quick|test-medium)') < cli.lastIndexOf('load_config\n\ncase'));
  assert.match(cli,/test-release\) exec/);
});
test('quick requires a selector and medium checks Python plus Node without services',()=>{
  assert.match(tiers,/if \[\[ "\$#" -eq 0 \]\]/);
  assert.match(tiers,/exec "\$PYTHON" -m pytest -q "\$@"/);
  assert.match(tiers,/node --test tests\/\*\.mjs/);
  assert.doesNotMatch(tiers,/docker compose|mlx restart|playwright/);
  assert.match(docs,/test-medium/);
});
