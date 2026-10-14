import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/compact.js', import.meta.url), 'utf8'
);

function environment() {
    let enabled = true;
    let requestCount = 0;
    let fetchHandler = async (_url, body) => ({
        response: { ok: true },
        data: {
            compacted: true,
            messages: [
                { role: 'system', content: 'Context: ' + 'important fact. '.repeat(60) },
                ...body.messages.slice(-12)
            ]
        }
    });
    const window = {
        MLXChatRuntime: { isAutoCompactEnabled: () => enabled },
        MLXI18n: { t: (_key, fallback) => fallback }
    };
    const context = {
        window,
        console: { log() {}, warn() {}, error() {} },
        MLXCommon: {
            jsonRequest(_method, payload) { return payload; },
            async fetchJson(url, payload) {
                requestCount++;
                return fetchHandler(url, payload);
            },
            fastApiDetailError() { return new Error('HTTP failed'); }
        },
        MLXChatSessions: { saveSessions() { throw Error('Auto mutated chat'); } },
        MLXChatRendering: { renderAll() { throw Error('Auto re-rendered'); } }
    };
    vm.runInNewContext(source, context, { filename: 'compact.js' });
    return {
        compact: window.MLXChatCompact,
        setEnabled(value) { enabled = value; },
        setFetchHandler(handler) { fetchHandler = handler; },
        get requestCount() { return requestCount; }
    };
}

function history() {
    return Array.from({ length: 20 }, (_, i) => ({
        role: i % 2 ? 'assistant' : 'user',
        content: (i % 2 ? 'Response ' : 'Question ') + i + ': ' +
            'Useful ordinary conversation context. '.repeat(165)
    }));
}

test('auto compaction retains full chat, lowers outgoing size, and reuses summary', async () => {
    const env = environment();
    const session = { messages: history() };
    const originalRefs = [...session.messages];
    const originalContents = session.messages.map(x => x.content);
    const before = env.compact.messageChars(session.messages);
    assert.equal(await env.compact.autoCompactIfNeeded(session), true);
    assert.equal(env.requestCount, 1);
    assert.deepEqual(session.messages, originalRefs);
    assert.deepEqual(session.messages.map(x => x.content), originalContents);

    let out = env.compact.messagesForInference(session, session.messages);
    assert.equal(out.length, 13);
    assert.equal(out[0].role, 'user');
    assert.match(out[0].content, /Archived conversation context/);
    assert.ok(env.compact.messageChars(out) < before * .8);
    assert.equal(out.at(-1), session.messages.at(-1));

    // Each new turn should reuse the summary, without extra model calls.
    session.messages.push({ role: 'user', content: 'A new question.' });
    session.messages.push({ role: 'assistant', content: 'New reply.' });
    assert.equal(await env.compact.autoCompactIfNeeded(session), true);
    assert.equal(env.requestCount, 1);
    out = env.compact.messagesForInference(session, session.messages);
    assert.equal(out.length, 15);
    assert.equal(out.at(-1), session.messages.at(-1));

    env.setEnabled(false);
    assert.deepEqual(
        env.compact.messagesForInference(session, session.messages),
        session.messages
    );
});

test('editing or regenerating a past turn invalidates the cached summary', async () => {
    const env = environment();
    const session = { messages: history() };
    assert.equal(await env.compact.autoCompactIfNeeded(session), true);
    session.messages[0].content = 'edited first message';
    const out = env.compact.messagesForInference(session, session.messages);
    assert.equal(out.length, 20);
    assert.equal(out[0], session.messages[0]);
});

test('incoming file, code or tool history bypasses model compaction', async () => {
    for (const patch of [
        msg => { msg.content += '\n```python\nprint(1)\n```'; },
        msg => { msg.attachments = [{ kind: 'image' }]; },
        msg => { msg.agent_run = { goal: 'inspect workspace' }; },
        msg => { msg.content += '\nUse main.py'; }
    ]) {
        const env = environment();
        const session = { messages: history() };
        patch(session.messages[2]);
        assert.equal(await env.compact.autoCompactIfNeeded(session), false);
        assert.equal(env.requestCount, 0);
        assert.deepEqual(
            env.compact.messagesForInference(session, session.messages),
            session.messages
        );
    }
});

test('empty, non-saving and mismatched responses fail open to original history', async () => {
    for (const data of [
        { compacted: true, messages: [{ role: 'system', content: '' }] },
        { compacted: true, messages: [{ role: 'system', content: 'Too short' }] },
        {
            compacted: true,
            messages: [
                { role: 'system', content: 'Summary. '.repeat(60) },
                { role: 'user', content: 'Wrong suffix' }
            ]
        },
        { compacted: false, messages: [] }
    ]) {
        const env = environment();
        env.setFetchHandler(async () => ({ response: { ok: true }, data }));
        const session = { messages: history() };
        assert.equal(await env.compact.autoCompactIfNeeded(session), false);
        assert.equal(env.compact.messagesForInference(session, session.messages).length, 20);
    }
});

test('in-flight compaction never overwrites a cleared or changed chat', async () => {
    const env = environment();
    let resolve;
    env.setFetchHandler((_url, body) => new Promise(done => {
        resolve = () => done({
            response: { ok: true },
            data: {
                compacted: true,
                messages: [
                    { role: 'system', content: 'Summary. '.repeat(70) },
                    ...body.messages.slice(-12)
                ]
            }
        });
    }));
    const session = { messages: history() };
    const pending = env.compact.autoCompactIfNeeded(session);
    session.messages = [];
    resolve();
    assert.equal(await pending, false);
    assert.equal(session.messages.length, 0);
    assert.deepEqual(env.compact.messagesForInference(session, session.messages), []);
});

test('two concurrent compaction requests coalesce into one model call', async () => {
    const env = environment();
    let resolve;
    env.setFetchHandler((_url, body) => new Promise(done => {
        resolve = () => done({
            response: { ok: true },
            data: {
                compacted: true,
                messages: [
                    { role: 'system', content: 'Summary. '.repeat(70) },
                    ...body.messages.slice(-12)
                ]
            }
        });
    }));
    const session = { messages: history() };
    const first = env.compact.autoCompactIfNeeded(session);
    const second = env.compact.autoCompactIfNeeded(session);
    assert.equal(env.requestCount, 1);
    resolve();
    assert.equal(await first, true);
    assert.equal(await second, true);
    assert.equal(env.requestCount, 1);
});
