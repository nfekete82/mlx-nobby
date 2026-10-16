import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const html=fs.readFileSync('frontend/chat.html','utf8');
const photo=fs.readFileSync('frontend/assets/chat/talking-photo.js','utf8');
const runtime=fs.readFileSync('frontend/assets/chat/runtime.js','utf8');
const appearance=fs.readFileSync('frontend/assets/chat/appearance.js','utf8');
const css=fs.readFileSync('frontend/assets/chat/media-library.css','utf8');
const chatCss=fs.readFileSync('frontend/assets/chat.css','utf8');
test('Dateien & Jobs moves into System & Tools without replacing its button handler',()=>{
 const utilities=fs.readFileSync('frontend/assets/chat/sidebar-rail-utilities.js','utf8');
 assert.match(utilities,/\['sidebarJobsButton', 'mlxSidebarHelpButton', 'runtimeInfoButton', 'sidebarSettingsButton'\]/);
 assert.match(utilities,/items\.appendChild\(button\)/);
 assert.equal((html.match(/id="sidebarJobsButton"/g)||[]).length,1);
});

test('system info is in anchored sidebar not topbar',()=>{
 const bottom=html.indexOf('<div class="sidebar-bottom">');
 const main=html.indexOf('<main class="main">');
 const info=html.indexOf('id="runtimeInfoButton"');
 assert.ok(bottom>=0 && info>bottom && info<main);
 assert.equal((html.match(/id="runtimeInfoButton"/g)||[]).length,1);
 assert.match(runtime,/runtimeInfoButton.addEventListener\('click'/);
 assert.match(css, /\.sidebar-bottom #runtimeInfoButton/);
});
test('Talking Photo launch uses anchored sidebar and existing modal behavior',()=>{
 assert.match(photo, /querySelector\('\.sidebar-bottom'\)/);
 assert.match(photo, /host.insertBefore\(button, anchor\)/);
 assert.match(photo,/button.addEventListener\('click', openModal\)/);
 assert.doesNotMatch(photo,/querySelector\('\.top-actions'\)/);
});

test('Systeminfo remains owned by System & Tools during dynamic mounts',()=>{
 assert.doesNotMatch(runtime,/new MutationObserver\(alignSystemInfo\)/);
 assert.doesNotMatch(runtime,/sidebarBottom\.insertBefore\(runtimeInfoButton, settings\)/);
 assert.match(runtime,/runtimeInfoButton\.addEventListener\('click'/);
});

test('Shorts uses a direct sidebar child anchor, not nested Settings',()=>{
 assert.match(appearance,/group\?\.parentElement === sidebarBottom/);
 assert.match(appearance,/desiredReference\?\.parentElement === sidebarBottom/);
 assert.doesNotMatch(appearance,/desiredReference \|\| settingsButton/);
});

test('Shorts sidebar row and desktop Notes modal are constrained to the viewport',()=>{
 assert.match(chatCss,/\.sidebar \.sidebar-bottom > \.mlx-shorts-history-launcher\.sidebar-action/);
 assert.match(chatCss,/body #notesPanel\.notes-panel/);
 assert.match(chatCss,/transform: translate\(-50%, -50%\) !important/);
});
