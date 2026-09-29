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

assert.match(dictation, /agent-task-mode\.js/, 'chat must load Task Mode module');
assert.match(source, /agentTaskModeSwitch/, 'Task Mode must expose a Chat\/Task switch');
assert.match(source, /agentChatModeButton/, 'switch must expose Chat mode');
assert.match(source, /agentTaskModeButton/, 'switch must expose Task mode');
assert.match(source, /activeWorkspaceHeader/, 'mode switch must live next to the active workspace');
assert.match(source, /let mode = 'chat'/, 'Chat must be the safe default');
assert.match(source, /mode !== 'task'/, 'only Task mode may own task submissions');
assert.doesNotMatch(source, /setArmed\(false\);\s*\n\s*let workspace/, 'Task mode must no longer be one-shot');
assert.match(source, /!workspace\?\.workspace_id && mode === 'task'/, 'closing the workspace must fall back to Chat');
assert.match(source, /taskButton\.disabled = running \|\| !hasWorkspace/, 'Task must be disabled without a workspace');
assert.match(source, /\/api\/mlx\/code\/workspaces/, 'Task Mode must bind an active workspace');
assert.match(source, /\/api\/mlx\/agent\/run/, 'Task Mode must reuse the existing agent runtime');
assert.match(source, /mode:\s*'coding'/, 'Task Mode must execute through coding mode');
assert.match(source, /workspace_bound:\s*true/, 'Task Mode must enforce workspace binding');
assert.match(source, /code_prepare/, 'Task contract must prepare a patch');
assert.match(source, /code_apply/, 'Task contract must use approved code application');
assert.match(source, /code_test/, 'Task contract must run workspace tests');
assert.match(source, /code_revert/, 'Task contract must preserve rollback semantics');
assert.match(source, /at most three repair cycles/, 'Task contract must cap repair cycles');
assert.match(source, /stopImmediatePropagation/, 'Task Mode must own composer submission while selected');
assert.match(css, /\.agent-task-mode-switch/, 'Task Mode switch must have isolated styling');
assert.match(css, /\.agent-task-mode-option\.is-active/, 'selected mode must be visually distinct');

assert.equal(de.chat_label, 'Chat');
assert.equal(de.task_label, 'Task');
assert.equal(en.chat_label, 'Chat');
assert.equal(en.task_label, 'Task');
assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort(), 'Task Mode translations must stay in sync');

console.log('✓ agent task mode workspace switch contract present');
