import assert from 'node:assert/strict';
import fs from 'node:fs';

const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');
const html = fs.readFileSync('frontend/chat.html', 'utf8');

assert.match(css, /--settings-control-height:\s*44px/);
assert.match(css, /\.settings-organized select\s*\{/);
assert.match(css, /appearance:\s*none/);
assert.match(css, /\.settings-organized \.settings-button,/);
assert.match(css, /\.settings-organized \.message-action-btn/);
assert.match(css, /\.settings-organized \.model-role-item select/);
assert.match(css, /box-shadow:\s*0 0 0 3px rgba\(79, 140, 255, \.16\)/);
assert.match(
    html,
    /\/assets\/chat\.css\?v=20261007-settings-controls/
);

console.log('Settings controls share one polished visual system.');
