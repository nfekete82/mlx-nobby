import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/agent-task-mode.js', 'utf8');
const settle = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };

function environment() {
    const observers = [];
    const documentEvents = new Map();
    const windowEvents = new Map();
    const requests = [];
    let selected = null;
    let gate = null;
    let failure = false;
    let deliveries = 0;
    class Element {
        constructor() {
            this.attributes = new Map();
            this.events = new Map();
            this.dataset = new Proxy({}, {
                set: (target, key, value) => {
                    target[key] = value;
                    this.setAttribute('data-' + key.replace(/[A-Z]/g, c => '-' + c.toLowerCase()), value);
                    return true;
                }
            });
        }
        addEventListener(name, handler) {
            const list = this.events.get(name) || [];
            list.push(handler);
            this.events.set(name, list);
        }
        getAttribute(name) { return this.attributes.get(name) ?? null; }
        setAttribute(name, value) {
            this.attributes.set(name, value);
            for (const observer of observers) {
                const options = observer.options;
                if (observer.target !== this || !options.attributes) continue;
                if (options.attributeFilter && !options.attributeFilter.includes(name)) continue;
                // Bound delivery also makes the old self-triggering code fail
                // deterministically instead of hanging the test process.
                if (++deliveries <= 100) queueMicrotask(() => observer.callback([{ attributeName: name }]));
            }
        }
    }
    const header = new Element();
    const send = new Element();
    const input = new Element();
    const elements = { activeWorkspaceHeader: header, sendButton: send, input };
    const window = {
        addEventListener(name, callback) { windowEvents.set(name, callback); }
    };
    const document = {
        hidden: false,
        documentElement: { lang: 'en' },
        getElementById(name) { return elements[name] || null; },
        addEventListener(name, callback) { documentEvents.set(name, callback); }
    };
    const context = vm.createContext({
        window, document, queueMicrotask, console,
        MutationObserver: class {
            constructor(callback) { this.callback = callback; observers.push(this); }
            observe(target, options) { this.target = target; this.options = options; }
        },
        fetch: async url => {
            if (url.startsWith('/i18n/')) return { ok: true, json: async () => ({}) };
            requests.push(url);
            const snapshot = selected;
            if (gate) await gate;
            if (failure) throw new Error('offline');
            return { ok: true, json: async () => ({ active_workspace: snapshot }) };
        }
    });
    vm.runInContext(source, context);
    return {
        api: window.MLXAgentTaskMode, context, requests, header, send, input, document, observers,
        select(value) { selected = value; },
        fail(value) { failure = value; },
        block() { gate = new Promise(resolve => { this.release = () => { gate = null; resolve(); }; }); },
        focus() { windowEvents.get('focus')(); },
        visible() { documentEvents.get('visibilitychange')(); }
    };
}

test('workspace mode settles after one initial read; its DOM markers do not poll', async () => {
    const env = environment();
    await settle();
    assert.equal(env.requests.length, 1);
    assert.equal(env.api.getMode(), 'chat');
    assert.equal(env.header.getAttribute('data-workspace-task-active'), 'false');
    env.header.setAttribute('title', 'Unrelated header change');
    env.header.setAttribute('data-agent-mode', 'chat');
    await settle();
    assert.equal(env.requests.length, 1);
});

test('selection, switch and deactivation still update task mode', async () => {
    const env = environment();
    await settle();
    env.select({ workspace_id: 'first', name: 'First' });
    env.header.setAttribute('data-active', 'true');
    await settle();
    assert.equal(env.api.getMode(), 'task');
    env.select({ workspace_id: 'second', name: 'Second' });
    env.header.setAttribute('data-active', 'true');
    await settle();
    assert.equal((await env.api.consume({ prompt: 'inspect' })).workspaceId, 'second');
    env.select(null);
    env.header.setAttribute('data-active', 'false');
    await settle();
    assert.equal(env.api.getMode(), 'chat');
    assert.equal(await env.api.consume({ prompt: 'hello' }), null);
});

test('concurrent readers share a request, but a later submission checks fresh state', async () => {
    const env = environment();
    await settle();
    env.block();
    const start = env.requests.length;
    const reads = Array.from({ length: 20 }, () => env.api.syncWorkspaceState());
    assert.equal(env.requests.length - start, 1);
    env.release();
    await Promise.all(reads);
    env.select({ workspace_id: 'new' });
    assert.equal((await env.api.consume({ prompt: 'inspect' })).workspaceId, 'new');
    assert.equal(env.requests.length - start, 2);
});

test('focus and visibility coalesce; a change during a read gets a trailing refresh', async () => {
    const env = environment();
    await settle();
    env.block();
    env.focus();
    env.visible();
    await settle();
    assert.equal(env.requests.length, 2);
    env.select({ workspace_id: 'changed' });
    env.header.setAttribute('data-active', 'true');
    await settle();
    assert.equal(env.requests.length, 2);
    env.release();
    await settle();
    assert.equal(env.requests.length, 3);
    assert.equal(env.api.getMode(), 'task');
});

test('failed reads are not cached and submission fails visibly', async () => {
    const env = environment();
    await settle();
    env.fail(true);
    assert.match((await env.api.consume({ prompt: 'inspect' })).error, /offline/);
    env.fail(false);
    env.select({ workspace_id: 'recovered' });
    assert.equal((await env.api.consume({ prompt: 'inspect' })).workspaceId, 'recovered');
});

test('repeated mount and script evaluation do not duplicate composer handlers', async () => {
    const env = environment();
    await settle();
    for (let i = 0; i < 5; i++) env.api.mount();
    vm.runInContext(source, env.context);
    await settle();
    assert.equal(env.send.events.get('click').length, 1);
    assert.equal(env.input.events.get('keydown').length, 1);
    assert.equal(env.observers.length, 1);
    assert.equal(env.requests.length, 1);
});
