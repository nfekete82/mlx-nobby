import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    'frontend/assets/chat/assistant-read-aloud.js',
    'utf8'
);
const loader = fs.readFileSync(
    'frontend/assets/chat/voice-loading.js',
    'utf8'
);
const de = JSON.parse(fs.readFileSync(
    'frontend/i18n/assistant-read-aloud.de.json',
    'utf8'
));
const en = JSON.parse(fs.readFileSync(
    'frontend/i18n/assistant-read-aloud.en.json',
    'utf8'
));

assert.match(loader, /assistant-read-aloud\.js/, 'voice bootstrap must load assistant read-aloud controller');
assert.match(source, /CHUNK_MAX_CHARS\s*=\s*600/, 'assistant TTS chunks must stay bounded');
assert.match(source, /REQUEST_TIMEOUT_MS\s*=\s*60000/, 'assistant TTS requests need a hard timeout');
assert.match(source, /\.message\.assistant/, 'controller must only intercept assistant playback');
assert.match(source, /stopImmediatePropagation\(\)/, 'controller must replace the legacy assistant click handler');
assert.match(source, /cloneNode\(true\)/, 'assistant speech must come from rendered visible content');
assert.match(source, /querySelectorAll\?\.\(\s*'pre,/, 'code blocks must be excluded from spoken text');
assert.match(source, /state\.controller\?\.abort\(\)/, 'a second click must be able to abort generation');
assert.doesNotMatch(source, /message\.content/, 'raw assistant markdown must not be sent to TTS');
assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort(), 'assistant TTS translations must stay in sync');

const appended = [];
const documentStub = {
    documentElement: { lang: 'en' },
    head: { appendChild: node => appended.push(node) },
    getElementById: () => null,
    createElement: () => ({
        style: {},
        classList: { add() {}, remove() {}, toggle() {} },
        setAttribute() {},
        addEventListener() {}
    }),
    addEventListener() {}
};
const windowStub = {
    MLXI18n: { getLanguage: () => 'en' }
};
const context = vm.createContext({
    window: windowStub,
    document: documentStub,
    console,
    URL,
    AbortController,
    MutationObserver: undefined,
    Audio: function Audio() {},
    setTimeout,
    clearTimeout,
    fetch: async () => ({ ok: false })
});
vm.runInContext(source, context);

const helpers = windowStub.MLXAssistantReadAloud.__test;
const normalized = helpers.normalizeVisibleText(
    'Hello   world.\n\nhttps://example.com/test\nNext line.'
);
assert.equal(normalized.includes('https://'), false, 'visible speech text must omit raw URLs');
assert.equal(helpers.CHUNK_MAX_CHARS, 600);
assert.equal(helpers.REQUEST_TIMEOUT_MS, 60000);

const longText = Array.from(
    { length: 150 },
    (_, index) => `Sentence ${index + 1}.`
).join(' ');
const chunks = helpers.splitSpeechText(longText);
assert.ok(chunks.length > 1, 'long assistant responses must be chunked');
assert.ok(chunks.every(chunk => chunk.length <= 600), 'no assistant TTS chunk may exceed 600 characters');
assert.equal(chunks.join(' ').replace(/\s+/g, ' ').trim(), longText, 'chunking must preserve spoken text');

console.log('✓ assistant read-aloud uses visible text, bounded chunks, timeout and cancellation');
