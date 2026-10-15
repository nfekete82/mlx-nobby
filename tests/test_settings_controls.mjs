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
    /\/assets\/chat\.css\?v=1-13-news-briefing/
);

console.log('Settings controls share one polished visual system.');


// Full-screen workspaces and input/button consistency across menus.
const settingsLayoutCss = fs.readFileSync('frontend/assets/chat/settings-layout.css', 'utf8');
const helpSource = fs.readFileSync('frontend/assets/chat/help.js', 'utf8');
const libraryCss = fs.readFileSync('frontend/assets/chat/media-library.css', 'utf8');
assert.match(settingsLayoutCss, /\.settings\.settings-organized\s*\{[\s\S]*?inset:\s*0;[\s\S]*?height:\s*100dvh;/);
assert.match(css, /\.runtime-modal\s*\{[\s\S]*?height:\s*100dvh;/);
assert.match(css, /#notesPanel\s*\{[\s\S]*?height:\s*100dvh\s*!important/);
assert.match(helpSource, /\.mlx-help-panel\{inset:0;top:0;left:0;right:0;bottom:0;width:100vw;height:100dvh/);
assert.match(libraryCss, /\.nobby-library-panel\{position:fixed;inset:0;/);
assert.match(css, /--nobby-control-height:\s*42px/);
assert.match(css, /\.image-edit-control,[\s\S]*?\.model-console-form/);
assert.match(helpSource, /var\(--nobby-control-bg,#111925\)/);
assert.match(css, /#runtimeModalClose,[\s\S]*?#settingsClose,[\s\S]*?#notesClose/);
