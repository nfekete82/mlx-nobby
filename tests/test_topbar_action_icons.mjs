import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');

for (const id of [
    'sidebarToggle',
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

assert.doesNotMatch(html, /id="clearButton"/);

assert.match(css, /\.top-action-button\s*\{/);
assert.match(css, /\.top-action-icon\s*\{/);
assert.match(css, /stroke-width:\s*1\.8/);

console.log('Top-bar action icons are consistent and accessible.');
