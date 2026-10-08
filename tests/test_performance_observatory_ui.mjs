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
assert.match(source, /handoff_ms/);
assert.match(source, /chat_releases/);
assert.match(source, /handoff_stages_ms/);
assert.match(source, /performanceHandoffBlock/);
assert.match(source, /handoff_release_summary/);
assert.match(source, /t\('handoff'\)/);
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
const localNumber = (value, options) => value.toLocaleString(undefined, options);

assert.equal(test.formatDuration(250), '250 ms');
assert.equal(
    test.formatDuration(1500),
    localNumber(1.5, { maximumFractionDigits: 2 }) + ' s',
);
assert.equal(
    test.formatRate(18.75),
    localNumber(18.75, { maximumFractionDigits: 1 }) + ' tok/s',
);
assert.equal(
    test.formatGb(18.25),
    localNumber(18.25, { maximumFractionDigits: 1 }) + ' GB',
);
assert.equal(test.stateText('warm'), 'Warm');
assert.equal(test.stateText('cold'), 'Cold');
assert.equal(test.pressureText('critical'), 'Critical');
assert.equal(test.statusText('completed'), 'Completed');

const breakdown = test.handoffMetrics({
    handoff_ms: { count: 2, p50: 200 },
    handoff_stages_ms: {
        lease_wait: { count: 2, p50: 30 },
        chat_stop: { count: 1, p50: 90 }
    }
});
assert.equal(breakdown.length, 6);
assert.equal(breakdown[0].key, 'handoff');
assert.equal(breakdown[0].metric.p50, 200);
assert.equal(breakdown[1].key, 'lease_wait');
assert.equal(breakdown[1].metric.p50, 30);
assert.equal(breakdown[5].key, 'chat_stop');
assert.equal(breakdown[5].metric.count, 1);
assert.equal(breakdown[2].metric, undefined);

console.log('performance observatory ui tests passed');
