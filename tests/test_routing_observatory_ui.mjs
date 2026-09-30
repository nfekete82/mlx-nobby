import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const ui = fs.readFileSync(
    new URL('../frontend/assets/chat/routing-observatory.js', import.meta.url),
    'utf8'
);
const styles = fs.readFileSync(
    new URL('../frontend/assets/chat/routing-observatory.css', import.meta.url),
    'utf8'
);
const backend = fs.readFileSync(
    new URL('../backend/media_routing_ui.py', import.meta.url),
    'utf8'
);


test('routing observatory is injected into the tools pane', () => {
    assert.match(ui, /data-settings-pane="functions"/);
    assert.match(ui, /Routing Observatory/);
    assert.match(ui, /\/api\/routing\/decisions/);
    assert.match(backend, /routing-observatory\.js\?v=/);
    assert.match(backend, /routing-observatory\.css\?v=/);
});


test('routing observatory exposes explicit feedback routes', () => {
    for (const route of ['chat', 'image', 'video_generate', 'shorts_generate', 'agent', 'web_search']) {
        assert.match(ui, new RegExp(route));
    }
    assert.match(ui, /correct:\s*true/);
    assert.match(ui, /correct:\s*false/);
    assert.match(ui, /expected_target/);
});


test('routing observatory renders confidence and guard diagnostics', () => {
    assert.match(ui, /confidence_source/);
    assert.match(ui, /original_target/);
    assert.match(ui, /duration_ms/);
    assert.match(ui, /prompt_sha256/);
    assert.match(styles, /\.routing-confidence\.is-high/);
    assert.match(styles, /\.routing-observatory-table/);
});
