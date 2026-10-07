import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');

for (const id of [
    'sidebarToggle',
    'runtimeInfoButton',
    'clearButton',
    'settingsButton',
    'powerButton',
]) {
    const match = html.match(new RegExp(
        '<button[\\s\\S]*?id="' + id + '"[\\s\\S]*?<\\/button>'
    ));
    assert.ok(match, id + ' button must exist');
    assert.match(match[0], /top-action-button/);
    assert.match(match[0], /<svg class="top-action-icon"/);
}

const clear = html.match(
    /<button[\s\S]*?id="clearButton"[\s\S]*?<\/button>/
)?.[0] || '';
assert.match(clear, /aria-label="Chat leeren"/);
assert.match(clear, /data-i18n-aria-label="ui\.clear_chat"/);
assert.doesNotMatch(clear, />\s*Chat leeren\s*</);

assert.match(css, /\.top-action-button\s*\{/);
assert.match(css, /\.top-action-icon\s*\{/);
assert.match(css, /stroke-width:\s*1\.8/);

console.log('Top-bar action icons are consistent and accessible.');
