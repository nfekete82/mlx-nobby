import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync(new URL('../frontend/assets/chat/personal-memory.js', import.meta.url), 'utf8');

test('personal memory mounts and its opt-in checkbox invokes the config API', async () => {
    const elements = new Map();
    const requests = [];
    class Element {
        constructor() { this.value = ''; this.style = {}; this.listeners = new Map(); }
        set id(value) { this._id = value; elements.set(value, this); }
        get id() { return this._id; }
        append() {}
        replaceChildren() {}
        setAttribute() {}
        addEventListener(name, fn) {
            assert.equal(typeof fn, 'function', `Invalid ${name} listener on ${this.id}`);
            this.listeners.set(name, fn);
        }
    }
    new Element().id = 'memoryManagerPane';
    const fetch = async (path, options = {}) => {
        requests.push({ path, ...options });
        let data = {};
        if (path.endsWith('/status')) data = { enabled: true };
        if (path.includes('/facts?')) data = { facts: [] };
        if (path.endsWith('/conflicts')) data = { conflicts: [] };
        return { ok: true, json: async () => data };
    };
    vm.runInNewContext(source, {
        window: {}, console, fetch, location: { pathname: '/chat' },
        document: {
            getElementById: id => elements.get(id),
            createElement: () => new Element(), documentElement: {}, addEventListener() {},
        },
        MutationObserver: class { observe() {} disconnect() {} },
    });
    assert.ok(elements.has('privateMemoryPanel'));
    const checkbox = elements.get('privateMemoryEnabled');
    checkbox.checked = true;
    await checkbox.listeners.get('change')();
    assert.ok(requests.some(r => r.path.endsWith('/personal/config') &&
        r.method === 'POST' && JSON.parse(r.body).enabled === true));
    assert.equal(checkbox.disabled, false);
});
