import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/assets/chat/tts-cache.js', import.meta.url), 'utf8');
const MiB = 1024 * 1024;

function harness(blobSize) {
    const calls = [];
    const events = {};
    // Model Blob sizes without allocating large audio buffers in unit tests.
    class AudioResponse {
        constructor(blob, options = {}) {
            this.audio = blob;
            this.ok = true;
            this.status = options.status || 200;
            this.statusText = 'OK';
            this.headers = new Map([['content-type', 'audio/mpeg']]);
        }
        clone() { return new AudioResponse(this.audio); }
        async blob() { return this.audio; }
    }
    const window = {
        location: {origin: 'http://localhost'},
        fetch: async (url, init) => {
            calls.push({url, init});
            const size = typeof blobSize === 'function' ? blobSize(JSON.parse(init.body)) : blobSize;
            return new AudioResponse({size});
        },
        addEventListener: (event, handler) => { events[event] = handler; },
    };
    vm.runInNewContext(source, {
        window, document: {addEventListener() {}}, Response: AudioResponse, URL,
    });
    const speak = (text) => window.fetch('/api/mlx/audio/speech', {
        method: 'POST', body: JSON.stringify({input: text}),
    });
    return {window, calls, events, speak};
}

test('repeated speech reuses cached audio and keeps non-speech fetches intact', async () => {
    const {window, calls, speak} = harness(MiB);
    const original = await speak('hello');
    const replay = await speak('hello');
    assert.equal(calls.length, 1);
    assert.equal((await replay.blob()).size, (await original.blob()).size);
    await window.fetch('/api/mlx/status');
    assert.equal(calls.length, 2);
});

test('byte budget evicts oldest speech before the 40-entry limit', async () => {
    const {window, calls, speak} = harness(12 * MiB);
    for (const text of ['one', 'two', 'three']) await speak(text);
    assert.equal(window.MLXTTSCache.size(), 2);
    assert.equal(window.MLXTTSCache.has('one'), false);
    assert.equal(window.MLXTTSCache.has('two'), true);
    await speak('three');
    assert.equal(calls.length, 3);
    await speak('one');
    assert.equal(calls.length, 4);
});

test('oversized audio is returned but does not displace cached smaller responses', async () => {
    const {window, speak} = harness(body => (body.input === 'long' ? 33 : 1) * MiB);
    await speak('short');
    assert.equal((await (await speak('long')).blob()).size, 33 * MiB);
    assert.equal(window.MLXTTSCache.size(), 1);
    assert.equal(window.MLXTTSCache.has('short'), true);
    assert.equal(window.MLXTTSCache.has('long'), false);
});

test('entry count remains bounded for small responses', async () => {
    const {window, speak} = harness(1);
    for (let i = 0; i < 41; i++) await speak(String(i));
    assert.equal(window.MLXTTSCache.size(), 40);
    assert.equal(window.MLXTTSCache.has('0'), false);
});

test('invalidation and voice changes release cached audio', async () => {
    const {window, events, speak} = harness(12 * MiB);
    await speak('one');
    await speak('two');
    assert.equal(window.MLXTTSCache.invalidateText('one'), 1);
    await speak('three');
    assert.equal(window.MLXTTSCache.size(), 2);
    events['mlx:voice-settings-changed']();
    assert.equal(window.MLXTTSCache.size(), 0);
    await speak('four');
    assert.equal(window.MLXTTSCache.size(), 1);
    window.MLXTTSCache.clear();
    assert.equal(window.MLXTTSCache.size(), 0);
});
