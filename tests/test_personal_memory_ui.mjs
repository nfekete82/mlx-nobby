import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const personalSource = fs.readFileSync(new URL('../frontend/assets/chat/personal-memory.js', import.meta.url), 'utf8');
const archiveSource = fs.readFileSync(new URL('../frontend/assets/chat/memory-archive.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function controller(source, fetch) {
    const elements = new Map();
    class Element {
        constructor() { this.value = ''; this.style = {}; this.listeners = new Map(); this.children = []; }
        set id(value) { this._id = value; elements.set(value, this); }
        get id() { return this._id; }
        set textContent(value) { this.text = String(value); this.children = []; }
        get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
        get childElementCount() { return this.children.length; }
        append(...children) { this.children.push(...children); }
        replaceChildren(...children) { this.text = ''; this.children = [...children]; }
        setAttribute() {}
        insertAdjacentHTML(_position, html) {
            for (const match of html.matchAll(/id="([^"]+)"/g)) new Element().id = match[1];
        }
        addEventListener(name, fn) {
            assert.equal(typeof fn, 'function', `Invalid ${name} listener on ${this.id}`);
            this.listeners.set(name, fn);
        }
    }
    for (const id of ['memoryManagerPane', 'memoryManagerTab']) new Element().id = id;
    vm.runInNewContext(source, {
        window: {}, console, fetch, location: { pathname: '/chat' },
        document: {
            getElementById: id => elements.get(id),
            createElement: () => new Element(), documentElement: {}, addEventListener() {},
        },
        MutationObserver: class { observe() {} disconnect() {} },
    });
    return elements;
}

const response = data => ({ ok: true, json: async () => data });

test('personal memory mounts and its opt-in checkbox invokes the config API', async () => {
    const requests = [];
    const elements = controller(personalSource, async (path, options = {}) => {
        requests.push({ path, ...options });
        if (path.endsWith('/status')) return response({ enabled: true });
        if (path.includes('/facts?')) return response({ facts: [] });
        if (path.endsWith('/conflicts')) return response({ conflicts: [] });
        return response({});
    });
    assert.ok(elements.has('privateMemoryPanel'));
    const checkbox = elements.get('privateMemoryEnabled');
    checkbox.checked = true;
    await checkbox.listeners.get('change')();
    assert.ok(requests.some(r => r.path.endsWith('/personal/config') &&
        r.method === 'POST' && JSON.parse(r.body).enabled === true));
    assert.equal(checkbox.disabled, false);
});

test('a late personal-memory refresh cannot redisplay private facts after opt-out', async () => {
    let enabled = true, releaseFacts, factsStarted = false;
    const gate = new Promise(resolve => { releaseFacts = resolve; });
    const elements = controller(personalSource, async path => {
        if (path.endsWith('/status')) return response({ enabled });
        if (path.endsWith('/config')) { enabled = false; return response({ enabled }); }
        if (path.includes('/facts?')) { factsStarted = true; return { ok: true, json: () => gate }; }
        if (path.endsWith('/conflicts')) return response({ conflicts: [] });
        return response({});
    });
    elements.get('memoryManagerTab').listeners.get('click')();
    await tick();
    assert.equal(factsStarted, true);
    const checkbox = elements.get('privateMemoryEnabled');
    checkbox.checked = false;
    await checkbox.listeners.get('change')();
    releaseFacts({ facts: [{ id: 'synthetic', subject: 'example', field: 'note',
        value: 'SYNTHETIC_PRIVATE_LATE_FACT', status: 'active', updated_at: 1 }] });
    await tick();
    assert.ok(!elements.get('privateMemoryFacts').textContent.includes('SYNTHETIC_PRIVATE_LATE_FACT'));
    assert.equal(checkbox.checked, false);
});

test('a late archive search cannot redisplay excerpts after opt-out', async () => {
    let releaseSearch;
    const gate = new Promise(resolve => { releaseSearch = resolve; });
    const elements = controller(archiveSource, async path => {
        if (path.includes('/search?')) return { ok: true, json: () => gate };
        if (path.endsWith('/config')) return response({ enabled: false, indexed_messages: 0 });
        return response({});
    });
    elements.get('localArchiveEnabled').checked = true;
    elements.get('localArchiveQuery').value = 'synthetic';
    const searching = elements.get('localArchiveSearch').listeners.get('click')();
    await tick();
    const checkbox = elements.get('localArchiveEnabled');
    checkbox.checked = false;
    await checkbox.listeners.get('change')();
    releaseSearch({ results: [{ chat_id: 'synthetic', message_index: 0, role: 'user',
        excerpt: 'SYNTHETIC_PRIVATE_LATE_EXCERPT' }] });
    await searching;
    assert.ok(!elements.get('localArchiveResults').textContent.includes('SYNTHETIC_PRIVATE_LATE_EXCERPT'));
});

test('successful opt-out clears displayed facts even if the next status request fails', async () => {
    let enabled = true;
    const elements = controller(personalSource, async path => {
        if (path.endsWith('/config')) { enabled = false; return response({ enabled }); }
        if (path.endsWith('/status')) {
            if (!enabled) throw new Error('Synthetic status outage');
            return response({ enabled });
        }
        if (path.includes('/facts?')) return response({ facts: [{ id: 'synthetic',
            subject: 'example', field: 'note', value: 'SYNTHETIC_EXISTING_PRIVATE_FACT',
            status: 'active', updated_at: 1 }] });
        if (path.endsWith('/conflicts')) return response({ conflicts: [] });
        return response({});
    });
    elements.get('memoryManagerTab').listeners.get('click')();
    await tick();
    assert.ok(elements.get('privateMemoryFacts').textContent.includes('SYNTHETIC_EXISTING_PRIVATE_FACT'));
    const checkbox = elements.get('privateMemoryEnabled');
    checkbox.checked = false;
    await checkbox.listeners.get('change')();
    assert.equal(checkbox.checked, false);
    assert.ok(!elements.get('privateMemoryFacts').textContent.includes('SYNTHETIC_EXISTING_PRIVATE_FACT'));
});
