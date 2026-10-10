import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const runtime=fs.readFileSync('frontend/assets/chat/runtime.js','utf8');
const html=fs.readFileSync('frontend/chat.html','utf8');
const css=fs.readFileSync('frontend/assets/chat/media-library.css','utf8');
test('runtime info modal retains sidebar entry and real runtime data',()=>{
 assert.match(runtime,/runtimeInfoButton\.addEventListener\('click'/);
 assert.match(runtime,/runtimePopover\.hidden = false/);
 assert.match(runtime,/refreshRuntimeInfo\(\)/);
 assert.match(runtime,/clearInterval\(runtimeInfoInterval\)/);
 assert.match(html,/runtime\.js\?v=20261010-runtime-modal/);
});
test('modal includes close X, accessible dialog and backdrop',()=>{
 assert.match(html,/id="runtimeModalClose"/);
 assert.match(html,/<dialog id="runtimePopover"/);
 assert.match(html,/aria-modal="true"/);
 assert.match(runtime,/runtimePopover\\.showModal\\(\\)/);
 assert.match(runtime,/runtimePopover\\.close\\(\\)/);
 assert.match(html,/data-runtime-close="true"/);
 assert.match(runtime,/getElementById\('runtimeModalClose'\).*addEventListener\('click', closeRuntimePopover\)/);
 assert.match(runtime,/event\.key === 'Escape'/);
 assert.match(runtime,/runtimeModalPreviousFocus\.focus\(\)/);
 assert.match(css,/\.runtime-popover\.nobby-runtime-modal\[hidden\]\{display:none!important\}/);
});

test('native Systeminfo dialog is viewport-centered',()=>{ assert.match(css,/dialog#runtimePopover\.nobby-runtime-modal\[open\]/); assert.match(css,/transform: translate\(-50%, -50%\)/); assert.match(css,/max-height: min\(88dvh, 820px\)/); });
