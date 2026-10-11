import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/assets/chat/app-version.js', import.meta.url), 'utf8');

async function harness() {
    const observers = new Set();
    const pending = new Set();
    const byId = new Map();
    function mutate() {
        for (const observer of observers) if (observer.active) pending.add(observer);
    }
    class Element {
        children = [];
        dataset = {};
        _text = '';
        get textContent() { return this._text; }
        set textContent(value) { this._text = value; mutate(); }
        querySelector(selector) {
            if (selector === '[data-mlx-app-version]') return this.children.find(c => c.dataset.mlxAppVersion === '1') || null;
            return null;
        }
        prepend(node) { this.children.unshift(node); mutate(); }
    }
    const style = new Element();
    style._text = 'initial historical layout';
    byId.set('mlxChatHistoryPolish', style);
    const document = {
        documentElement: {},
        getElementById: id => byId.get(id) || null,
        createElement: () => new Element(),
    };
    class MutationObserver {
        constructor(callback) { this.callback = callback; this.active = false; observers.add(this); }
        observe(target, options) {
            assert.equal(target, document.documentElement);
            assert.equal(options.childList, true);
            assert.equal(options.subtree, true);
            this.active = true;
        }
        disconnect() { this.active = false; pending.delete(this); }
    }
    const window = {};
    vm.runInNewContext(source, {
        document, window, MutationObserver,
        fetch: async () => ({ok: true, json: async () => ({version: '15.0', commit: 'fixture'})}),
    });
    await new Promise(resolve => setImmediate(resolve));
    function flush() {
        let deliveries = 0;
        while (pending.size) {
            assert.ok(++deliveries < 20, 'DOM observer must settle instead of starving the delayed health-panel mount');
            const observer = pending.values().next().value;
            pending.delete(observer);
            if (observer.active) observer.callback([], observer);
        }
        return deliveries;
    }
    return {style, byId, Element, mutate, flush, observers, window};
}

test('an unrelated DOM mutation settles while system health is still loading', async () => {
    const h = await harness();
    assert.equal(h.byId.has('systemHealthV1'), false);
    h.mutate();
    assert.equal(h.flush(), 1);
    assert.match(h.style.textContent, /translate:112px 0/);
    h.mutate();
    assert.equal(h.flush(), 1);
});

test('the delayed health panel receives its version badge and the mount observer disconnects', async () => {
    const h = await harness();
    h.mutate();
    h.flush();
    const health = new h.Element();
    h.byId.set('systemHealthV1', health);
    h.mutate();
    h.flush();
    assert.equal(health.children.length, 1);
    assert.equal(health.children[0].textContent, 'MLX Nobby v15.0 · Build fixture');
    assert.equal([...h.observers].filter(o => o.active).length, 0);
    h.mutate();
    assert.equal(h.flush(), 0);
});
