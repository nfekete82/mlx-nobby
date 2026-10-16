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

// The modal's displayed Ragnarok values must beat old explicit settings.
const creatorSampling = JSON.parse(JSON.stringify(
    context.imageOptionsForRequest(
        {image: {model: 'juggernaut-xl', steps: 30, guidance: 5.0}},
        'image', 'portrait', true, '', 'juggernaut-xl', 'generate',
        {steps: 40, guidance: 4.0}
    )
));
assert.equal(creatorSampling.steps, 40);
assert.equal(creatorSampling.guidance, 4.0);
assert.equal(creatorSampling.model, 'juggernaut-xl');
assert.equal(creatorSampling.auto_size, true);

// No accidental expert-parameter injection for other models or edits.
const noCrossModel = JSON.parse(JSON.stringify(
    context.imageOptionsForRequest(
        {image: {}}, 'image', 'square', true, '',
        'mlxserve-qwen-image-2.1', 'generate',
        {steps: 40, guidance: 4.0}
    )
));
assert.equal(noCrossModel.steps, undefined);
assert.equal(noCrossModel.guidance, undefined);


// A selected but temporarily unavailable model must remain explicit.
const modelStart = source.indexOf('async function updateImageModelOptions(');
const modelEnd = source.indexOf('\nconst IMAGE_OPTION_KEYS', modelStart);
const elements = [];
const modelContext = vm.createContext({
    document: {createElement() {return {};}},
    window: {}, storedImageModel: () => 'auto',
    fetch: async () => ({ok:true, async json() {return {models:[]};}}),
});
vm.runInContext(source.slice(modelStart, modelEnd), modelContext);
const select = {value:'', replaceChildren(...items) {elements.splice(0, elements.length, ...items);},
    appendChild(item) {elements.push(item);}};
assert.equal(await modelContext.updateImageModelOptions(select, 'manual-missing'), 'manual-missing');
assert.equal(elements.at(-1).disabled, true);
modelContext.fetch = async () => {throw new Error('offline');};
assert.equal(await modelContext.updateImageModelOptions(select, 'manual-offline'), 'manual-offline');
