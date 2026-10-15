import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const html=fs.readFileSync('frontend/chat.html','utf8');
const code=fs.readFileSync('frontend/assets/chat/sidebar-rail-utilities.js','utf8');
const css=fs.readFileSync('frontend/assets/chat.css','utf8');
const talkingPhoto=fs.readFileSync('frontend/assets/chat/talking-photo.js','utf8');

test('collapsed rail loads a single utility mirror and keeps existing shortcut controls',()=>{
 assert.match(html,/sidebar-rail-utilities\.js\?v=1-13-system-tools/);
 for(const id of ['railNewChat','railChats','railLibrary','railJobs','railSettings']) {
   assert.match(html,new RegExp('id="'+id+'"'));
 }
 assert.match(code,/rail\.dataset\.utilityMirrorInstalled/);
 assert.match(code,/spacer\.after\(jobs\)/);
 assert.match(code,/rail\.appendChild\(settings\)/);
});
test('all bottom utilities use existing SVGs, tools and accessible titles',()=>{
 for(const label of ['talkingPhotoButton','mlxSidebarHelpButton','mlx-shorts-history-launcher','runtimeInfoButton']) {
   assert.ok(code.includes(label),label);
 }
 assert.match(code,/icon\.cloneNode\(true\)/);
 assert.match(code,/target\.click\(\)/);
 assert.match(code,/setAttribute\('aria-label', label\)/);
 assert.match(code,/button\.title = label/);
 assert.match(code,/observer\.observe\(bottom, \{childList:true, subtree:true\}\)/);
 assert.match(css,/\.app\.sidebar-collapsed[\s\S]*?\.sidebar-rail/);
});

test('System & Tools groups footer actions while preserving original buttons',()=>{
 assert.match(code,/sidebarSystemTools/);
 assert.match(code,/mlxSidebarHelpButton', 'runtimeInfoButton', 'sidebarSettingsButton'/);
 assert.match(code,/button && button.parentElement !== items/);
 assert.match(css,/sidebar-system-tools-items/);
});

test('collapsed utility rail tolerates Settings anchor moving out of the rail',()=>{
 assert.match(code,/settings\?\.parentNode === rail \? settings : null/);
 assert.match(code,/rail\.insertBefore\(button, anchor\)/);
});

test('Talking Photo can mount after Systeminfo moves into the group',()=>{
 assert.match(talkingPhoto,/runtimeInfo\?\.parentElement === host \? runtimeInfo : host\.firstChild/);
 assert.match(talkingPhoto,/host\.insertBefore\(button, anchor\)/);
});
