import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const chat = fs.readFileSync(new URL('../frontend/assets/chat.js', import.meta.url), 'utf8');
const sessions = fs.readFileSync(new URL('../frontend/assets/chat/sessions.js', import.meta.url), 'utf8');

// Confirm modal and its shared helper remain available.
for (const id of ['confirmModal', 'confirmModalConfirm', 'confirmModalCancel']) {
    assert.match(html, new RegExp('id="' + id + '"'));
}
assert.match(chat, /window\.MLXConfirm\s*=\s*showConfirmModal/);

// "All chats" is still in the main sidebar, NOT under Settings.
assert.match(html, /id="chatHistoryMenu"/);
assert.match(html, /id="deleteAllChats"/);
assert.doesNotMatch(html, /id="settingsDeleteAllChats"/);
assert.match(chat, /MLXChatSessions\.deleteAllSessions\(\)/);

// The sidebar action requires a confirmation before it sends a scoped request.
const start = sessions.indexOf('async function deleteAllSessions()');
const end = sessions.indexOf('function renameSession(', start);
assert.ok(start > -1 && end > start);
const bulk = sessions.slice(start, end);
assert.match(bulk, /await window\.MLXConfirm\(\{/);
assert.match(bulk, /if \(!confirmed\) return false/);
assert.match(bulk, /chatDeleteApproval\('all'\)/);
assert.match(bulk, /deletion_token: deletionToken/);
assert.match(bulk, /await window\.MLXChatWorkspace\?\.deactivate\?\.\(\)/);

// There is no hidden destructive "clear messages" shortcut.
const clearStart = sessions.indexOf('async function deleteMessages()');
const clearEnd = sessions.indexOf('function updateTitle(', clearStart);
assert.ok(clearStart > -1 && clearEnd > clearStart);
const clear = sessions.slice(clearStart, clearEnd);
assert.match(clear, /return false/);
assert.doesNotMatch(clear, /api\/mlx\/chats/);

// Workspace deactivation remains available.
assert.match(chat, /async function deactivateWorkspace\(\)/);
assert.match(chat, /deactivate:\s*deactivateWorkspace/);
console.log('Sidebar chat deletion confirmation and non-destructive memory boundary passed.');
