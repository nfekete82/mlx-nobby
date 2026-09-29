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
const de = JSON.parse(fs.readFileSync(
    'frontend/i18n/agent-task-mode.de.json',
    'utf8',
));
const en = JSON.parse(fs.readFileSync(
    'frontend/i18n/agent-task-mode.en.json',
    'utf8',
));

assert.match(dictation, /agent-task-mode\.js/, 'chat must load workspace mode module');
assert.doesNotMatch(source, /agentTaskModeSwitch/, 'workspace mode must not expose a Chat\/Task switch');
assert.doesNotMatch(source, /agentChatModeButton/, 'workspace mode must not expose a manual Chat button');
assert.doesNotMatch(source, /agentTaskModeButton/, 'workspace mode must not expose a manual Task button');
assert.match(source, /function isWorkspaceMode\(\)/, 'workspace presence must determine the mode');
assert.match(source, /Boolean\(workspace\?\.workspace_id\)/, 'an active workspace must imply task mode');
assert.match(source, /if \(!isWorkspaceMode\(\) \|\| running\) return;/, 'normal chat must remain untouched without a workspace');
assert.match(source, /\/api\/mlx\/code\/workspaces/, 'workspace mode must bind an active workspace');
assert.match(source, /\/api\/mlx\/agent\/run/, 'workspace mode must reuse the existing agent runtime');
assert.match(source, /mode:\s*'coding'/, 'workspace mode must execute through coding mode');
assert.match(source, /workspace_bound:\s*true/, 'workspace mode must enforce workspace binding');
assert.match(source, /read-only answer or an actual mutation/, 'task contract must distinguish read-only and mutating requests');
assert.match(source, /do not prepare or apply a patch/, 'read-only workspace questions must remain read-only');
assert.match(source, /code_prepare/, 'mutation contract must prepare a patch');
assert.match(source, /code_apply/, 'mutation contract must use approved code application');
assert.match(source, /code_test/, 'mutation contract must run workspace tests');
assert.match(source, /code_revert/, 'mutation contract must preserve rollback semantics');
assert.match(source, /at most three repair cycles/, 'mutation contract must cap repair cycles');
assert.match(source, /stopImmediatePropagation/, 'workspace mode must own composer submission while a workspace is active');
assert.match(source, /data-workspace-task-active/, 'active workspace state must be observable in the DOM');

assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort(), 'workspace mode translations must stay in sync');
assert.equal(de.workspace_check_failed, 'Der aktive Workspace konnte nicht geprüft werden.');
assert.equal(en.workspace_check_failed, 'The active workspace could not be checked.');

console.log('✓ agent workspace-implies-task contract present');
