import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(
    'frontend/assets/chat/agent-task-mode.js',
    'utf8',
);
const dictation = fs.readFileSync(
    'frontend/assets/chat/dictation.js',
    'utf8',
);
const css = fs.readFileSync(
    'frontend/assets/chat/agent-task-mode.css',
    'utf8',
);
const de = JSON.parse(fs.readFileSync(
    'frontend/i18n/agent-task-mode.de.json',
    'utf8',
));
const en = JSON.parse(fs.readFileSync(
    'frontend/i18n/agent-task-mode.en.json',
    'utf8',
));

assert.match(dictation, /agent-task-mode\.js/, 'composer must load Task Mode module');
assert.match(source, /agentTaskModeButton/, 'Task Mode must expose a composer control');
assert.match(source, /\/api\/mlx\/code\/workspaces/, 'Task Mode must bind an active workspace');
assert.match(source, /\/api\/mlx\/agent\/run/, 'Task Mode must reuse the existing agent runtime');
assert.match(source, /mode:\s*'coding'/, 'Task Mode must execute through coding mode');
assert.match(source, /workspace_bound:\s*true/, 'Task Mode must enforce workspace binding');
assert.match(source, /code_prepare/, 'Task contract must prepare a patch');
assert.match(source, /code_apply/, 'Task contract must use approved code application');
assert.match(source, /code_test/, 'Task contract must run workspace tests');
assert.match(source, /code_revert/, 'Task contract must preserve rollback semantics');
assert.match(source, /at most three repair cycles/, 'Task contract must cap repair cycles');
assert.match(source, /stopImmediatePropagation/, 'Task Mode must own the armed composer submission');
assert.match(css, /\.agent-task-mode-button/, 'Task Mode must have isolated styling');

assert.equal(de.label, 'Task');
assert.equal(de.active, 'Task Mode aktiv');
assert.equal(en.active, 'Task Mode active');
assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort(), 'Task Mode translations must stay in sync');

console.log('✓ agent task mode v1 contract present');
