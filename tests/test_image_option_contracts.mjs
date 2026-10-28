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


// Image creation must not offer unavailable, disabled or edit-only models.
// Even a stale persisted choice must not reappear as a disabled option.
const modelStart = source.indexOf('async function updateImageModelOptions(');
const modelEnd = source.indexOf('\nconst IMAGE_OPTION_KEYS', modelStart);
assert.ok(modelStart >= 0 && modelEnd > modelStart);
const elements = [];
const savedChoices = [];
const catalogue = {
    default_model: 'juggernaut-xl',
    models: [
        {id: 'juggernaut-xl', name: 'Juggernaut Ragnarok', enabled: true, available: true, capabilities: ['text_to_image']},
        {id: 'mlxserve-qwen-image-2.1', name: 'Qwen Image 2.1', enabled: true, available: true, capabilities: ['text_to_image']},
        {id: 'mflux-osaurus-qwen-image-2.1-edit', name: 'Qwen 2.1 Edit', enabled: true, available: false, capabilities: ['image_edit']},
        {id: 'edit-ready', name: 'Edit installed', enabled: true, available: true, capabilities: ['image_edit']},
        {id: 'missing-weights', name: 'Weights missing', enabled: true, available: false, capabilities: ['text_to_image']},
        {id: 'disabled-model', name: 'Disabled model', enabled: false, available: true, capabilities: ['text_to_image']},
        {id: 'unknown-status', name: 'Unknown status', enabled: true, capabilities: ['text_to_image']},
    ]
};
const modelContext = vm.createContext({
    document: {createElement() {return {value: '', textContent: ''};}},
    window: {}, storedImageModel: () => 'auto',
    generationText(_key, fallback, values = {}) {
        return fallback.replaceAll('{model}', values.model || '');
    },
    storeImageModel: value => {savedChoices.push(value); return value;},
    fetch: async () => ({ok: true, async json() {return catalogue;}}),
});
vm.runInContext(source.slice(modelStart, modelEnd), modelContext);
const select = {
    value: '', disabled: false,
    replaceChildren(...items) {elements.splice(0, elements.length, ...items);},
    appendChild(item) {elements.push(item);}
};
const options = () => elements.map(option => option.value);
assert.equal(await modelContext.updateImageModelOptions(select, 'juggernaut-xl'), 'juggernaut-xl');
assert.deepEqual(options(), ['auto', 'juggernaut-xl', 'mlxserve-qwen-image-2.1']);
assert.equal(elements[0].textContent, 'Automatic (Juggernaut Ragnarok)');
assert.equal(select.disabled, false);
assert.equal(savedChoices.length, 0);

// An unavailable or edit-only model cannot silently replace a manual
// generation preference with Auto/Qwen.
for (const stale of ['mflux-osaurus-qwen-image-2.1-edit', 'missing-weights',
                     'disabled-model', 'edit-ready', 'unknown-status', 'manual-missing']) {
    await assert.rejects(modelContext.updateImageModelOptions(select, stale), /unavailable/);
    assert.deepEqual(options(), ['auto', 'juggernaut-xl', 'mlxserve-qwen-image-2.1']);
    assert.equal(select.disabled, false);
}
assert.equal(savedChoices.length, 0);

// Image editing has a separate capability-filtered list, and only ready
// image-edit checkpoints are shown there.
assert.equal(await modelContext.updateImageModelOptions(select, 'edit-ready', 'image_edit'), 'edit-ready');
assert.deepEqual(options(), ['auto', 'edit-ready']);
await assert.rejects(modelContext.updateImageModelOptions(select, 'juggernaut-xl', 'image_edit'), /unavailable/);
assert.deepEqual(options(), ['auto', 'edit-ready']);

// A service outage should never surface a stale option or overwrite the saved
// preference, and an automatic entry remains selectable.
const savedBeforeOutage = savedChoices.length;
modelContext.fetch = async () => {throw new Error('offline');};
await assert.rejects(modelContext.updateImageModelOptions(select, 'manual-offline'), /offline/);
assert.deepEqual(options(), ['auto']);
assert.equal(select.disabled, false);
assert.equal(savedChoices.length, savedBeforeOutage);
console.log('Image model picker hides unavailable models without changing manual choices.');
