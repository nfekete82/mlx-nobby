import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');
const runtime = fs.readFileSync('frontend/assets/chat/runtime.js', 'utf8');

const headerStart = html.indexOf('<div class="model-heading">');
const headerEnd = html.indexOf('<div class="model-meta">', headerStart);
const header = html.slice(headerStart, headerEnd);

test('RAM indicator is adjacent to the model name and hidden until measured', () => {
    assert.ok(headerStart >= 0);
    assert.ok(header.indexOf('id="modelTitle"') < header.indexOf('id="modelMemory"'));
    assert.match(header, /id="modelMemory"[\\s\\S]*?hidden/);
    assert.match(css, /\\.model-memory\\[hidden\\]/);
    assert.match(html, /runtime\\.js\\?v=20261019-model-ram-header/);
});

function harness() {
    const from = runtime.indexOf('function formatHeaderMemoryGb(');
    const until = runtime.indexOf('async function loadStatus()', from);
    assert.ok(from > 0 && until > from, 'memory functions should be present');
    const memory = { hidden: true, textContent: '' };
    const events = {};
    const timers = [];
    let system = { mlx: { memory_mb: 20480 }, system: { total_gb: 48 } };
    let switching = false;
    const sandbox = {
        modelMemory: memory,
        document: {
            visibilityState: 'visible',
            addEventListener(name, callback) { events[name] = callback; }
        },
        headerMemoryInterval: null,
        headerMemoryRefreshing: false,
        headerMemoryRevision: 0,
        isSwitching: () => switching,
        fetchSystem: async () => system,
        setInterval(callback, period) { timers.push({ callback, period }); return 1; },
        console,
    };
    vm.runInNewContext(runtime.slice(from, until), sandbox);
    return {
        memory, events, timers, sandbox,
        setSystem(value) { system = value; },
        setSwitching(value) { switching = value; }
    };
}

test('displays real MLX-process RSS against installed unified memory', () => {
    const h = harness();
    h.sandbox.renderHeaderMemory({ mlx: { memory_mb: 20480 }, system: { total_gb: 48 } });
    assert.equal(h.memory.textContent, 'RAM 20 / 48 GB');
    assert.equal(h.memory.hidden, false);
    h.sandbox.renderHeaderMemory({ mlx: { memory_mb: 21913.6 }, system: { total_gb: 48 } });
    assert.equal(h.memory.textContent, 'RAM 21,4 / 48 GB');
    h.sandbox.renderHeaderMemory({ mlx: { memory_mb: 0 }, system: { total_gb: 48 } });
    assert.equal(h.memory.hidden, true);
    h.sandbox.renderHeaderMemory({ mlx: { memory_mb: 20480 }, system: {} });
    assert.equal(h.memory.hidden, true);
});

test('refresh is periodic, visibility-aware and invalidates memory during model switches', async () => {
    const h = harness();
    h.sandbox.initHeaderMemory();
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(h.memory.textContent, 'RAM 20 / 48 GB');
    assert.equal(h.timers.length, 1);
    assert.equal(h.timers[0].period, 15000);
    h.sandbox.initHeaderMemory();
    assert.equal(h.timers.length, 1);

    h.setSystem({ mlx: { memory_mb: 10240 }, system: { total_gb: 48 } });
    h.sandbox.resetHeaderMemory();
    h.setSwitching(true);
    await h.sandbox.refreshHeaderMemory();
    assert.equal(h.memory.hidden, true);
    h.setSwitching(false);
    await h.sandbox.refreshHeaderMemory();
    assert.equal(h.memory.textContent, 'RAM 10 / 48 GB');

    h.sandbox.document.visibilityState = 'hidden';
    h.setSystem({ mlx: { memory_mb: 5120 }, system: { total_gb: 48 } });
    await h.sandbox.refreshHeaderMemory();
    assert.equal(h.memory.textContent, 'RAM 10 / 48 GB');
    h.sandbox.document.visibilityState = 'visible';
    await h.events.visibilitychange();
    await Promise.resolve();
    assert.equal(h.memory.textContent, 'RAM 5 / 48 GB');
});
