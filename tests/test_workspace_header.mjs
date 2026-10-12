import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const js = fs.readFileSync('frontend/assets/chat.js', 'utf8');

// Workspace selection was deliberately moved from the header to the sidebar.
for (const id of ['sidebarWorkspaceList', 'sidebarWorkspaceAdd', 'sidebarWorkspaceFeedback']) {
    assert.match(html, new RegExp('id=["\\x27]' + id + '["\\x27]'), 'sidebar missing ' + id);
}
assert.match(js, /\/api\/mlx\/code\/workspaces\/pick/, 'folder picker must remain available');
assert.match(js, /\/api\/mlx\/code\/workspaces\/active/, 'active workspace API must remain available');
assert.match(js, /nobby-sidebar-workspace-remove/, 'workspace remove action must remain available');
assert.doesNotMatch(html, /id=["']activeWorkspaceHeader["']/, 'deprecated workspace header must stay removed');

console.log('✓ sidebar workspace contract present');
