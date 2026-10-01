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
const translations = fs.readFileSync(
    new URL('../frontend/i18n/routing-observatory.json', import.meta.url),
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


test('routing observatory renders original and final route diagnostics', () => {
    assert.match(ui, /originalRoute/);
    assert.match(ui, /finalRoute/);
    assert.match(ui, /decision\.original_target/);
    assert.match(ui, /decision\.target/);
    assert.match(ui, /confidence_source/);
    assert.match(ui, /duration_ms/);
    assert.match(ui, /decision\.intent/);
    assert.match(ui, /prompt_sha256/);
    assert.match(styles, /\.routing-route-cell\.is-original/);
    assert.match(styles, /\.routing-route-cell\.is-final\.is-changed/);
    assert.match(styles, /\.routing-guard-badge/);
    assert.match(styles, /\.routing-confidence\.is-high/);
});


test('routing observatory translates portrait question guard reason', () => {
    assert.match(ui, /reason_instructional_portrait_question/);
    assert.match(translations, /reason_instructional_portrait_question/);
    assert.match(translations, /Frage zur Porträterstellung/);
});
