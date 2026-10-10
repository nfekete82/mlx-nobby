import assert from "node:assert/strict";
import fs from "node:fs";
const html=fs.readFileSync(new URL("../frontend/chat.html",import.meta.url),"utf8");
const js=fs.readFileSync(new URL("../frontend/assets/chat/sidebar-navigation.js",import.meta.url),"utf8");
const css=fs.readFileSync(new URL("../frontend/assets/chat/media-library.css",import.meta.url),"utf8");
for(const id of ["newChat","sidebarLibraryButton","chatHistoryMenu","recentToggle","recentFilterToggle","recentSearch","recentNewChat","chatList"])assert.match(html,new RegExp('id="'+id+'"'));
assert.equal((html.match(/id="chatHistoryMenu"/g)||[]).length,1);
assert.equal((html.match(/id="deleteAllChats"/g)||[]).length,1);
assert.ok(html.indexOf('library.projects')<html.indexOf('library.recent'));
assert.match(html,/sidebar-navigation\.js\?v=1-10-1/);
assert.match(js,/new MutationObserver\(applyFilter\)/);
assert.match(js,/row\.hidden = Boolean\(query\)/);
assert.match(js,/data-session-title/);
assert.match(js,/\.chat-title/);
assert.doesNotMatch(js,/const label = \(row\.textContent/);
assert.match(js,/list\.hidden = !expanded/);
assert.match(js,/document\.getElementById\("newChat"\)\?\.click\(\)/);
assert.match(css,/nobby-recent-heading/);
assert.match(css,/sidebar-library-action svg/);
console.log("Sidebar structure, recent tools, new-chat shortcut and DOM filter wiring passed.");

assert.ok(html.indexOf('id="sidebarJobsButton"') > html.indexOf('class="sidebar-bottom"'), 'Files & Jobs must stay in fixed bottom navigation');

// The bottom navigation must stay anchored when the recent list is hidden.
assert.match(css,/\.sidebar \.sidebar-bottom\s*\{[^}]*margin-top\s*:\s*auto/);
assert.match(css,/\.sidebar \.sidebar-bottom\s*\{[^}]*flex-shrink\s*:\s*0/);
assert.match(html,/media-library\.css\?v=20261010-runtime-modal-layout/);

const chat = fs.readFileSync(new URL("../frontend/assets/chat.js",import.meta.url),"utf8");
for (const id of ["sidebarWorkspaceList","sidebarWorkspaceAdd","sidebarWorkspaceFeedback"]) {
  assert.match(html, new RegExp('id="'+id+'"'));
}
assert.match(html,/nobby-sidebar-recent-divider/);
assert.match(chat,/renderSidebarWorkspaces\(data\.workspaces \|\| \[\], data\.active_workspace \|\| null\)/);
assert.match(chat,/encodeURIComponent\(workspace\.workspace_id\) \+ '\/activate'/);
assert.match(chat,/workspaceRequest\('\/api\/mlx\/code\/workspaces'/);
assert.match(css,/\.nobby-sidebar-workspace\.is-active/);
assert.match(css,/\.nobby-sidebar-recent-divider/);
