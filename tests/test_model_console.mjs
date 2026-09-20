import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/models.js', import.meta.url),
    'utf8',
);
const html = fs.readFileSync(
    new URL('../frontend/chat.html', import.meta.url),
    'utf8',
);
const css = fs.readFileSync(
    new URL('../frontend/assets/chat.css', import.meta.url),
    'utf8',
);

const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    window: { fetch: globalThis.fetch },
    document: {
        getElementById: () => null,
        addEventListener: () => {},
    },
};
sandbox.window.window = sandbox.window;
vm.runInNewContext(source, sandbox, { filename: 'models.js' });

const test = sandbox.window.MLXModelConsole.__test;

assert.match(html, /data-settings-tab="models"/);
assert.match(html, /data-model-console-tab="runtime"/);
assert.match(html, /data-model-console-tab="storage"/);
assert.match(html, /id="modelConsoleDialog"/);
assert.match(html, /models\.js\?v=20260906-runtime-console/);
assert.match(css, /@media \(max-width: 700px\)/);
assert.match(css, /prefers-reduced-motion: reduce/);

assert.equal(
    test.displayName('/example/Models/Qwen3.8-27B-Uncensored-MLX/6-bit'),
    'Qwen3.8 27B Uncensored',
);
assert.equal(
    test.displayName('TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-mixed-6.4bit'),
    'Qwen3.6 35B A3B Heretic',
);
assert.equal(test.formatBytes(23_565_963_846), '21.95 GB');
sandbox.window.MLXI18n = { getLocale: () => 'de-DE' };
assert.equal(test.formatBytes(23_565_963_846), '21,95 GB');
delete sandbox.window.MLXI18n;
assert.equal(test.formatUptime(null), null);
assert.equal(test.formatUptime(8_040), '2h 14m');

assert.equal(test.validateModelInput('', '').valid, false);
assert.equal(test.validateModelInput('bad alias', 'owner/model').valid, false);
assert.equal(test.validateModelInput('qwen38', 'owner/model').valid, true);
assert.equal(test.aliasExists('QWEN38', [{ alias: 'qwen38' }]), true);

// Both the browser and agent endpoint exercise the same compatibility cases.
const validationCases = JSON.parse(fs.readFileSync(
    new URL('./fixtures/model_validation.json', import.meta.url), 'utf8',
));
validationCases.push({ alias: 'a'.repeat(97), repo: 'owner/model', valid: true });
for (const { alias, repo, valid } of validationCases) {
    assert.equal(test.validateModelInput(alias, repo).valid, valid, JSON.stringify({ alias, repo }));
}

test.state.aliases = {
    current: 'owner/active',
    models: [
        { alias: 'active', repo: 'owner/active', active: true, local: false },
        { alias: 'local', repo: '/Models/local', active: false, local: true },
    ],
};
test.state.status = { online: true, model: 'owner/active', thinking: false };
test.state.runtimeAction = null;
test.state.error = null;
test.state.cache = {
    models: [{ repo: 'owner/active', complete: true, size_bytes: 1024 }],
};
test.state.jobs = [];

assert.equal(test.activeModel().alias, 'active');
assert.deepEqual(
    JSON.parse(JSON.stringify(test.statusView())),
    { kind: 'online', label: 'Online' },
);
assert.equal(test.modelAvailability(test.state.aliases.models[0]).state, 'ready');
assert.equal(test.modelAvailability(test.state.aliases.models[1]).state, 'ready');

test.state.status = { online: false, model: 'owner/active', thinking: false };
assert.equal(test.statusView().kind, 'offline');
test.state.runtimeAction = { type: 'restart', phase: 'initializing', observedOffline: true };
assert.equal(test.statusView().kind, 'starting');
assert.equal(test.deriveActionSteps(test.state.runtimeAction)[0].mode, 'done');
assert.equal(test.canBeginRuntimeAction(), false);
test.state.runtimeAction = null;
assert.equal(test.canBeginRuntimeAction(), true);

test.setDependencies({ wait: async () => {} });

const restartUpdates = [];
const restartStatuses = [
    { online: false, model: 'owner/active' },
    { online: true, model: 'owner/active' },
];
const restarted = await test.monitorMutation({
    type: 'restart',
    expectedRepo: 'owner/active',
    commandPromise: Promise.resolve({ ok: true }),
    fetchStatus: async () => restartStatuses.shift() || { online: true, model: 'owner/active' },
    onUpdate: action => restartUpdates.push(action),
    timeoutMs: 1000,
});
assert.equal(restarted.online, true);
assert.equal(restartUpdates.some(item => item.observedOffline), true);
assert.equal(restartUpdates.at(-1).phase, 'ready');

const stopped = await test.monitorMutation({
    type: 'stop',
    commandPromise: Promise.resolve({ ok: true }),
    fetchStatus: async () => ({ online: false, model: 'owner/active' }),
    timeoutMs: 1000,
});
assert.equal(stopped.online, false);

const started = await test.monitorMutation({
    type: 'start',
    expectedRepo: 'owner/active',
    commandPromise: Promise.resolve({ ok: true }),
    fetchStatus: async () => ({ online: true, model: 'owner/active' }),
    timeoutMs: 1000,
});
assert.equal(started.model, 'owner/active');

const switched = await test.monitorMutation({
    type: 'switch',
    expectedRepo: 'owner/new',
    commandPromise: Promise.resolve({ ok: true }),
    fetchStatus: async () => ({ online: true, model: 'owner/new' }),
    timeoutMs: 1000,
});
assert.equal(switched.model, 'owner/new');

await assert.rejects(
    test.monitorMutation({
        type: 'start',
        commandPromise: Promise.resolve({ ok: true }),
        fetchStatus: async () => ({ online: false }),
        timeoutMs: 0,
    }),
    /did not confirm the expected state in time/,
);

test.state.cache.models = [{ repo: 'owner/broken', complete: false }];
test.state.jobs = [{ target: 'broken', status: 'failed' }];
assert.equal(
    test.modelAvailability({ alias: 'broken', repo: 'owner/broken', local: false }).state,
    'error',
);

assert.match(source, /\/api\/mlx\/thinking\//);
assert.match(source, /\/api\/mlx\/models\/add/);
assert.match(source, /confirm-remove-model/);
assert.match(source, /confirm-delete-cache/);
assert.doesNotMatch(source, /Math\.random\(\).*progress|progress.*Math\.random\(/i);

console.log('Model Runtime Console tests passed');
