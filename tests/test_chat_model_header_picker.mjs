import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const runtime = fs.readFileSync('frontend/assets/chat/runtime.js', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');

test('chat model title is an accessible, visibly selectable header control', () => {
    const button = html.match(/<button\b[^>]*id="modelTitle"[^>]*>[\s\S]*?<\/button>/);
    assert.ok(button, 'The header must use a real button, not an inert text label');
    assert.match(button[0], /aria-haspopup="true"/);
    assert.match(button[0], /aria-controls="modelPopover"/);
    assert.match(button[0], /aria-expanded="false"/);
    assert.match(html, /class="model-popover-heading" data-i18n="runtime_ui.chat_model_choose">Chatmodell auswählen/);
    assert.match(css, /\.model-title::after\s*\{/);
    assert.match(css, /\.model-popover-hint\s*\{/);
});

test('header switch changes chat role only and blocks while generating', () => {
    const start = runtime.indexOf('async function switchModel(alias)');
    const end = runtime.indexOf('function initModelSwitcher()', start);
    assert.ok(start >= 0 && end > start);
    const action = runtime.slice(start, end);
    assert.match(action, /if \(isGenerating\(\)\)/);
    assert.match(action, /\/api\/mlx\/model\/chat\//);
    assert.doesNotMatch(action, /['"]\/api\/mlx\/model\/['"]\s*\+/);
    assert.match(runtime, /option\.disabled = isSwitching\(\) \|\| isGenerating\(\) \|\| model\.active/);
    const initializer = runtime.slice(end, runtime.indexOf('function initRuntimeInfoPopover()', end));
    assert.match(initializer, /modelTitle\.addEventListener\('click'/);
    assert.doesNotMatch(initializer, /modelTitle\.addEventListener\('keydown'/,
        'Native button keyboard activation must not be duplicated');
});
