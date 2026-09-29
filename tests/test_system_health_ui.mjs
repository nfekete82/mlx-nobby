import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/system-health.js', import.meta.url),
    'utf8',
);

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
    getElementById() {
        return null;
    },
    addEventListener() {},
};

const context = {
    console,
    window,
    document,
    globalThis: {
        confirm: () => true,
    },
    fetch: async () => {
        throw new Error('mount should not fetch without serviceHealthGrid');
    },
    navigator: {},
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
    encodeURIComponent,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/system-health.js',
});

const test = window.MLXSystemHealth.__test;

assert.equal(test.formatBytes(1024), '1 KB');
assert.equal(test.formatBytes(1024 * 1024), '1 MB');
assert.equal(test.formatDuration(59), '59s');
assert.equal(test.formatDuration(120), '2m');
assert.equal(test.statusLabel('healthy'), 'Healthy');
assert.equal(test.statusLabel('degraded'), 'Degraded');
assert.equal(test.statusLabel('down'), 'Down');

const diagnosis = test.diagnosisText({
    checked_at: 1,
    services: [{
        name: 'Speech',
        status: 'healthy',
        port: 8050,
        pid: 123,
        rss_bytes: 1024 * 1024,
        uptime_seconds: 120,
        current_model: 'tts-model',
        active_job_id: null,
        latency_ms: 5,
        last_error: null,
        detail: null,
    }],
    stuck_jobs: [{
        kind: 'image',
        id: 'a'.repeat(24),
        phase: 'running',
        idle_seconds: 95,
        progress: 0.4,
        current_step: 12,
        total_steps: 30,
    }],
});

assert.match(diagnosis, /Speech \| healthy \| port=8050/);
assert.match(diagnosis, /stuck_jobs=1/);
assert.match(diagnosis, /image \| a{24} \| running/);

console.log('system health ui tests passed');
