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
            assert.match(url, /^\/api\/mlx\/chats\/(?:chat-[ab]|new-chat-id)$/);
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

function tab(server, cache = new Map(), options = {}) {
    const state = { sessions: [], activeId: null };
    let generating = options.generating === true;
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
        renderAll() {}, renderSidebar() {}, isGenerating() { return generating; },
        createSessionSettings() { return {}; }, onSessionSelected() {},
    });
    return { sessions, state, cache, setGenerating(value) { generating = value; } };
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


test('a write conflict with an in-flight local edit forks a safe copy, never overwrites the other tab', async () => {
    const server = store();
    const first = tab(server), second = tab(server);
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();

    let releaseFirst;
    const gate = new Promise(resolve => { releaseFirst = resolve; });
    server.setBeforePut((_body, n) => n === 1 ? gate : Promise.resolve());

    const local = first.state.sessions.find(chat => chat.id === 'chat-a');
    local.updated = 20;
    local.messages.push({ role: 'assistant', content: 'Interim local edit' });
    const firstWrite = first.sessions.persistSession(local);

    const remote = second.state.sessions.find(chat => chat.id === 'chat-a');
    remote.updated = 30;
    remote.messages.push({ role: 'assistant', content: 'Saved in another tab' });
    await second.sessions.persistSession(remote);

    // Edit the original session while its old request is still pending.
    local.updated = 40;
    local.messages.at(-1).content = 'My final unsent edit';
    releaseFirst();
    await firstWrite;

    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Saved in another tab');

    first.sessions.saveSessions();
    const copy = first.state.sessions.find(chat => chat.id === 'new-chat-id');
    assert.ok(copy, 'a conflict copy must remain visible in the session list');
    assert.match(copy.title, /conflict copy/i);
    await first.sessions.persistSession(copy);
    assert.equal(server.chats.get('new-chat-id').messages.at(-1).content, 'My final unsent edit');
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Saved in another tab');
    assert.equal(first.state.sessions.find(chat => chat.id === 'chat-a')
        .messages.at(-1).content, 'Saved in another tab');
});

test('active-generation conflict survives reload as a separate chat without stale overwrite', async () => {
    const server = store();
    const first = tab(server, new Map(), { generating: true });
    const second = tab(server);
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();

    let releaseFirst;
    const gate = new Promise(resolve => { releaseFirst = resolve; });
    server.setBeforePut((_body, n) => n === 1 ? gate : Promise.resolve());

    const local = first.state.sessions.find(chat => chat.id === 'chat-a');
    local.updated = 20;
    local.messages.push({ role: 'assistant', content: 'Started generation' });
    const firstWrite = first.sessions.persistSession(local);

    const remote = second.state.sessions.find(chat => chat.id === 'chat-a');
    remote.updated = 30;
    remote.messages.push({ role: 'assistant', content: 'Other tab wins' });
    await second.sessions.persistSession(remote);

    local.updated = 40;
    local.messages.at(-1).content = 'Final generated draft';
    releaseFirst();
    await firstWrite;
    first.sessions.saveSessions();
    assert.equal(first.state.sessions.find(chat => chat.id === 'chat-a')
        .messages.at(-1).content, 'Final generated draft');

    const reloaded = tab(server, first.cache);
    reloaded.sessions.loadSessions();
    await reloaded.sessions.syncWithServer();

    const rescued = reloaded.state.sessions.find(chat => chat.id === 'new-chat-id');
    assert.ok(rescued, 'local edits must survive reload in a distinct chat');
    assert.equal(rescued.messages.at(-1).content, 'Final generated draft');
    await reloaded.sessions.persistSession(rescued);

    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Other tab wins');
    assert.equal(server.chats.get('new-chat-id').messages.at(-1).content, 'Final generated draft');
});


test('offline cache with a future timestamp cannot overwrite another tab on reload', async () => {
    const server = store();
    const offline = record('chat-a', 99, 'Offline version from earlier tab');
    const cache = new Map([
        ['mlx-web-chats-v1', JSON.stringify([offline])],
    ]);
    const client = tab(server, cache);
    client.sessions.loadSessions();
    await client.sessions.syncWithServer();

    const original = client.state.sessions.find(chat => chat.id === 'chat-a');
    const recovered = client.state.sessions.find(chat => chat.id === 'new-chat-id');
    assert.ok(original);
    assert.ok(recovered, 'offline changes must be retained as a separate copy');
    assert.equal(original.messages[0].content, 'Original A');
    assert.equal(recovered.messages[0].content, 'Offline version from earlier tab');
    await client.sessions.persistSession(recovered);

    assert.equal(server.chats.get('chat-a').messages[0].content, 'Original A');
    assert.equal(server.chats.get('new-chat-id').messages[0].content,
        'Offline version from earlier tab');
});


test('browser startup settings defaults do not fork an otherwise unchanged chat', async () => {
    const server = store();
    const cached = record('chat-a', 999, 'Original A');
    cached.settings = {
        system_prompt: '', preset_id: 'general',
        adaptive_response_auto: true, adaptive_response_length: false,
        media_quality: 'standard', negative_prompt: '',
    };
    const cache = new Map([
        ['mlx-web-chats-v1', JSON.stringify([cached])],
    ]);
    const client = tab(server, cache);
    client.sessions.loadSessions();
    await client.sessions.syncWithServer();

    assert.deepEqual(client.state.sessions.map(s => s.id).sort(), ['chat-a', 'chat-b']);
    assert.deepEqual(server.writes.map(x => x.id), []);
    assert.equal(server.chats.get('chat-a').messages[0].content, 'Original A');

    // Later user edits still use the current server CAS token, rather than
    // treating an initial settings migration as an external rewrite.
    const session = client.state.sessions.find(s => s.id === 'chat-a');
    session.updated = 1000;
    session.messages.push({ role: 'assistant', content: 'New user-owned edit' });
    await client.sessions.persistSession(session);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'New user-owned edit');
});
