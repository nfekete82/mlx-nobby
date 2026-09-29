import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/model-scout-filter.js', import.meta.url),
    'utf8',
);

const window = {
    MLXModelScout: {
        tuningTraits(candidate) {
            const id = String(candidate?.id || '').toLowerCase();
            const traits = [];
            if (id.includes('heretic')) traits.push('heretic');
            if (id.includes('uncensored')) traits.push('uncensored');
            if (id.includes('abliterated')) traits.push('abliterated');
            return traits;
        },
    },
};
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
    navigator: { language: 'de-DE' },
    MutationObserver: MutationObserverStub,
    requestAnimationFrame() {},
    console,
    Array,
    String,
    Set,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/model-scout-filter.js',
});

const matches = window.MLXModelScout?.matchesTuningFilter;
assert.equal(typeof matches, 'function');

function card(id, tuningLabels = []) {
    return {
        querySelector(selector) {
            if (selector === '.model-scout-name') return { textContent: id };
            return null;
        },
        querySelectorAll(selector) {
            if (selector !== '.model-scout-chip.tuning') return [];
            return tuningLabels.map(textContent => ({ textContent }));
        },
    };
}

const heretic = card('mlx-community/Qwen3.8-27B-Heretic-4bit', ['Heretic']);
assert.equal(matches(heretic, 'all'), true);
assert.equal(matches(heretic, 'heretic'), true);
assert.equal(matches(heretic, 'uncensored'), false);
assert.equal(matches(heretic, 'standard'), false);

const tagOnlyUncensored = card('mlx-community/Qwen3.8-27B-4bit', ['Uncensored']);
assert.equal(matches(tagOnlyUncensored, 'uncensored'), true);
assert.equal(matches(tagOnlyUncensored, 'standard'), false);

const standard = card('mlx-community/Qwen3.8-27B-Instruct-4bit');
assert.equal(matches(standard, 'standard'), true);
assert.equal(matches(standard, 'abliterated'), false);

const abliterated = card('mlx-community/Qwen3.8-27B-Abliterated-4bit', ['Abliterated']);
assert.equal(matches(abliterated, 'abliterated'), true);
assert.equal(matches(abliterated, 'standard'), false);

console.log('Model Scout tuning filter passed.');
