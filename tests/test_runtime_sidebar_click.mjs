import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const runtime=fs.readFileSync('frontend/assets/chat/runtime.js','utf8');
const html=fs.readFileSync('frontend/chat.html','utf8');
test('runtime menu clicks within nested icon and label do not close popover immediately',()=>{
 assert.match(runtime,/!runtimeInfoButton\.contains\(event\.target\)/);
 assert.doesNotMatch(runtime,/event\.target !== runtimeInfoButton/);
 assert.match(runtime,/runtimeInfoButton\.addEventListener\('click'/);
 assert.match(runtime,/runtimePopover\.hidden = false/);
 assert.match(html,/runtime\.js\?v=20261010-runtime-sidebar-click/);
});
