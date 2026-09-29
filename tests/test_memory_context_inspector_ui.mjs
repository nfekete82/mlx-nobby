import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const inspector = fs.readFileSync(
    new URL('../frontend/assets/chat/memory-context-inspector.js', import.meta.url),
    'utf8'
);
const routes = fs.readFileSync(
    new URL('../backend/memory_manager_routes.py', import.meta.url),
    'utf8'
);
const translations = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/memory-context-inspector.json', import.meta.url),
    'utf8'
));


test('context inspector exposes read-only retrieval diagnostics', () => {
    assert.match(inspector, /\/api\/mlx\/memory\/inspect/);
    assert.match(inspector, /memoryContextInspectorQuery/);
    assert.match(inspector, /memoryContextInspectorLimit/);
    assert.match(inspector, /semantic/);
    assert.match(inspector, /lexical/);
    assert.match(inspector, /importance/);
    assert.match(inspector, /confidence/);
    assert.match(inspector, /recency/);
    assert.match(inspector, /Injected context preview/);
    assert.doesNotMatch(inspector, /method:\s*['"](?:POST|PATCH|DELETE)/);
});


test('context inspector is injected after memory modules and before chat runtime', () => {
    const base = routes.indexOf('memory-manager.js?v=');
    const consolidation = routes.indexOf('memory-manager-consolidation.js?v=');
    const inspectorIndex = routes.indexOf('memory-context-inspector.js?v=');
    const chat = routes.indexOf('CHAT_SCRIPT_MARKER');
    assert.ok(base >= 0);
    assert.ok(consolidation > base);
    assert.ok(inspectorIndex > consolidation);
    assert.ok(chat >= 0);
});


test('context inspector translations stay aligned in German and English', () => {
    assert.deepEqual(
        Object.keys(translations.de).sort(),
        Object.keys(translations.en).sort()
    );
    assert.equal(translations.de.inspect, 'Context prüfen');
    assert.equal(translations.en.inspect, 'Inspect context');
});
