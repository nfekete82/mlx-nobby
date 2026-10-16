import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code = fs.readFileSync('frontend/assets/chat/region-editor.js', 'utf8');
const gen = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const chat = fs.readFileSync('frontend/chat.html', 'utf8');
const render = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
const library = fs.readFileSync('frontend/assets/chat/media-library.js', 'utf8');
const css = fs.readFileSync('frontend/assets/chat/region-editor.css', 'utf8');

test('editor exports an opt-in window integration without opening a dialog', () => {
  const context = vm.createContext({window: {}, document: {documentElement: {lang: 'de'}}});
  vm.runInContext(code, context);
  assert.equal(typeof context.window.MLXRegionEditor.open, 'function');
  assert.equal(typeof context.window.MLXRegionEditor.paintPath, 'function');
  assert.equal(context.window.MLXRegionEditor.maskHasSelection([]), false);
  assert.equal(context.window.MLXRegionEditor.maskHasSelection([{erase: true}]), false);
  assert.equal(context.window.MLXRegionEditor.maskHasSelection([{erase: false}]), true);
});

test('brush strokes are rounded and use requested pixel width', () => {
  const context = vm.createContext({window: {}, document: {documentElement: {lang: 'de'}}});
  vm.runInContext(code, context);
  const calls = [];
  const painter = {
    beginPath() {calls.push('begin');}, arc(...args) {calls.push(['arc', ...args]);},
    fill() {calls.push('fill');}, moveTo(...args) {calls.push(['move', ...args]);},
    lineTo(...args) {calls.push(['line', ...args]);}, stroke() {calls.push('stroke');},
  };
  context.window.MLXRegionEditor.paintPath(painter, [[10, 20], [30, 40]], 16, '#fff');
  assert.equal(painter.lineWidth, 16);
  assert.equal(painter.lineCap, 'round');
  assert.ok(calls.includes('stroke'));
  assert.ok(calls.some(item => Array.isArray(item) && item[0] === 'arc' && item[3] === 8));
});

test('editor draws pixel-aligned black/white PNG, uploads it and sends masked edit', () => {
  assert.match(code, /ctx\.fillStyle = '#000'/);
  assert.match(code, /stroke\.erase \? '#000' : '#fff'/);
  assert.match(code, /display\.getBoundingClientRect\(\)/);
  assert.match(code, /display\.setPointerCapture/);
  assert.match(code, /mask\.toBlob/);
  assert.match(code, /uploadImageAttachments/);
  assert.match(code, /mask_path: path/);
  assert.match(code, /new File\(\[blob\]/);
  assert.match(code, /paintPath/);
  assert.match(code, /pointercancel/);
  assert.match(css, /touch-action: none/);
});

test('images expose same editor from chat and library; existing compare kept', () => {
  assert.match(chat, /region-editor\.css/);
  assert.match(chat, /region-editor\.js/);
  assert.match(render, /MLXRegionEditor\?\.open/);
  assert.match(render, /MLXImageCompare\?\.open/);
  assert.match(library, /MLXRegionEditor\?\.open/);
});

test('masked edits use the standard chat action queue and image artifact identifiers', () => {
  assert.match(gen, /async function startRegionImageEdit/);
  assert.match(gen, /action: 'image_edit'/);
  // Regression: one escaped digit token matches actual artifact IDs; \\d
  // escaped twice would match the literal characters instead.
  assert.ok(gen.includes(String.raw`/^\d{10}-[a-f0-9]{12}$/i.test`));

  assert.match(gen, /resolved_target: 'image_edit'/);
  assert.match(gen, /mask_path: mask_path/);
  assert.match(gen, /active_artifact_id: artifact_id/);
  assert.match(gen, /updateImageJobMessage/);
  assert.match(gen, /watchImageJob/);
  assert.match(gen, /startRegionImageEdit: startRegionImageEdit/);
});
