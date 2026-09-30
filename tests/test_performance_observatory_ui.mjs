import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/performance-observatory.js', import.meta.url),
    'utf8',
);

assert.match(source, /\/api\/mlx\/performance\/observatory\?limit=40/);
assert.match(source, /performanceObservatoryV2/);
assert.match(source, /serviceHealthGrid/);
assert.match(source, /tokens_per_second/);
assert.match(source, /headroom_gb/);
assert.match(source, /swap_used_gb/);
assert.match(source, /performance-observatory-runtime state-/);
assert.match(source, /runtime_start/);
assert.match(source, /warm_starts/);
assert.match(source, /cold_starts/);
assert.match(source, /recent_calls/);
assert.match(source, /recent_jobs/);

const window = {
    MLXI18n: {
        getLocale: () => 'en-US',
    },
    addEventListener() {},
};
window.window = window;

const document = {
    readyState: 'complete',
    documentElement: { lang: 'en' },
    head: { appendChild() {} },
    getElementById() {
        return null;
    },
    addEventListener() {},
};

const context = {
    console,
    window,
    document,
    navigator: { language: 'en-US' },
    fetch: async () => {
        throw new Error('mount should not fetch without serviceHealthGrid');
    },
    setInterval() {
        return 1;
    },
    clearInterval() {},
    setTimeout() {},
    Date,
    JSON,
    Number,
    String,
    Math,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/performance-observatory.js',
});

const test = window.MLXPerformanceObservatory.__test;

assert.equal(test.formatDuration(250), '250 ms');
assert.equal(test.formatDuration(1500), '1.5 s');
assert.equal(test.formatRate(18.75), '18.8 tok/s');
assert.equal(test.formatGb(18.25), '18.3 GB');
assert.equal(test.stateText('warm'), 'Warm');
assert.equal(test.stateText('cold'), 'Cold');
assert.equal(test.pressureText('critical'), 'Critical');
assert.equal(test.statusText('completed'), 'Completed');

console.log('performance observatory ui tests passed');
