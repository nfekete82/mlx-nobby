import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../frontend/assets/chat/models.js', import.meta.url), 'utf8');

// Small DOM adapter; native details interaction is additionally exercised in Chromium.
class Element {
    constructor(tag = 'div') {
        this.tag = tag;
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.open = false;
        this.classList = { toggle() {} };
    }
    get childNodes() { return this.children; }
    set innerHTML(value) { assert.equal(value, ''); this.children = []; }
    set textContent(value) { this.text = String(value); }
    get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    appendChild(child) {
        if (child.tag === 'fragment') this.children.push(...child.children);
        else this.children.push(child);
        return child;
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener() {}
    querySelector(selector) {
        return this.children.find(child => child.className?.split(' ').includes(selector.slice(1)))
            || this.children.map(child => child.querySelector(selector)).find(Boolean) || null;
    }
    querySelectorAll() { return []; }
}

function setup() {
    const content = new Element();
    const root = new Element();
    const timers = new Map();
    let nextTimer = 0;
    const events = new Map();
    const requests = [];
    const sandbox = {
        console,
        setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
        clearTimeout(id) { timers.delete(id); },
        document: {
            getElementById(id) { return { modelConsole: root, modelConsoleContent: content }[id] || null; },
            createElement: tag => new Element(tag),
            createDocumentFragment: () => new Element('fragment'),
            createTextNode: text => Object.assign(new Element('text'), { textContent: text }),
            addEventListener(name, callback) { events.set(name, callback); },
        },
        window: {},
    };
    vm.runInNewContext(source, sandbox);
    const api = sandbox.window.MLXModelConsole;
    api.__test.setDependencies({ fetch: url => new Promise(resolve => requests.push({ url, resolve })) });
    function finishBatch(pid = 1234, failed = false) {
        const batch = requests.splice(0);
        assert.equal(batch.length, 5, 'exactly one endpoint batch in flight');
        for (const request of batch) {
            const data = /\/(aliases|cache)$/.test(request.url) ? { models: [] }
                : request.url.endsWith('/jobs') ? { jobs: [] }
                : request.url.endsWith('/system') ? { mlx: { pid } } : {};
            request.resolve({ ok: !failed, status: failed ? 503 : 200, json: async () => data });
        }
    }
    function firePeriodic() {
        assert.equal(timers.size, 1);
        const [id, timer] = [...timers][0];
        assert.equal(timer.delay, 15000);
        timers.delete(id);
        return timer.callback();
    }
    return { api, content, timers, events, requests, finishBatch, firePeriodic,
        details: () => content.querySelector('.model-console-technical') };
}

async function ready(h) {
    h.api.setTab('runtime');
    h.api.open();
    const pending = h.api.load();
    assert.equal(h.content.attributes['aria-busy'], 'true');
    h.finishBatch();
    await pending;
    assert.equal(h.content.attributes['aria-busy'], 'false');
    assert.equal(h.details().open, false);
}

test('background and periodic refresh preserve open/closed details and update runtime data', async () => {
    const h = setup();
    await ready(h);
    for (const [opened, pid] of [[true, 2345], [false, 3456]]) {
        const previous = h.details();
        previous.open = opened;
        const pending = h.api.load();
        assert.equal(h.content.attributes['aria-busy'], 'true');
        assert.equal(h.details(), previous, 'existing content stays visible');
        h.finishBatch(pid);
        await pending;
        assert.notEqual(h.details(), previous, 'runtime content really updates');
        assert.equal(h.details().open, opened);
        assert.match(h.content.textContent, new RegExp(String(pid)));
        assert.equal(h.content.attributes['aria-busy'], 'false');
    }
    h.details().open = true;
    const periodic = h.firePeriodic();
    h.finishBatch(4567);
    await periodic;
    assert.equal(h.details().open, true);
    assert.match(h.content.textContent, /4567/);
    h.events.get('mlx-language-changed')();
    assert.equal(h.details().open, true);
    h.api.close();
    assert.equal(h.timers.size, 0);
});

test('forced refreshes coalesce behind one flight and stay busy until fresh data arrives', async () => {
    const h = setup();
    await ready(h);
    h.details().open = true;
    const first = h.api.load();
    assert.equal(h.api.load(), first);
    assert.equal(h.api.load({ force: true }), first);
    assert.equal(h.api.load({ force: true }), first);
    assert.equal(h.requests.length, 5, 'force never starts parallel batches');
    h.finishBatch(2345);
    // Drain promises to the trailing request, without real timers or sleeps.
    for (let i = 0; i < 20 && !h.requests.length; i++) await Promise.resolve();
    assert.equal(h.requests.length, 5, 'multiple force requests create one trailing batch');
    assert.equal(h.content.attributes['aria-busy'], 'true');
    assert.doesNotMatch(h.content.textContent, /2345/, 'intermediate response cannot rerender stale data');
    assert.equal(h.details().open, true);
    h.finishBatch(3456);
    await first;
    assert.equal(h.requests.length, 0);
    assert.match(h.content.textContent, /3456/);
    assert.doesNotMatch(h.content.textContent, /2345/);
    assert.equal(h.content.attributes['aria-busy'], 'false');
    assert.equal(h.details().open, true);
    h.api.close();
});

test('open is idempotent; tab changes reset details; reopening refreshes; errors finish loading', async () => {
    const h = setup();
    await ready(h);
    h.details().open = true;
    const previous = h.details();
    const scheduled = [...h.timers.keys()];
    h.api.open();
    assert.equal(h.details(), previous);
    assert.deepEqual([...h.timers.keys()], scheduled);
    assert.equal(h.requests.length, 0);
    h.api.setTab('runtime');
    assert.equal(h.details().open, true);
    for (const tab of ['models', 'storage', 'downloads']) {
        h.api.setTab(tab);
        assert.equal(h.content.dataset.activeModelTab, tab);
    }
    h.api.setTab('runtime');
    assert.equal(h.details().open, false);
    h.api.close();
    h.api.open();
    const [id, timer] = [...h.timers][0];
    assert.equal(timer.delay, 0, 'hidden to visible requests fresh data');
    h.timers.delete(id);
    const pending = timer.callback();
    h.finishBatch(1234, true);
    await pending;
    assert.equal(h.content.attributes['aria-busy'], 'false');
    assert.ok(h.api.__test.state.error);
    assert.match(h.content.textContent, /1234/, 'last valid data survives a request failure');
    h.api.close();
});
