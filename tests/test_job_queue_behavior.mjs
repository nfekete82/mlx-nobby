import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Exercise the shipped module's rendering, cancellation and polling lifecycle.
class Element {
    constructor() { this.children = []; this.listeners = {}; this.dataset = {}; this.style = {}; this.hidden = false; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(child) { this.children = child.children; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    all() { return [this, ...this.children.flatMap(c => c.all())]; }
}

test('Queue loads Agent fields, cancels once, refreshes status and stops polling', async () => {
    const nodes = Object.fromEntries(['jobsPanel', 'jobsPanelContent', 'sidebarJobsButton', 'jobsPanelClose'].map(id => [id, new Element()]));
    const calls = [], timers = new Map();
    let cancelled = false;
    const window = {
        MLXConfirm: async () => true,
        alert: message => assert.fail(message),
        setInterval: (fn, delay) => { assert.equal(delay, 2000); timers.set(1, fn); return 1; }
    };
    const fetch = async (path, init = {}) => {
        calls.push([path, init.method || 'GET']);
        if (path.endsWith('/cancel')) {
            assert.equal(init.method, 'POST');
            cancelled = true;
            return {ok: true};
        }
        return {ok: true, json: async () => path.includes('/batch') ? {jobs: []} : {
            active_count: 0, waiting_count: cancelled ? 0 : 1,
            jobs: [{id: 'a'.repeat(24), kind: 'image', title: 'Queue fixture', progress: 0,
                queue_status: cancelled ? 'cancelled' : 'waiting', queue_position: 1, cancellable: !cancelled}]
        }};
    };
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/job-queue.js', 'utf8'), {
        window, fetch, clearInterval: id => timers.delete(id),
        document: {getElementById: id => nodes[id], documentElement: {lang: 'en'}, head: new Element(),
            createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener() {}}
    });
    window.MLXJobQueue.open();
    await window.MLXJobQueue.refresh();
    let item = nodes.jobsPanelContent.all().find(n => n.dataset.jobId);
    assert.equal(item.dataset.jobState, 'waiting');
    assert.ok(item.all().some(n => n.textContent === 'Waiting · #1'));
    const cancel = item.all().find(n => n.className === 'mlx-queue-cancel');
    await cancel.listeners.click();
    assert.deepEqual(calls.filter(([, method]) => method === 'POST'), [['/api/system/job-queue/image/' + 'a'.repeat(24) + '/cancel', 'POST']]);
    item = nodes.jobsPanelContent.all().find(n => n.dataset.jobId);
    assert.equal(item.dataset.jobState, 'cancelled');
    assert.ok(item.all().some(n => n.textContent === 'Cancelled'));
    assert.ok(!item.all().some(n => n.className === 'mlx-queue-cancel'));
    assert.equal(timers.size, 1);
    nodes.jobsPanel.hidden = true;
    timers.get(1)();
    assert.equal(timers.size, 0);
    window.MLXJobQueue.open();
    nodes.jobsPanelClose.listeners.click();
    assert.equal(timers.size, 0);
});
