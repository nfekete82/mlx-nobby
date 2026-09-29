import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/performance.js', import.meta.url),
    'utf8'
);

function createSandbox() {
    let now = 1000;
    let nextTimerId = 1;
    const timers = new Map();
    const frames = [];
    const renders = [];
    let saves = 0;

    const FakeDate = class extends Date {
        static now() {
            return now;
        }
    };

    const sandbox = {
        console,
        Date: FakeDate,
        setTimeout(callback, delay) {
            const id = nextTimerId++;
            timers.set(id, { callback, delay });
            return id;
        },
        clearTimeout(id) {
            timers.delete(id);
        },
        requestAnimationFrame(callback) {
            frames.push(callback);
            return frames.length;
        },
        document: {
            hidden: false,
            addEventListener() {}
        },
        window: {
            addEventListener() {},
            MLXChatSessions: {
                saveSessions() {
                    saves += 1;
                }
            },
            MLXChatRendering: {
                renderMessages(options) {
                    renders.push(options || {});
                }
            }
        }
    };

    sandbox.window.window = sandbox.window;
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);

    return {
        sandbox,
        frames,
        renders,
        timers,
        get saves() {
            return saves;
        },
        setNow(value) {
            now = value;
        }
    };
}

test('chat persistence saves immediately, then coalesces burst writes', () => {
    const env = createSandbox();
    const sessions = env.sandbox.window.MLXChatSessions;

    assert.equal(env.sandbox.window.MLXChatPerformance.mounted, true);

    sessions.saveSessions();
    assert.equal(env.saves, 1);

    sessions.saveSessions();
    sessions.saveSessions();

    assert.equal(env.saves, 1);
    assert.equal(env.timers.size, 1);

    const [{ callback, delay }] = Array.from(env.timers.values());
    assert.equal(delay, 500);

    env.setNow(1500);
    callback();

    assert.equal(env.saves, 2);
});

test('content renders are merged into one animation frame', () => {
    const env = createSandbox();
    const rendering = env.sandbox.window.MLXChatRendering;

    rendering.renderMessages({ contentUpdated: true, source: 'first' });
    rendering.renderMessages({ contentUpdated: true, source: 'second' });

    assert.equal(env.renders.length, 0);
    assert.equal(env.frames.length, 1);

    env.frames.shift()();

    assert.equal(env.renders.length, 1);
    assert.equal(env.renders[0].contentUpdated, true);
    assert.equal(env.renders[0].source, 'second');
});

test('non-content render remains synchronous', () => {
    const env = createSandbox();
    const rendering = env.sandbox.window.MLXChatRendering;

    rendering.renderMessages({ contentUpdated: false, reason: 'language' });

    assert.equal(env.renders.length, 1);
    assert.equal(env.frames.length, 0);
    assert.equal(env.renders[0].reason, 'language');
});
