import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = path => fs.readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const css = read('frontend/assets/chat/ui-controls.css');
const library = read('frontend/assets/chat/media-library.css');
const chat = read('frontend/chat.html');
const control = read('frontend/index.html');
const voice = read('frontend/assets/chat/voice.js');

for (const html of [chat, control]) {
  assert.match(html, /ui-controls\.css\?v=1-18-ui-consistency/);
  assert.match(html, /<body class="[^"]*\bnobby-ui\b/);
}
for (const token of [
  '--nobby-ui-control-bg', '--nobby-ui-control-open-bg',
  '--nobby-ui-control-border', '--nobby-ui-focus',
  '--nobby-ui-picker-bg', '--nobby-ui-picker-selected',
  '--nobby-ui-control-height'
]) {
  assert.ok(css.includes(token + ':'), 'Missing UI token: ' + token);
}
for (const selector of [
  '.model-console-form select', '.model-role-item select',
  '.model-scout-select', '.model-overview-select',
  '.mlx-voice-select', '.mlx-voice-speed', '.mlx-vm-select',
  '.mlx-shorts-studio-field select', '.mlx-shorts-project-overlay select',
  '.automation-field select', '.memory-manager-card select',
  '.routing-feedback-editor select', '.routing-observatory-filters select',
  '.note-folder-select', '.media-duration-field select'
]) {
  assert.ok(css.includes(selector), 'Missing module selector: ' + selector);
}
for (const special of ['[type="checkbox"]', '[type="radio"]', '[type="range"]', '[type="file"]']) {
  assert.ok(css.includes(':not(' + special + ')'), 'Protect specialized controls: ' + special);
}
assert.match(css, /@supports \(appearance: base-select\) and selector\(::picker\(select\)\)/);
assert.match(css, /::picker-icon/);
assert.match(css, /::picker\(select\)/);
assert.match(css, /width: anchor-size\(width\)/);
assert.match(css, /option::checkmark/);
assert.match(css, /prefers-reduced-motion/);
assert.match(css, /\.finance-chart-range/);
assert.match(css, /outline: 2px solid var\(--nobby-ui-focus\)/);
assert.match(css, /body\.nobby-ui :is\(#addModelQuant, #batchFileType, #batchChunkTokens\)/);
assert.match(library, /\.mlx-talking-photo-field/);
assert.doesNotMatch(voice, /appearance: none;[\s\S]{0,250}background-image:/);

const roles = ['chat', 'agent', 'coding', 'vision', 'vision_uncensored', 'embedding'];
for (const role of roles) {
  const label = 'modelRoleLabel' + role.replace(/_/g, '-');
  assert.match(chat, new RegExp('id="' + label + '"'));
  assert.match(chat, new RegExp('aria-labelledby="' + label + '" data-model-role="' + role + '"'));
}

assert.doesNotMatch(css, /(^|\n)\s*(select|input|button)\s*\{/);
console.log('Shared UI controls, module scopes, a11y labels, and control-center integration passed.');
