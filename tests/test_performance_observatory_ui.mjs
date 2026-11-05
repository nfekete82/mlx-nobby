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
assert.match(source, /vision_summary/);
assert.match(source, /vision_first_content/);
assert.match(source, /vision_tokens_per_second/);
assert.match(source, /metricValue\(vision\.first_content_ms, formatDuration\)/);
assert.match(source, /metricValue\(vision\.tokens_per_second, formatRate\)/);
assert.match(source, /headroom_gb/);
assert.match(source, /swap_used_gb/);
assert.match(source, /runtimes\.memory4b/);
assert.match(source, /system\?\.admission\?\.image/);
assert.match(source, /system\?\.admission\?\.video/);
assert.match(source, /performance-observatory-runtime state-/);
assert.match(source, /runtime_start/);
assert.match(source, /warm_starts/);
assert.match(source, /cold_starts/);
assert.match(source, /handoff_ms/);
assert.match(source, /chat_releases/);
assert.match(source, /image_preserves/);
assert.match(source, /image_preserve_samples/);
assert.match(source, /handoff_stages_ms/);
assert.match(source, /performanceHandoffBlock/);
assert.match(source, /performanceImageHandoffBlock/);
assert.match(source, /memory_api_ready/);
assert.match(source, /memory_resume/);
assert.match(source, /chat_restore/);
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

assert.equal(test.formatDuration(null), '—');
assert.equal(test.formatDuration(undefined), '—');
assert.equal(test.formatDuration(''), '—');
assert.equal(test.formatDuration(0), '0 ms');
assert.equal(test.formatRate(null), '—');
assert.equal(test.formatRate(undefined), '—');
assert.equal(test.formatGb(null), '—');
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
assert.equal(test.budgetText({ state: 'headroom_ok' }), 'Headroom adequate (estimate)');
assert.equal(test.budgetText({ state: 'release_required' }), 'Release other models first');
assert.equal(test.budgetText({ state: 'unknown' }), 'Admission cannot be estimated');
assert.equal(test.memoryActivity({supervisor_state:'running',managed:true}), 'Automatic extraction ready');
assert.equal(test.memoryActivity({supervisor_state:'suspended_media'}), 'Paused for image/video');
assert.equal(test.memoryActivity({supervisor_state:'waiting_for_memory'}), 'Waiting for free RAM');
assert.equal(test.memoryActivity({supervisor_state:'external'}), 'External model (not supervised)');
assert.equal(test.memoryActivity({supervisor_state:'not_installed'}), 'Memory supervisor unavailable');

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

const imageStages = test.imageHandoffMetrics({
    handoff_ms: { count: 1, p50: 1300 },
    handoff_stages_ms: {
        video_wait: { count: 1, p50: 35 },
        chat_restore: { count: 1, p50: 900 }
    }
});
assert.equal(imageStages.length, 7);
assert.equal(imageStages[0].metric.p50, 1300);
assert.equal(imageStages[2].key, 'video_wait');
assert.equal(imageStages[2].metric.p50, 35);
assert.equal(imageStages[6].key, 'chat_restore');
assert.equal(imageStages[6].metric.p50, 900);


console.log('performance observatory ui tests passed');
