import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import { webcrypto } from 'node:crypto';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/sessions.js', import.meta.url), 'utf8'
);

const clone = value => JSON.parse(JSON.stringify(value));
const copyFor = chats => [...chats].find(chat => chat.id.startsWith('conflict-'));
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
            assert.match(url, /^\/api\/mlx\/chats\/(?:chat-[ab]|conflict-[a-f0-9]{64}|[a-f0-9-]{36})$/);
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
        window, console, crypto: webcrypto,
        TextEncoder,
        localStorage: {
            get length() { return cache.size; },
            key(index) { return [...cache.keys()][index] ?? null; },
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

    // A deliberate stale edit of A must survive as a durable conflict copy.
    const stale = second.state.sessions.find(s => s.id === 'chat-a');
    stale.updated = 40;
    stale.messages.push({ role: 'assistant', content: 'Stale data' });
    await second.sessions.persistSession(stale);
    assert.equal(server.writes.findLast(w => w.id === 'chat-a').expected_updated, 10);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Tab A wrote this');
    assert.equal(stale.messages.at(-1).content, 'Tab A wrote this');
    assert.equal(copyFor(server.chats.values())?.messages.at(-1).content, 'Stale data');
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
    const copy = copyFor(first.state.sessions);
    assert.ok(copy, 'a conflict copy must remain visible in the session list');
    assert.match(copy.title, /conflict copy/i);
    await first.sessions.persistSession(copy);
    assert.equal(copyFor(server.chats.values()).messages.at(-1).content, 'My final unsent edit');
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

    const rescued = copyFor(reloaded.state.sessions);
    assert.ok(rescued, 'local edits must survive reload in a distinct chat');
    assert.equal(rescued.messages.at(-1).content, 'Final generated draft');
    await reloaded.sessions.persistSession(rescued);

    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Other tab wins');
    assert.equal(copyFor(server.chats.values()).messages.at(-1).content, 'Final generated draft');
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
    const recovered = copyFor(client.state.sessions);
    assert.ok(original);
    assert.ok(recovered, 'offline changes must be retained as a separate copy');
    assert.equal(original.messages[0].content, 'Original A');
    assert.equal(recovered.messages[0].content, 'Offline version from earlier tab');
    await client.sessions.persistSession(recovered);

    assert.equal(server.chats.get('chat-a').messages[0].content, 'Original A');
    assert.equal(copyFor(server.chats.values()).messages[0].content,
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

    assert.deepEqual(Array.from(client.state.sessions, s => s.id).sort(), ['chat-a', 'chat-b']);
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

for (const updated of [5, 10]) {
    test(`offline cache with timestamp ${updated} retains divergent content on reload`, async () => {
        const server = store();
        const cache = new Map([['mlx-web-chats-v1', JSON.stringify([
            record('chat-a', updated, 'Unsaved offline draft'),
        ])]]);
        const client = tab(server, cache);
        client.sessions.loadSessions();
        await client.sessions.syncWithServer();
        assert.equal(server.chats.get('chat-a').messages[0].content, 'Original A');
        assert.equal(copyFor(server.chats.values()).messages[0].content, 'Unsaved offline draft');
    });
}

test('identical concurrent content never creates a conflict copy or repeated PUTs', async () => {
    const server = store();
    const first = tab(server), second = tab(server);
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();
    for (const client of [first, second]) {
        const local = client.state.sessions.find(s => s.id === 'chat-a');
        local.updated = 20;
        local.messages.push({ role: 'assistant', content: 'Identical final content' });
        await client.sessions.persistSession(local);
    }
    second.sessions.saveSessions();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(server.chats.size, 2);
    assert.equal(server.writes.length, 2);
    assert.ok(second.state.sessions.every(s => !/conflict copy/i.test(s.title)));
});

test('server timestamp advancement still drains mutations made during the PUT', async () => {
    const server = store();
    const client = tab(server);
    await client.sessions.syncWithServer();
    const local = client.state.sessions.find(s => s.id === 'chat-a');
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    server.setBeforePut(async (incoming, n) => {
        if (n === 1) { await gate; incoming.updated = 21; }
    });
    local.updated = 20;
    local.messages.push({ role: 'assistant', content: 'Partial' });
    const writing = client.sessions.persistSession(local);
    local.title = 'Renamed during PUT';
    local.messages.at(-1).content = 'Final';
    release();
    await writing;
    assert.deepEqual(server.writes.map(w => w.expected_updated), [10, 21]);
    assert.equal(server.chats.get('chat-a').title, 'Renamed during PUT');
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Final');
});

test('GET started before a PUT cannot restore stale data or CAS tokens', async () => {
    const server = store();
    const client = tab(server);
    await client.sessions.syncWithServer();
    const fetch = server.fetch.bind(server);
    let release;
    server.fetch = async (url, body) => {
        const result = await fetch(url, body);
        if (url === '/api/mlx/chats') await new Promise(resolve => { release = resolve; });
        return result;
    };
    const syncing = client.sessions.syncWithServer();
    await new Promise(resolve => setImmediate(resolve));
    const local = client.state.sessions.find(s => s.id === 'chat-a');
    local.updated = 20;
    local.messages.push({ role: 'assistant', content: 'Saved after GET started' });
    await client.sessions.persistSession(local);
    release();
    await syncing;
    local.updated = 30;
    local.messages.at(-1).content = 'Second save';
    await client.sessions.persistSession(local);
    assert.deepEqual(server.writes.map(w => w.expected_updated), [10, 20]);
    assert.equal(server.chats.size, 2);
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Second save');
});

test('failed conflict-copy upload survives reload and retries under the same new ID', async () => {
    const server = store();
    const first = tab(server), second = tab(server);
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();
    const remote = first.state.sessions.find(s => s.id === 'chat-a');
    remote.updated = 20;
    remote.messages.push({ role: 'assistant', content: 'Server winner' });
    await first.sessions.persistSession(remote);
    const fetch = server.fetch.bind(server);
    server.fetch = async (url, body) => {
        if (url.includes('/conflict-')) throw new Error('Offline');
        return fetch(url, body);
    };
    const local = second.state.sessions.find(s => s.id === 'chat-a');
    local.updated = 30;
    local.messages.push({ role: 'assistant', content: 'Offline conflict copy' });
    await second.sessions.persistSession(local);
    const copyId = copyFor(second.state.sessions).id;
    assert.ok(copyId);
    server.fetch = fetch;
    const reloaded = tab(server, second.cache);
    reloaded.sessions.loadSessions();
    await reloaded.sessions.syncWithServer();
    assert.equal(server.chats.size, 3);
    assert.equal(server.chats.get(copyId).messages.at(-1).content, 'Offline conflict copy');
    await reloaded.sessions.syncWithServer();
    assert.equal(server.chats.size, 3);
});

test('generation finishing before the conflicting response still saves its final draft', async () => {
    const server = store();
    const first = tab(server), second = tab(server, new Map(), { generating: true });
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();
    const winner = first.state.sessions.find(s => s.id === 'chat-a');
    winner.updated = 20;
    winner.messages.push({ role: 'assistant', content: 'Winner' });
    await first.sessions.persistSession(winner);
    let release;
    server.setBeforePut(() => new Promise(resolve => { release = resolve; }));
    const local = second.state.sessions.find(s => s.id === 'chat-a');
    local.updated = 30;
    local.messages.push({ role: 'assistant', content: 'Final generated text' });
    const writing = second.sessions.persistSession(local);
    second.setGenerating(false);
    second.sessions.saveSessions();
    server.setBeforePut(null);
    release();
    await writing;
    assert.equal(copyFor(server.chats.values()).messages.at(-1).content, 'Final generated text');
});

test('another tab replacing the shared cache cannot erase a generating conflict draft', async () => {
    const server = store(), cache = new Map();
    const first = tab(server, cache), second = tab(server, cache, { generating: true });
    await first.sessions.syncWithServer();
    await second.sessions.syncWithServer();
    const winner = first.state.sessions.find(s => s.id === 'chat-a');
    winner.updated = 20;
    winner.messages.push({ role: 'assistant', content: 'Server winner' });
    await first.sessions.persistSession(winner);
    const draft = second.state.sessions.find(s => s.id === 'chat-a');
    draft.updated = 30;
    draft.messages.push({ role: 'assistant', content: 'Streaming draft' });
    await second.sessions.persistSession(draft);
    draft.messages.at(-1).content = 'Final draft before reload';
    second.sessions.saveSessions();
    // This replaces the single legacy cache with another tab's session list.
    first.sessions.saveSessions();
    await new Promise(resolve => setImmediate(resolve));
    const reloaded = tab(server, cache);
    reloaded.sessions.loadSessions();
    await reloaded.sessions.syncWithServer();
    assert.equal(server.chats.get('chat-a').messages.at(-1).content, 'Server winner');
    assert.equal(copyFor(server.chats.values()).messages.at(-1).content, 'Final draft before reload');
    assert.ok([...cache.keys()].every(key => !key.startsWith('mlx-web-chats-pending-conflicts-v1:')));
});

test('two identical losing tabs converge on one new conflict ID', async () => {
    const server = store();
    const winner = tab(server), first = tab(server), second = tab(server);
    for (const client of [winner, first, second]) await client.sessions.syncWithServer();
    const remote = winner.state.sessions.find(s => s.id === 'chat-a');
    remote.updated = 20;
    remote.messages.push({ role: 'assistant', content: 'Server winner' });
    await winner.sessions.persistSession(remote);
    const writes = [];
    for (const [index, client] of [first, second].entries()) {
        const local = client.state.sessions.find(s => s.id === 'chat-a');
        local.updated = 30 + index;
        // Property ordering must not change content equality or the fork ID.
        local.messages.push(index === 0 ? { role: 'assistant', content: 'Same rejected draft' }
            : { content: 'Same rejected draft', role: 'assistant' });
        writes.push(client.sessions.persistSession(local));
    }
    await Promise.all(writes);
    assert.equal(server.chats.size, 3);
    assert.equal(copyFor(first.state.sessions).id, copyFor(second.state.sessions).id);
    assert.equal(copyFor(server.chats.values()).messages.at(-1).content, 'Same rejected draft');
});

test('different losing tabs retain both distinct copies', async () => {
    const server = store();
    const winner = tab(server), first = tab(server), second = tab(server);
    for (const client of [winner, first, second]) await client.sessions.syncWithServer();
    const remote = winner.state.sessions.find(s => s.id === 'chat-a');
    remote.updated = 20;
    remote.messages.push({ role: 'assistant', content: 'Winner' });
    await winner.sessions.persistSession(remote);
    await Promise.all([first, second].map(async (client, index) => {
        const local = client.state.sessions.find(s => s.id === 'chat-a');
        local.updated = 30;
        local.messages.push({ role: 'assistant', content: 'Draft ' + index });
        await client.sessions.persistSession(local);
    }));
    assert.equal(server.chats.size, 4);
    assert.notEqual(copyFor(first.state.sessions).id, copyFor(second.state.sessions).id);
    assert.deepEqual([...server.chats.values()].filter(s => s.id.startsWith('conflict-'))
        .map(s => s.messages.at(-1).content).sort(), ['Draft 0', 'Draft 1']);
});

test('two generating tabs with the same initial draft retain divergent final journals', async () => {
    const server = store(), cache = new Map();
    const winner = tab(server, cache);
    const clients = [tab(server, cache, { generating: true }), tab(server, cache, { generating: true })];
    for (const client of [winner, ...clients]) await client.sessions.syncWithServer();
    const remote = winner.state.sessions.find(s => s.id === 'chat-a');
    remote.updated = 20;
    remote.messages.push({ role: 'assistant', content: 'Winner' });
    await winner.sessions.persistSession(remote);
    for (const client of clients) {
        const draft = client.state.sessions.find(s => s.id === 'chat-a');
        draft.updated = 30;
        draft.messages.push({ role: 'assistant', content: 'Same partial generation' });
        await client.sessions.persistSession(draft);
    }
    clients.forEach((client, index) => {
        client.state.sessions.find(s => s.id === 'chat-a').messages.at(-1).content = 'Final ' + index;
        client.sessions.saveSessions();
    });
    const reloaded = tab(server, cache);
    reloaded.sessions.loadSessions();
    await reloaded.sessions.syncWithServer();
    assert.equal(server.chats.size, 4);
    const contents = [...server.chats.values()].map(s => s.messages.at(-1).content);
    assert.ok(contents.includes('Final 0'));
    assert.ok(contents.includes('Final 1'));
    assert.equal([...cache.keys()].filter(key => key.startsWith('mlx-web-chats-pending-conflicts-v1:')).length, 0);
});

test('a malformed journal entry cannot hide later valid recovery records', async () => {
    const server = store();
    const source = record('chat-a', 30, 'Recovered draft');
    const copy = { ...clone(source), id: 'conflict-' + 'ab'.repeat(32), title: 'Chat (Conflict copy)' };
    const cache = new Map([
        ['mlx-web-chats-v1', JSON.stringify([source])],
        ['mlx-web-chats-pending-conflicts-v1:broken', '{'],
        ['mlx-web-chats-pending-conflicts-v1:valid', JSON.stringify({ source, copy })],
    ]);
    const client = tab(server, cache);
    client.sessions.loadSessions();
    await client.sessions.syncWithServer();
    assert.equal(server.chats.get(copy.id).messages[0].content, 'Recovered draft');
    assert.equal(server.chats.get('chat-a').messages[0].content, 'Original A');
});

test('a server tombstone discards a source chat and its recovery journal', async () => {
    const server = store();
    const source = record('chat-a', 30, 'Deleted draft');
    const copy = { ...clone(source), id: 'conflict-' + 'ab'.repeat(32), title: 'Conflict copy' };
    const key = 'mlx-web-chats-pending-conflicts-v1:deleted';
    const cache = new Map([[key, JSON.stringify({ sourceId: source.id, source, copy })]]);
    const fetch = server.fetch.bind(server);
    server.fetch = (url, body) => url === '/api/mlx/chats'
        ? Promise.resolve({ response: { ok: true }, data: {
            chats: [clone(server.chats.get('chat-b'))], deleted_ids: ['chat-a'],
        } }) : fetch(url, body);
    const client = tab(server, cache);
    client.sessions.loadSessions();
    await client.sessions.syncWithServer();
    assert.deepEqual(Array.from(client.state.sessions, s => s.id), ['chat-b']);
    assert.equal(cache.has(key), false);
    assert.equal(server.writes.length, 0);
});
