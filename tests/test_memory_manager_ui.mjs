import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const manager = fs.readFileSync(
    new URL('../frontend/assets/chat/memory-manager.js', import.meta.url),
    'utf8'
);
const routes = fs.readFileSync(
    new URL('../backend/memory_manager_routes.py', import.meta.url),
    'utf8'
);
const entrypoint = fs.readFileSync(
    new URL('../backend/entrypoint.py', import.meta.url),
    'utf8'
);


test('memory manager exposes the full local CRUD workflow', () => {
    assert.match(manager, /\/api\/mlx\/memory\?include_disabled=true/);
    assert.match(manager, /method: 'POST'/);
    assert.match(manager, /method: 'PATCH'/);
    assert.match(manager, /method: 'DELETE'/);
    assert.match(manager, /pinned:/);
    assert.match(manager, /enabled:/);
    assert.match(manager, /memoryManagerSearch/);
    assert.match(manager, /memoryManagerFilter/);
});


test('memory manager is injected before the hard-coded settings router', () => {
    assert.match(routes, /memory-manager\.js/);
    assert.match(routes, /CHAT_SCRIPT_MARKER/);
    assert.match(entrypoint, /MemoryManagerUiMiddleware/);
    assert.match(entrypoint, /install_memory_manager_routes/);
});


test('memory manager supports direct settings navigation and both UI languages', () => {
    assert.match(manager, /requestedAtBoot/);
    assert.match(manager, /\/settings\/memory/);
    assert.match(manager, /const COPY =/);
    assert.match(manager, /de:/);
    assert.match(manager, /en:/);
    assert.match(manager, /mlx-language-changed/);
});
