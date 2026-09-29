import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/automation-notifications.js', import.meta.url),
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
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 1; },
    clearInterval() {},
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/automation-notifications.js',
});

const api = window.MLXAutomationNotifications;
assert.equal(typeof api?.refresh, 'function');
assert.equal(typeof api?.markRead, 'function');
assert.equal(typeof api?.markAllRead, 'function');
assert.equal(typeof api?.__test?.unreadCount, 'function');
assert.equal(typeof api?.__test?.shouldAnnounce, 'function');

assert.equal(
    api.__test.unreadCount([
        { unread: true },
        { unread: false },
        { unread: true },
    ]),
    2,
);

assert.equal(
    api.__test.shouldAnnounce(
        { unread: true, delivered: false, created_at: 20 },
        10,
    ),
    true,
);
assert.equal(
    api.__test.shouldAnnounce(
        { unread: true, delivered: true, created_at: 20 },
        10,
    ),
    false,
);
assert.equal(
    api.__test.shouldAnnounce(
        { unread: true, delivered: false, created_at: 5 },
        10,
    ),
    false,
);

console.log('Automation notification UI helpers passed.');
