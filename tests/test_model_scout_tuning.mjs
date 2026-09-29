import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/model-scout.js', import.meta.url),
    'utf8',
);

const window = {};
window.window = window;

class MutationObserverStub {
    observe() {}
    disconnect() {}
}

const document = {
    readyState: 'loading',
    documentElement: {},
    addEventListener() {},
    querySelector() { return null; },
};

const context = {
    window,
    document,
    navigator: { language: 'en-US' },
    MutationObserver: MutationObserverStub,
    requestAnimationFrame() {},
    console,
    Intl,
    Date,
    Array,
    String,
    Number,
    Object,
    RegExp,
    Set,
    Map,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/model-scout.js',
});

const tuningTraits = window.MLXModelScout?.tuningTraits;
assert.equal(typeof tuningTraits, 'function');

assert.deepEqual(
    Array.from(tuningTraits({
        id: 'mlx-community/Qwen3.8-27B-Heretic-Abliterated-4bit',
        tags: [],
    })),
    ['heretic', 'abliterated'],
);

assert.deepEqual(
    Array.from(tuningTraits({
        id: 'mlx-community/Qwen3.8-27B-4bit',
        tags: ['uncensored'],
    })),
    ['uncensored'],
);

assert.deepEqual(
    Array.from(tuningTraits({
        id: 'mlx-community/Model-Orthogonalized-4bit',
        tags: ['unfiltered'],
    })),
    ['orthogonalized', 'unfiltered'],
);

assert.deepEqual(
    Array.from(tuningTraits({
        id: 'mlx-community/Qwen3.8-27B-Instruct-4bit',
        tags: ['text-generation'],
    })),
    [],
);

console.log('Model Scout tuning marker detection passed.');
