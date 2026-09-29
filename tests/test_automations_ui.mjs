import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/automations.js', import.meta.url),
    'utf8',
);

const window = {};
window.window = window;

const document = {
    readyState: 'loading',
    addEventListener() {},
};

const context = {
    window,
    document,
    navigator: { language: 'en-US' },
    console,
    Intl,
    Date,
    Array,
    String,
    Number,
    Object,
    Promise,
    Error,
    Set,
    Map,
    setTimeout() { return 1; },
    clearTimeout() {},
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/automations.js',
});

const api = window.MLXAutomationsUI;
assert.equal(typeof api?.show, 'function');
assert.equal(typeof api?.refresh, 'function');
assert.equal(typeof api?.openEditor, 'function');
assert.equal(typeof api?.openScoutTemplate, 'function');
assert.equal(typeof api?.timezoneName, 'function');
assert.equal(typeof api?.__test?.scheduleLabel, 'function');

assert.equal(
    api.__test.scheduleLabel({ schedule_type: 'daily', schedule_time: '09:30' }),
    'Daily · 09:30',
);
assert.equal(
    api.__test.scheduleLabel({ schedule_type: 'hourly', schedule_minute: 5 }),
    'Hourly · :05',
);
assert.equal(
    api.__test.scheduleLabel({ schedule_type: 'weekly', schedule_weekday: 6, schedule_time: '10:00' }),
    'Weekly · Sunday · 10:00',
);
assert.equal(
    api.__test.resultSummary({ result: { kind: 'model_scout', count: 7 } }),
    '7 candidates found',
);
assert.equal(api.__test.statusLabel('needs_approval'), 'Needs approval');
assert.ok(api.timezoneName());

console.log('Automations UI helpers passed.');
