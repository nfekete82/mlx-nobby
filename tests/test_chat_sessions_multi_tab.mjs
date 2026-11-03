import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/sessions.js', import.meta.url), 'utf8'
);

const clone = value => JSON.parse(JSON.stringify(value));
const record = (id, updated, message) => ({
    id, title: id, created: 1, updated, revision: 0,
    messages: [{ role: 'user', content: message }],
    settings: { system_prompt: '', preset_id: 'general' },
});

function store() {
    const chats = new Map([
        ['chat-a', record('chat-a', 10, 'Original A')],
        ['chat-b', record('chat-b', 10, 'Original B')],
    ]);
    const writes = [];
    let beforePut = null;
    let active = 0, maxActive = 0;
    return {
        chats, writes,
        get maxActive() { return maxActive; },
        setBeforePut(fn) { beforePut = fn; },
        async fetch(url, body) {
            if (url === '/api/mlx/chats') {
                return { response: { ok: true },
                    data: { chats: clone([...chats.values()]), deleted_ids: [] } };
            }
            assert.match(url, /^\/api\/mlx\/chats\/chat-[ab]$/);
            assert.ok(body);
            const id = url.split('/').at(-1);
            const { expected_updated, ...incoming } = clone(body);
            writes.push({ id, updated: incoming.updated, expected_updated });
            active++;
            maxActive = Math.max(active, maxActive);
            try {
                if (beforePut) await beforePut(incoming, writes.length);
                const existing = chats.get(id);
                if ((existing && existing.updated !== expected_updated) ||
                    (!existing && expected_updated !== -1)) {
                    return { response: { ok: true },
                        data: { chat: clone(existing), conflict: true } };
                }
                chats.set(id, incoming);
                return { response: { ok: true },
                    data: { chat: clone(incoming), conflict: false } };
            } finally {
                active--;
            }
        },
    };
}

function tab(server) {
    const state = { sessions: [], activeId: null };
    const cache = new Map();
    const window = {};
    vm.runInNewContext(source, {
        window, console, crypto: { randomUUID: () => 'new-chat-id' },
        localStorage: {
            getItem(key) { return cache.get(key) ?? null; },
            setItem(key, value) { cache.set(key, value); },
            removeItem(key) { cache.delete(key); },
        },
        MLXCommon: {
            jsonRequest(_method, value) { return value; },
            fetchJson(path, body) { return server.fetch(path, body); },
        },
    }, { filename: 'frontend/assets/chat/sessions.js' });
    const sessions = window.MLXChatSessions;
    sessions.configure({
        state,
        renderAll() {}, renderSidebar() {}, isGenerating() { return false; },
        createSessionSettings() { return {}; }, onSessionSelected() {},
    });
    return { sessions, state, cache };
}

test('saving one chat never resubmits unrelated unchanged chats from other tabs', async () => {
    const server = store();
    const first = tab(server), second = tab(server);
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();

    const a = first.state.sessions.find(s => s.id === 'chat-a');
    a.updated = 20;
    a.messages.push({ role: 'assistant', content: 'Tab A wrote this' });
    first.sessions.saveSessions();
    await first.sessions.persistSession(a);
    assert.deepEqual(server.writes.map(w => w.id), ['chat-a']);

    // Tab B still has an older cache for A. Updating B must not PUT A.
    const b = second.state.sessions.find(s => s.id === 'chat-b');
    b.updated = 30;
    b.messages.push({ role: 'assistant', content: 'Tab B wrote this' });
    second.sessions.saveSessions();
    await second.sessions.persistSession(b);
    assert.deepEqual(server.writes.map(w => w.id), ['chat-a', 'chat-b']);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Tab A wrote this');
    assert.equal(server.chats.get('chat-b').messages.at(-1).content, 'Tab B wrote this');

    // A deliberate stale edit of A is rejected and reconciles to its server copy.
    const stale = second.state.sessions.find(s => s.id === 'chat-a');
    stale.updated = 40;
    stale.messages.push({ role: 'assistant', content: 'Stale data' });
    await second.sessions.persistSession(stale);
    assert.equal(server.writes.at(-1).expected_updated, 10);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Tab A wrote this');
    assert.equal(stale.messages.at(-1).content, 'Tab A wrote this');
});

test('two rapid writes for one chat are serialized and persist the latest message', async () => {
    const server = store();
    const client = tab(server);
    await client.sessions.syncWithServer();
    const a = client.state.sessions.find(s => s.id === 'chat-a');

    let releaseFirst;
    const gate = new Promise(resolve => { releaseFirst = resolve; });
    server.setBeforePut((_body, n) => n === 1 ? gate : Promise.resolve());

    a.updated = 20;
    a.messages.push({ role: 'assistant', content: 'Interim' });
    const firstWrite = client.sessions.persistSession(a);

    a.updated = 30;
    a.messages.at(-1).content = 'Final';
    client.sessions.saveSessions();

    releaseFirst();
    await firstWrite;
    assert.deepEqual(server.writes.map(w => w.updated), [20, 30]);
    assert.deepEqual(server.writes.map(w => w.expected_updated), [10, 20]);
    assert.equal(server.maxActive, 1);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Final');
});
