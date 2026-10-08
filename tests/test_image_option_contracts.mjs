import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the actual composer helper with a minimal DOM-free context.
const source = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const start = source.indexOf('const IMAGE_OPTION_KEYS = Object.freeze({');
const end = source.indexOf('\nfunction isImageEditRequest(', start);
assert.ok(start >= 0 && end > start, 'composer image-options helper exists');

const context = vm.createContext({
    IMAGE_SIZES_BY_FORMAT: {
        square: {width: 1024, height: 1024},
        portrait: {width: 768, height: 1024},
    },
});
vm.runInContext(source.slice(start, end), context, {filename: 'generation-image-options.js'});
const compose = (settings, mode, allowFormat = false, prompt = 'old session negative') =>
    JSON.parse(JSON.stringify(context.imageOptionsForRequest(
        {image: settings},
        'image',
        'portrait',
        allowFormat,
        prompt,
        'auto',
        mode,
    )));

const stale = {
    negative_prompt: 'old session negative',
    width: 300,
    height: 300,
    auto_size: true,
    format: 'landscape',
    count: 4,
    model: 'some-old-model',
    steps: 30,
    seed: 123,
};

assert.deepEqual(compose(stale, 'edit'), {
    model: 'auto',
    steps: 30,
    seed: 123,
});
assert.deepEqual(compose(stale, 'generate', true), {
    negative_prompt: 'old session negative',
    width: 768,
    height: 1024,
    auto_size: true,
    model: 'auto',
    steps: 30,
    seed: 123,
});
assert.deepEqual(compose(stale, 'reference', true), {
    negative_prompt: 'old session negative',
    width: 768,
    height: 1024,
    auto_size: true,
    model: 'auto',
    steps: 30,
    seed: 123,
});
assert.deepEqual(compose(stale, 'generate', false, ''), {
    width: 300,
    height: 300,
    auto_size: true,
    model: 'auto',
    steps: 30,
    seed: 123,
});
assert.equal(source.includes("referenceMode ? 'reference' : 'edit'"), true);
console.log('Image mode parameter contracts: generation/edit/reference settings isolated.');
