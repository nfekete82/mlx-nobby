import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const html=fs.readFileSync('frontend/chat.html','utf8');
const code=fs.readFileSync('frontend/assets/chat/sidebar-rail-utilities.js','utf8');
const css=fs.readFileSync('frontend/assets/chat.css','utf8');

test('collapsed rail loads a single utility mirror and keeps existing shortcut controls',()=>{
 assert.match(html,/sidebar-rail-utilities\.js\?v=1-11-0/);
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
 assert.match(code,/observer\.observe\(bottom, \{childList:true\}\)/);
 assert.match(css,/\.app\.sidebar-collapsed[\s\S]*?\.sidebar-rail/);
});
