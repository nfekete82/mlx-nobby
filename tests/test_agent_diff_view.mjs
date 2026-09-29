import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const moduleUrl = pathToFileURL(
    path.resolve('frontend/assets/chat/agent-diff-view.js')
).href + '?test=' + Date.now();

await import(moduleUrl);

const api = globalThis.MLXAgentDiffView?.__test;
assert.ok(api, 'agent diff view test API must be exposed');

const diff = [
    '--- original/README.md',
    '+++ proposed/README.md',
    '@@ -10,4 +10,4 @@',
    ' unchanged',
    '-old wording',
    '-second old line',
    '+new wording',
    '+second new line',
    ' tail',
    ''
].join('\n');

const rows = api.parseUnifiedDiff(diff);
assert.equal(rows[0].type, 'hunk');
assert.equal(rows[1].type, 'context');
assert.equal(rows[1].left.number, 10);
assert.equal(rows[1].right.number, 10);
assert.equal(rows[2].type, 'change');
assert.equal(rows[2].left.number, 11);
assert.equal(rows[2].left.text, 'old wording');
assert.equal(rows[2].right.number, 11);
assert.equal(rows[2].right.text, 'new wording');
assert.equal(rows[3].left.number, 12);
assert.equal(rows[3].right.number, 12);
assert.equal(rows[4].type, 'context');
assert.equal(rows[4].left.number, 13);
assert.equal(rows[4].right.number, 13);

const insertion = api.parseUnifiedDiff([
    '@@ -2,2 +2,3 @@',
    ' keep',
    '+inserted',
    ' next'
].join('\n'));
assert.equal(insertion[2].left, null);
assert.equal(insertion[2].right.text, 'inserted');
assert.equal(insertion[2].right.number, 3);

assert.equal(api.changeCount([
    { added: 3, removed: 5 },
    { added: 1, removed: 0 }
]), 9);

console.log('✓ agent split diff parser contract present');
