import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

function environment(file) {
    const ids = new Map();
    const intervals = [];
    const events = new Map();
    const observers = [];
    const requests = [];
    let blocked = null;
    class Element {
        constructor() {
            this.children = [];
            this.dataset = {};
            this.hidden = false;
            this.parentElement = null;
            this.nodes = new Map();
            this.classes = new Set();
            this.classList = { contains: value => this.classes.has(value) };
        }
        set id(value) { this._id = value; ids.set(value, this); }
        get id() { return this._id; }
        get lastChild() { return this.children.at(-1); }
        append(...nodes) { for (const node of nodes) this.appendChild(node); }
        appendChild(node) { node.parentElement = this; this.children.push(node); return node; }
        insertBefore(node) { return this.appendChild(node); }
        replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
        addEventListener() {}
        setAttribute() {}
        querySelector(selector) {
            if (!this.nodes.has(selector)) this.nodes.set(selector, new Element());
            return this.nodes.get(selector);
        }
        closest(selector) {
            for (let node = this; node; node = node.parentElement) {
                if (selector === '[hidden]' && node.hidden) return node;
                if (selector === '.settings' && node.classes.has('settings')) return node;
            }
            return null;
        }
    }
    const settings = new Element(); settings.classes.add('settings');
    const pane = settings.appendChild(new Element()); pane.hidden = true;
    const grid = pane.appendChild(new Element()); grid.id = 'serviceHealthGrid';
    const document = {
        hidden: false, readyState: 'complete', documentElement: { lang: 'en' },
        head: new Element(),
        createElement: () => new Element(),
        getElementById: id => ids.get(id) || null,
        addEventListener: (name, callback) => events.set(name, callback),
        removeEventListener: name => events.delete(name)
    };
    const windowEvents = new Map();
    const window = { addEventListener: (name, callback) => windowEvents.set(name, callback) };
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), {
        window, document, navigator: { language: 'en' }, console,
        setInterval: callback => { intervals.push(callback); return intervals.length; },
        clearInterval() {}, setTimeout() {},
        MutationObserver: class {
            constructor(callback) { this.callback = callback; observers.push(this); }
            observe() {}
            disconnect() { this.disconnected = true; }
        },
        fetch: async url => {
            if (url.startsWith('/i18n/')) return { ok: true, json: async () => ({}) };
            requests.push(url);
            if (blocked) await blocked;
            return { ok: true, json: async () => ({}) };
        }
    });
    return {
        requests, settings, pane, document, observers,
        tick() { for (const callback of intervals) callback(); },
        notify() { for (const observer of observers) observer.callback(); },
        visible() { events.get('visibilitychange')(); },
        unload() { windowEvents.get('beforeunload')(); },
        block() { blocked = new Promise(resolve => { this.release = () => { blocked = null; resolve(); }; }); }
    };
}

for (const module of ['performance-observatory', 'system-health']) {
    test(`${module}: closed settings and hidden tabs do not fetch`, async () => {
        const env = environment(`frontend/assets/chat/${module}.js`);
        await settle();
        for (let i = 0; i < 5; i++) { env.tick(); await settle(); }
        assert.equal(env.requests.length, 0);
        env.settings.classes.add('open');
        env.notify(); await settle();
        assert.equal(env.requests.length, 0, 'other settings tabs remain idle');
        env.pane.hidden = false;
        env.notify(); await settle();
        assert.equal(env.requests.length, 1, 'showing the panel immediately refreshes');
        env.tick(); await settle();
        assert.equal(env.requests.length, 2, 'visible panels retain periodic updates');
        env.document.hidden = true;
        env.tick(); await settle();
        assert.equal(env.requests.length, 2);
        env.document.hidden = false;
        env.visible(); await settle();
        assert.equal(env.requests.length, 3, 'returning to the browser refreshes');
        env.settings.classes.delete('open');
        env.notify(); env.tick(); await settle();
        assert.equal(env.requests.length, 3);
        env.unload();
        assert.ok(env.observers.every(observer => observer.disconnected));
    });
    test(`${module}: visibility bursts do not overlap a slow request`, async () => {
        const env = environment(`frontend/assets/chat/${module}.js`);
        await settle();
        env.settings.classes.add('open'); env.pane.hidden = false; env.block();
        env.notify(); env.notify(); env.tick(); env.visible();
        await settle();
        assert.equal(env.requests.length, 1);
        env.release(); await settle();
        env.tick(); await settle();
        assert.equal(env.requests.length, 2);
    });
}
