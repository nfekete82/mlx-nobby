import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function setup(history) {
    const storage = new Map();
    const requests = [];
    let nextId = 0;
    const window = { location: { href: 'http://localhost/chat' }, localStorage: {
        getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
    } };
    const sandbox = {
        window, console, URL, crypto: { randomUUID: () => 'draft-' + (++nextId) },
        localStorage: window.localStorage,
        document: { readyState: 'loading', getElementById: () => null, createElement: () => ({}),
            head: { appendChild() {} }, addEventListener() {} },
        fetch: async (url, options = {}) => {
            requests.push({ url, method: options.method || 'GET' });
            return { ok: true, json: async () => options.method === 'PUT'
                ? { chat: JSON.parse(options.body) } : { chats: structuredClone(history) } };
        },
    };
    vm.runInNewContext(fs.readFileSync(new URL('../frontend/assets/common.js', import.meta.url), 'utf8'), sandbox);
    sandbox.MLXCommon = window.MLXCommon;
    vm.runInNewContext(fs.readFileSync(new URL('../frontend/assets/chat/sessions.js', import.meta.url), 'utf8'), sandbox);
    const state = { sessions: [], activeId: null };
    const api = window.MLXChatSessions;
    api.configure({ state, renderAll() {}, renderSidebar() {}, isGenerating: () => false,
        createSessionSettings: () => ({}), onSessionSelected() {} });
    return { api, state, requests };
}

test('empty startup and New chat clicks remain local drafts in the current product', async () => {
    const h = setup([]);
    await h.api.syncWithServer();
    assert.equal(h.state.sessions.length, 1);
    assert.equal(h.state.sessions[0].messages.length, 0);
    h.api.createSession();
    h.api.createSession();
    await Promise.resolve();
    assert.deepEqual(h.requests, [{ url: '/api/mlx/chats', method: 'GET' }]);
    h.api.currentSession().messages.push({ role: 'user', content: 'first user turn' });
    h.api.saveSessions();
    await Promise.resolve();
    assert.equal(h.requests.filter(request => request.method === 'PUT').length, 1);
});

test('opening and syncing existing history does not create a new empty session', async () => {
    const history = [{ id: 'user-owned', title: 'Normal', created: 1, updated: 2,
        messages: [{ role: 'user', content: 'fixture' }] }];
    const h = setup(history);
    await h.api.syncWithServer();
    await h.api.syncWithServer();
    assert.deepEqual(Array.from(h.state.sessions, chat => chat.id), ['user-owned']);
    assert.ok(h.requests.every(request => request.method === 'GET'));
});
