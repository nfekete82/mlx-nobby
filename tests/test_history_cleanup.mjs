import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Small DOM harness: exercise the actual shared controls without a UI dependency.
const elements = [];
class Element {
    children = [];
    dataset = {};
    listeners = {};
    disabled = false;
    textContent = '';
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    replaceChildren(...children) { this.children = children; }
    setAttribute() {}
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { return this.listeners.click(); }
}
const document = {
    createElement() { const element = new Element(); elements.push(element); return element; },
    querySelectorAll(selector) {
        const kind = selector.match(/"(.+)"/)[1];
        return elements.filter(element => element.dataset.historyKind === kind);
    },
};
let confirmed = false;
let response;
const requests = [];
const window = { confirm: () => confirmed };
vm.runInNewContext(fs.readFileSync(new URL('../frontend/assets/history-cleanup.js', import.meta.url), 'utf8'), {
    document, window,
    fetch: async (url, options) => { requests.push({ url, options }); return response; },
});
const mount = window.MLXHistoryCleanup.mount;
const downloads = new Element();
let refreshed = 0;
mount(downloads, { kind: 'downloads', onComplete: () => { refreshed++; } });
const buttons = downloads.children[0].children;
assert.deepEqual(buttons.map(button => button.textContent), [
    'Delete completed', 'Delete failed', 'Clear history',
]);
await buttons[0].click();
assert.equal(requests.length, 0, 'cancelling confirmation sends no request');
confirmed = true;
let finish;
response = new Promise(resolve => { finish = resolve; });
const first = buttons[0].click();
assert.ok(buttons.every(button => button.disabled));
await buttons[1].click();
const rerender = new Element();
mount(rerender, { kind: 'downloads' });
assert.ok(rerender.children[0].children.every(button => button.disabled));
await rerender.children[0].children[2].click();
assert.equal(requests.length, 1, 'duplicate requests remain blocked across rerenders');
finish({ ok: true, json: async () => ({ removed: 2, remaining: 3 }) });
await first;
assert.equal(requests[0].url, '/api/mlx/jobs/cleanup');
assert.equal(requests[0].options.method, 'POST');
assert.deepEqual(JSON.parse(requests[0].options.body), { scope: 'completed' });
assert.equal(refreshed, 1);
assert.ok(buttons.every(button => !button.disabled));
assert.match(downloads.children[1].textContent, /2 entries removed/);

const batch = new Element();
mount(batch, { kind: 'batch', onComplete: () => { refreshed++; } });
response = { ok: false, status: 500, json: async () => ({ detail: 'Store nicht lesbar' }) };
await batch.children[0].children[1].click();
assert.equal(requests.at(-1).url, '/api/mlx/batch/cleanup');
assert.deepEqual(JSON.parse(requests.at(-1).options.body), { scope: 'failed' });
assert.match(batch.children[1].textContent, /Store nicht lesbar/);
assert.equal(refreshed, 1, 'failed cleanup does not pretend success');
assert.ok(batch.children[0].children.every(button => !button.disabled));
response = { ok: true, json: async () => ({ removed: 0, remaining: 3 }) };
await batch.children[0].children[2].click();
assert.deepEqual(JSON.parse(requests.at(-1).options.body), { scope: 'all' });
assert.equal(refreshed, 2);
console.log('History cleanup UI: confirmation, filters, refresh, errors and concurrency passed.');
