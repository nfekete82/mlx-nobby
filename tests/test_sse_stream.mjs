import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { performance } from 'node:perf_hooks';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url),
    'utf8',
);

let generating = false;
let abortController = null;
const runtime = {
    isSwitching: () => false,
    getSessionGenerationSettings: () => ({
        temperature: 0.7,
        max_tokens: 3000,
    }),
    getSessionSystemPrompt: () => '',
    updateSendButton() {},
};
const sessions = {
    currentSession: () => session,

    runtimeRevision(targetSession) {
        const value = Number(
            targetSession?._runtime_revision
        );

        return (
            Number.isSafeInteger(value) &&
            value >= 0
        )
            ? value
            : 0;
    },

    bumpRuntimeRevision(targetSession) {
        if (!targetSession) {
            return 0;
        }

        const next =
            sessions.runtimeRevision(
                targetSession
            ) + 1;

        Object.defineProperty(
            targetSession,
            '_runtime_revision',
            {
                value: next,
                writable: true,
                configurable: true,
                enumerable: false
            }
        );

        return next;
    },

    runtimeRevisionIsCurrent(
        targetSession,
        revision
    ) {
        return (
            targetSession === session &&
            sessions.runtimeRevision(
                targetSession
            ) === revision
        );
    },

    saveSessions() {},
};
const rendering = {
    renderAll() {},
    renderMessages() {},
};
const window = {
    MLXI18n: {
        t(_key, fallback) {
            return fallback;
        },
    },
};
window.window = window;

const context = {
    AbortController,
    console,
    crypto: { randomUUID: () => 'generated-trace-id' },
    document: {
        getElementById() {
            return {};
        },
    },
    fetch: null,
    MLXChatRendering: rendering,
    MLXChatRuntime: runtime,
    MLXChatSessions: sessions,
    performance,
    TextDecoder,
    window,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/generation.js',
});

const generation = window.MLXChatGeneration;
generation.configure({
    getGenerating: () => generating,
    setGenerating: value => {
        generating = value;
    },
    getAbortController: () => abortController,
    setAbortController: value => {
        abortController = value;
    },
});

const encoder = new TextEncoder();

function readerFromChunks(chunks) {
    let index = 0;

    return {
        async read() {
            if (index >= chunks.length) {
                return { value: undefined, done: true };
            }

            return { value: chunks[index++], done: false };
        },
    };
}

function encodedChunks(...values) {
    return values.map(value => encoder.encode(value));
}

async function collectEvents(chunks) {
    const events = [];

    for await (
        const event of generation.__test.readSseEvents(
            readerFromChunks(chunks)
        )
    ) {
        events.push(event);
    }

    return events;
}

const metrics =
    'event: metrics\ndata: {"trace_id":"trace-normal"}';
const done = 'event: done\ndata: {}';

assert.deepEqual(
    await collectEvents(encodedChunks(metrics + '\n\n', done + '\n\n')),
    [metrics, done],
);

assert.deepEqual(
    await collectEvents(encodedChunks(metrics + '\n\n' + done + '\n\n')),
    [metrics, done],
);

assert.deepEqual(
    await collectEvents(encodedChunks(metrics)),
    [metrics],
);

const unicodeStream =
    'data: {"type":"content","text":"Grüße 🌍"}\n\n' +
    'event: metrics\ndata: {"trace_id":"trace-unicode"}';
const unicodeBytes = encoder.encode(unicodeStream);
const oneByteChunks = Array.from(
    unicodeBytes,
    byte => Uint8Array.of(byte),
);

assert.deepEqual(
    await collectEvents(oneByteChunks),
    [
        'data: {"type":"content","text":"Grüße 🌍"}',
        'event: metrics\ndata: {"trace_id":"trace-unicode"}',
    ],
);

const fullConversationStream = [
    'event: sources\ndata: {"sources":[{"title":"Source"}]}\n\n',
    'data: {"type":"reasoning","text":"Überlege 🧠"}\n\n',
    'data: {"type":"content","text":"Grüße 🌍"}\n\n',
    'event: metrics\ndata: {"trace_id":"trace-turn-001",',
    '"model_calls_in_turn":1}\n\n',
    'event: done\ndata: {}',
].join('');
const conversationBytes = encoder.encode(fullConversationStream);
const arbitraryChunks = [];
const chunkSizes = [1, 2, 7, 3, 11, 5];
let offset = 0;
let sizeIndex = 0;

while (offset < conversationBytes.length) {
    const size = chunkSizes[sizeIndex++ % chunkSizes.length];
    arbitraryChunks.push(conversationBytes.slice(offset, offset + size));
    offset += size;
}

context.fetch = async () => ({
    ok: true,
    body: {
        getReader: () => readerFromChunks(arbitraryChunks),
    },
});

const session = {
    messages: [{
        role: 'user',
        content: 'Question',
        trace_id: 'trace-turn-001',
    }],
};

await generation.generateAssistant(session);

const assistant = session.messages.at(-1);
assert.equal(assistant.reasoning, 'Überlege 🧠');
assert.equal(assistant.content, 'Grüße 🌍');
assert.equal(assistant.sources.length, 1);
assert.equal(assistant.sources[0].title, 'Source');
assert.equal(assistant.model_metrics.trace_id, 'trace-turn-001');
assert.equal(assistant.model_metrics.model_calls_in_turn, 1);


// Regression: stale generation after chat reset must never restore content.
{
    let resolveResponse;
    let responseBodyCancelled = false;

    context.fetch = async () =>
        new Promise(resolve => {
            resolveResponse = resolve;
        });

    session.messages = [
        {
            role: 'user',
            content: 'Old request',
            trace_id: 'trace-stale-reset',
        },
    ];

    const generationPromise =
        generation.generateAssistant(session);

    // Allow generateAssistant() to create its pending assistant message
    // and reach the unresolved fetch().
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(
        session.messages.length,
        2,
        'generation should have created a pending assistant message',
    );

    assert.equal(
        session.messages.at(-1).role,
        'assistant',
    );

    // Simulate "Chat leeren": invalidate all work from the old runtime
    // revision and remove the conversation contents.
    sessions.bumpRuntimeRevision(session);
    session.messages = [];

    resolveResponse({
        ok: true,
        body: {
            async cancel() {
                responseBodyCancelled = true;
            },
            getReader() {
                throw new Error(
                    'stale response must never open its SSE reader'
                );
            },
        },
    });

    await generationPromise;

    assert.deepEqual(
        session.messages,
        [],
        'stale generation must not restore messages after chat reset',
    );

    assert.equal(
        responseBodyCancelled,
        true,
        'stale response body should be cancelled',
    );
}

// Regression: the real resetSessionRuntime() path must invalidate an
// in-flight generation before a late response can restore stale content.
{
    let resolveResponse;
    let responseBodyCancelled = false;

    context.fetch = async () =>
        new Promise(resolve => {
            resolveResponse = resolve;
        });

    session.messages = [
        {
            role: 'user',
            content: 'Old request through real reset',
            trace_id: 'trace-real-reset-race',
        },
    ];

    const generationPromise =
        generation.generateAssistant(session);

    // Let generateAssistant() create the pending assistant message and
    // block on the unresolved fetch().
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(
        session.messages.length,
        2,
        'generation should be pending before reset',
    );

    const revisionBeforeReset =
        sessions.runtimeRevision(session);

    // Exercise the production reset runtime path rather than manually
    // reproducing its state changes.
    await generation.resetSessionRuntime(session);

    sessions.bumpRuntimeRevision(session);
    session.messages = [];

    assert.equal(
        generating,
        false,
        'resetSessionRuntime should clear generating state',
    );

    assert.equal(
        abortController,
        null,
        'resetSessionRuntime should clear the abort controller',
    );

    assert.equal(
        sessions.runtimeRevision(session),
        revisionBeforeReset + 1,
        'reset should invalidate the old runtime revision',
    );

    // Complete the old request only after reset has finished.
    resolveResponse({
        ok: true,
        body: {
            async cancel() {
                responseBodyCancelled = true;
            },
            getReader() {
                throw new Error(
                    'late stale response must never open its SSE reader'
                );
            },
        },
    });

    await generationPromise;

    assert.deepEqual(
        session.messages,
        [],
        'late generation must not restore messages after real reset',
    );

    assert.equal(
        responseBodyCancelled,
        true,
        'late stale response body should be cancelled',
    );
}


// Regression: resetSessionRuntime() must abort the active text request
// before clearing the shared AbortController reference.
{
    let abortObserved = false;

    const controller = new AbortController();

    controller.signal.addEventListener(
        'abort',
        () => {
            abortObserved = true;
        },
        { once: true },
    );

    abortController = controller;
    generating = true;

    await generation.resetSessionRuntime(session);

    assert.equal(
        controller.signal.aborted,
        true,
        'active AbortController should be aborted by reset',
    );

    assert.equal(
        abortObserved,
        true,
        'abort signal should be observable by the active request',
    );

    assert.equal(
        abortController,
        null,
        'AbortController reference should be cleared after abort',
    );

    assert.equal(
        generating,
        false,
        'generation state should be cleared after reset',
    );
}


console.log(
    'SSE finalization: final metrics, arbitrary chunks, Unicode, and event behavior passed.',
);
