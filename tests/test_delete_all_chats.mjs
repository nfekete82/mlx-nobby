import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync(new URL('../frontend/assets/chat/sessions.js', import.meta.url), 'utf8');
const oldChat = id => ({ id, title: id, created: 1, updated: 2, messages: [{ role: 'user', content: 'hello' }] });
function fixture() {
    const state = { sessions: [oldChat('one'), oldChat('two')], activeId: 'one' };
    const cache = new Map([['mlx-web-chats-v1', JSON.stringify(state.sessions)], ['settings', 'keep']]);
    const requests = [], resets = [], dialogs = [];
    let confirm = true, attachments = 0, detach = 0;
    let responder = async (url, options) => ({ response: { ok: true }, data:
        options?.method === 'DELETE' ? { ok: true } : options?.method === 'PUT' ? { chat: options.body } : { chats: state.sessions } });
    const window = {
        MLXConfirm: async options => { dialogs.push(options); return confirm; },
        MLXChatGeneration: { resetSessionRuntime: async session => { resets.push(session); } },
        MLXChatAttachments: { clearAttachments: () => attachments++ },
        MLXChatWorkspace: { deactivate: async () => detach++ },
    };
    vm.runInNewContext(source, {
        window, console: { warn() {} }, crypto: { randomUUID: () => 'new-empty' },
        localStorage: { getItem: key => cache.get(key), setItem: (key, value) => cache.set(key, value), removeItem: key => cache.delete(key) },
        MLXCommon: { jsonRequest: (method, body) => ({ method, body }), fetchJson: (url, options) => { requests.push({ url, options }); return responder(url, options); } },
    });
    const api = window.MLXChatSessions;
    api.configure({ state, renderAll() {}, renderSidebar() {}, isGenerating: () => false, createSessionSettings: () => ({}), onSessionSelected() {} });
    return { state, cache, requests, resets, dialogs, api,
        set confirm(value) { confirm = value; }, set respond(value) { responder = value; },
        get attachments() { return attachments; }, get detach() { return detach; } };
}
const ok = data => ({ response: { ok: true }, data });
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return { promise, resolve }; };

test('cancel preserves history, cache, settings and running jobs', async () => {
    const f = fixture(); f.confirm = false;
    const before = JSON.stringify(f.state);
    assert.equal(await f.api.deleteAllSessions(), false);
    assert.equal(JSON.stringify(f.state), before);
    assert.equal(f.requests.length, 0); assert.equal(f.resets.length, 0);
    assert.equal(f.attachments, 0); assert.equal(f.detach, 0);
});

test('bulk deletion stops every session, clears only chat data and creates one empty chat', async () => {
    const f = fixture(); const old = [...f.state.sessions];
    assert.equal(await f.api.deleteAllSessions(), true);
    assert.equal(f.resets.length, 2);
    assert.ok(old.every(session => f.api.runtimeRevision(session) === 1));
    assert.equal(f.requests[0].options.method, 'DELETE');
    assert.deepEqual(Array.from(f.requests[0].options.body.ids), ['one', 'two']);
    assert.equal(f.attachments, 1); assert.equal(f.detach, 1);
    assert.equal(f.cache.get('settings'), 'keep');
    assert.equal(f.state.sessions.length, 1);
    assert.equal(f.state.sessions[0].messages.length, 0);
    assert.equal(f.state.activeId, 'new-empty');
    assert.deepEqual(JSON.parse(f.cache.get('mlx-web-chats-v1')).map(chat => chat.id), ['new-empty']);
    f.respond = async () => ok({ chats: [], deleted_ids: ['one', 'two'] });
    await f.api.syncWithServer();
    f.api.loadSessions();
    assert.deepEqual(Array.from(f.state.sessions, chat => chat.id), ['new-empty']);
});

test('unreachable server retains local history and shows a failure dialog', async () => {
    const f = fixture(); f.respond = async () => { throw new Error('offline'); };
    assert.equal(await f.api.deleteAllSessions(), false);
    assert.deepEqual(Array.from(f.state.sessions, chat => chat.id), ['one', 'two']);
    assert.equal(f.attachments, 0); assert.equal(f.detach, 0);
    assert.equal(f.dialogs.length, 2);
    assert.match(f.dialogs[1].message, /retained/);
    assert.deepEqual(JSON.parse(f.cache.get('mlx-web-chats-v1')).map(chat => chat.id), ['one', 'two']);
});

test('late sync response cannot restore chats after deletion', async () => {
    const f = fixture(); const sync = deferred();
    f.respond = (url, options) => options?.method === 'DELETE' ? Promise.resolve(ok({ ok: true })) : sync.promise;
    const pending = f.api.syncWithServer();
    await f.api.deleteAllSessions();
    sync.resolve(ok({ chats: [oldChat('one'), oldChat('two')] }));
    await pending;
    assert.deepEqual(Array.from(f.state.sessions, chat => chat.id), ['new-empty']);
});

test('waits for old PUT and blocks concurrent creation/persistence before deletion', async () => {
    const f = fixture(); await f.api.syncWithServer();
    const put = deferred(), deleting = deferred(); let deletingStarted;
    const entered = new Promise(resolve => deletingStarted = resolve);
    f.respond = (url, options) => {
        if (options?.method === 'PUT' && options.body.id === 'one') return put.promise;
        if (options?.method === 'DELETE') { deletingStarted(); return deleting.promise; }
        return Promise.resolve(ok({ chat: options.body }));
    };
    const old = f.state.sessions[0];
    const pendingPut = f.api.persistSession(old);
    const pendingDelete = f.api.deleteAllSessions();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.requests.filter(item => item.options?.method === 'DELETE').length, 0);
    f.api.createSession(); f.api.saveSessions();
    assert.equal(f.state.sessions.length, 2);
    put.resolve(ok({ chat: { ...old, updated: 9999 } }));
    await pendingPut; await entered;
    assert.equal(old.updated, 2, 'stale PUT response is ignored');
    deleting.resolve(ok({ ok: true })); await pendingDelete;
    await f.api.persistSession(old);
    assert.deepEqual(Array.from(f.state.sessions, chat => chat.id), ['new-empty']);
});

test('server tombstones discard stale local cache during reload sync', async () => {
    const f = fixture();
    f.respond = async (_url, options) => options?.method === 'PUT' ? ok({ chat: options.body }) : ok({ chats: [], deleted_ids: ['one', 'two'] });
    await f.api.syncWithServer();
    assert.deepEqual(Array.from(f.state.sessions, chat => chat.id), ['new-empty']);
    assert.ok(f.requests.every(item => !item.options || item.options.body.id === 'new-empty'));
});
