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

console.log(
    'SSE finalization: final metrics, arbitrary chunks, Unicode, and event behavior passed.',
);
