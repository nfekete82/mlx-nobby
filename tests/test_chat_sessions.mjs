import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/sessions.js', import.meta.url),
    'utf8',
);

const state = { sessions: [], activeId: 'chat-1' };
let generating = false;
let nextResponse;
let renderCount = 0;
const cache = new Map();
const window = {};

vm.runInNewContext(source, {
    window,
    console,
    localStorage: {
        setItem(key, value) { cache.set(key, value); },
    },
    MLXCommon: {
        jsonRequest(_method, body) { return body; },
        fetchJson(_url, body) { return nextResponse(body); },
    },
}, { filename: 'frontend/assets/chat/sessions.js' });

const sessions = window.MLXChatSessions;
sessions.configure({
    state,
    renderAll() { renderCount++; },
    renderSidebar() {},
    isGenerating() { return generating; },
    createSessionSettings() { return {}; },
    onSessionSelected() {},
});

function chat(updated, messages = []) {
    return {
        id: 'chat-1',
        title: 'Chat',
        created: 1,
        updated,
        revision: updated,
        messages,
    };
}

nextResponse = async () => ({
    response: { ok: true },
    data: { chats: [chat(10)] },
});
await sessions.syncWithServer();

const session = state.sessions[0];
state.activeId = session.id;
const assistantMessage = {
    role: 'assistant',
    content: '',
    agent_run: { status: 'running' },
    _thinkingStarted: 123,
};
session.messages.push(assistantMessage);
sessions.bumpRuntimeRevision(session);
const messages = session.messages;
generating = true;

let respond;
nextResponse = () => new Promise(resolve => { respond = resolve; });
const pending = sessions.persistSession(session);
assistantMessage.agent_run.status = 'waiting';
respond({
    response: { ok: true },
    data: {
        chat: {
            ...chat(20, [{ role: 'assistant', content: 'stale' }]),
            _runtime_revision: 0,
        },
    },
});
await pending;

assert.strictEqual(state.sessions[0], session);
assert.strictEqual(sessions.currentSession(), session);
assert.strictEqual(session.messages, messages);
assert.strictEqual(session.messages[0], assistantMessage);
assert.equal(assistantMessage.agent_run.status, 'waiting');
assert.equal(assistantMessage._thinkingStarted, 123);
assert.equal(session.updated, 20);
assert.equal(session.revision, 20);
assert.equal(sessions.runtimeRevision(session), 1);
assert.equal(Object.keys(session).includes('_runtime_revision'), false);
assert.equal(JSON.parse(cache.get('mlx-web-chats-v1'))[0].revision, 20);

const rendersAfterUpdate = renderCount;
for (const updated of [19, 20]) {
    nextResponse = async () => ({
        response: { ok: true },
        data: { chat: chat(updated, []) },
    });
    await sessions.persistSession(session);
    assert.strictEqual(state.sessions[0], session);
    assert.strictEqual(session.messages[0], assistantMessage);
    assert.equal(session.revision, 20);
}
assert.equal(renderCount, rendersAfterUpdate);

generating = false;
nextResponse = async () => ({
    response: { ok: true },
    data: { chat: chat(30, [{ role: 'user', content: 'server' }]) },
});
await sessions.persistSession(session);
assert.strictEqual(state.sessions[0], session);
assert.equal(session.messages[0].content, 'server');
assert.equal(session.revision, 30);
assert.equal(sessions.runtimeRevision(session), 1);

nextResponse = () => new Promise(resolve => { respond = resolve; });
const changedWhilePending = sessions.persistSession(session);
const localMessage = { role: 'assistant', content: 'new local text' };
session.messages.push(localMessage);
respond({
    response: { ok: true },
    data: { chat: chat(35, [{ role: 'user', content: 'old text' }]) },
});
await changedWhilePending;
assert.strictEqual(state.sessions[0], session);
assert.strictEqual(session.messages[1], localMessage);
assert.equal(session.revision, 35);

generating = true;
const runningMessage = { role: 'assistant', agent_run: { status: 'running' } };
session.messages.push(runningMessage);
const activeMessages = session.messages;
nextResponse = async () => ({
    response: { ok: true },
    data: { chats: [chat(40, [])] },
});
await sessions.syncWithServer();
assert.strictEqual(state.sessions[0], session);
assert.strictEqual(session.messages, activeMessages);
assert.strictEqual(session.messages.at(-1), runningMessage);
assert.equal(session.revision, 40);
assert.equal(sessions.runtimeRevision(session), 1);

generating = false;
nextResponse = async () => ({
    response: { ok: true },
    data: { chats: [chat(50, [{ role: 'user', content: 'synced' }])] },
});
await sessions.syncWithServer();
assert.strictEqual(state.sessions[0], session);
assert.equal(session.messages[0].content, 'synced');
assert.equal(session.revision, 50);

console.log('Chat session persistence and sync identity passed.');
