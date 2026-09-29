import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const manager = fs.readFileSync(
    new URL('../frontend/assets/chat/memory-manager-consolidation.js', import.meta.url),
    'utf8'
);
const routes = fs.readFileSync(
    new URL('../backend/memory_manager_routes.py', import.meta.url),
    'utf8'
);
const translations = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/memory-manager-consolidation.json', import.meta.url),
    'utf8'
));


test('memory consolidation UI exposes status, cleanup, history and restore actions', () => {
    assert.match(manager, /\/api\/mlx\/memory\/consolidation-status/);
    assert.match(manager, /\/api\/mlx\/memory\/consolidations\?limit=100/);
    assert.match(manager, /\/api\/mlx\/memory\/consolidate/);
    assert.match(manager, /memoryConsolidationHistory/);
    assert.match(manager, /restoreMemory/);
    assert.match(manager, /enabled: true/);
    assert.match(manager, /slot_replacement/);
    assert.match(manager, /semantic_duplicate/);
    assert.match(manager, /lexical_duplicate/);
});


test('card decoration observes card replacement only and cannot recurse on itself', () => {
    assert.match(manager, /listObserver\.observe\(list, \{ childList: true \}\)/);
    assert.doesNotMatch(manager, /listObserver\.observe\(list, \{ childList: true, subtree: true \}\)/);
    assert.match(manager, /data-memory-consolidation-decoration/);
});


test('consolidation manager is injected after the base manager and before chat runtime', () => {
    const base = routes.indexOf('memory-manager.js?v=');
    const consolidation = routes.indexOf('memory-manager-consolidation.js?v=');
    const marker = routes.indexOf('CHAT_SCRIPT_MARKER');
    assert.ok(base >= 0);
    assert.ok(consolidation > base);
    assert.ok(marker >= 0);
});


test('memory consolidation translations stay aligned in German and English', () => {
    assert.deepEqual(
        Object.keys(translations.de).sort(),
        Object.keys(translations.en).sort()
    );
    assert.equal(translations.de.clean, 'Memory bereinigen');
    assert.equal(translations.en.clean, 'Clean up memory');
    assert.equal(translations.de.reason_slot_replacement, 'Aktualisierte Präferenz');
});
