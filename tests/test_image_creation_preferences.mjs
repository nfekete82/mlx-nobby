import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8'
);
const negativeEditor = fs.readFileSync(
    new URL('../frontend/assets/chat/negative-prompt-editor.js', import.meta.url), 'utf8'
);
const start = source.indexOf('const IMAGE_CREATION_PREFERENCES_KEY =');
const end = source.indexOf('// Model-specific expert inputs', start);
assert.ok(start >= 0 && end > start);

function preferenceContext(storage) {
    const context = vm.createContext({
        window: {localStorage: storage},
        IMAGE_FORMATS: [
            'landscape', 'portrait', 'square', 'landscape_4_3',
            'portrait_3_4', 'portrait_ragnarok'
        ]
    });
    vm.runInContext(source.slice(start, end), context);
    return context;
}

test('image generation selections survive reopening and page reloads', () => {
    const saved = new Map();
    const storage = {
        getItem: key => saved.get(key) ?? null,
        setItem: (key, value) => saved.set(key, value)
    };
    const original = preferenceContext(storage);
    assert.equal(original.storedImageCreationPreferences(), null);

    original.storeImageCreationPreferences({
        quality: 'ultra', format: 'portrait_3_4',
        model: 'mlxserve-qwen-image-2.1',
        negative_prompt: 'deformed face, malformed hands'
    });

    const afterReload = preferenceContext(storage);
    assert.deepEqual(
        JSON.parse(JSON.stringify(afterReload.storedImageCreationPreferences())),
        {
            quality: 'ultra',
            format: 'portrait_3_4',
            model: 'mlxserve-qwen-image-2.1',
            negative_prompt: 'deformed face, malformed hands'
        }
    );
    afterReload.storeImageCreationPreferences({
        quality: 'fast', format: 'landscape', model: 'auto',
        negative_prompt: ''
    });
    assert.equal(
        preferenceContext(storage).storedImageCreationPreferences().negative_prompt,
        '',
        'Clearing the negative prompt must remain an intentional selection'
    );
    assert.equal(preferenceContext(storage).storedImageCreationPreferences().quality, 'fast');
});

test('corrupt or unsupported saved options fall back safely', () => {
    let raw = '{"quality":"unknown","format":"invalid","model":123,"negative_prompt":null}';
    const storage = {
        getItem: () => raw,
        setItem: (_key, value) => { raw = value; }
    };
    const context = preferenceContext(storage);
    const normalized = JSON.parse(JSON.stringify(context.storedImageCreationPreferences()));
    assert.deepEqual(normalized, {
        quality: 'standard', format: 'square', model: 'auto', negative_prompt: ''
    });
    raw = '{not valid';
    assert.equal(context.storedImageCreationPreferences(), null);
    raw = '[]';
    assert.equal(context.storedImageCreationPreferences(), null);
    const blocked = preferenceContext({
        getItem() {throw new Error('storage disabled');},
        setItem() {throw new Error('storage disabled');}
    });
    assert.equal(blocked.storedImageCreationPreferences(), null);
    assert.doesNotThrow(() => blocked.storeImageCreationPreferences({
        quality: 'standard', format: 'square', model: 'auto', negative_prompt: ''
    }));
});

test('only confirmed new image generation updates the saved preference', () => {
    const startConfirm = source.indexOf('const onConfirm = () => {');
    const endConfirm = source.indexOf('const onKeydown = event => {', startConfirm);
    const confirm = source.slice(startConfirm, endConfirm);
    assert.match(confirm, /if \(resolvedTarget === 'image'\) \{\s*storeImageCreationPreferences\(\{/);
    assert.match(confirm, /negative_prompt: selectedNegativePrompt/);
    assert.ok(source.includes("options?.image?.model && options.image.model !== 'auto'"));
    assert.ok(source.includes('savedImageCreation?.model || storedImageModel()'));
    assert.match(source, /savedImageCreation\?\.format/);
    assert.match(source, /savedImageCreation\?\.negative_prompt/);
    const onCancel = source.slice(
        source.indexOf('const onCancel = () => {', startConfirm - 6000),
        startConfirm
    );
    assert.doesNotMatch(onCancel, /storeImageCreationPreferences/);
    assert.match(source, /if \(negativePromptInput\?\.dataset\)/);
    assert.match(negativeEditor, /imageCreationRestored === 'true'/);
});


test('manual model choice remains authoritative and unavailable models never downgrade to Auto', async () => {
    assert.match(source, /savedImageCreation\\?\\.model \\|\\| options\\?\\.image\\?\\.model/);
    assert.ok(source.includes('merged.model = normalizedModel'));

    const selectionStart = source.indexOf('function storedImageModel()');
    const selectionEnd = source.indexOf('const IMAGE_OPTION_KEYS', selectionStart);
    assert.ok(selectionStart >= 0 && selectionEnd > selectionStart);
    const saved = new Map([['mlx-nobby-image-model', 'juggernaut-xl']]);
    const context = vm.createContext({
        IMAGE_MODEL_STORAGE_KEY: 'mlx-nobby-image-model',
        generationText(_key, fallback, values = {}) {
            return fallback.replaceAll('{model}', values.model || '');
        },
        window: {
            localStorage: {
                getItem: key => saved.get(key) ?? null,
                setItem: (key, value) => saved.set(key, value),
            },
            MLXI18n: {t(_key, fallback) {return fallback;}}
        },
        document: {createElement() {return {value: '', textContent: ''};}},
        fetch: async () => ({ok: true, async json() {
            return {default_model: 'mlxserve-qwen-image-2.1', models: [
                {id: 'mlxserve-qwen-image-2.1', name: 'Qwen', enabled: true,
                 available: true, capabilities: ['text_to_image']},
                {id: 'juggernaut-xl', name: 'Ragnarok', enabled: true,
                 available: true, capabilities: ['text_to_image']},
            ]};
        }})
    });
    vm.runInContext(source.slice(selectionStart, selectionEnd), context);
    const select = {
        disabled: false, children: [],
        replaceChildren(...options) {this.children = options;},
        appendChild(option) {this.children.push(option);}
    };
    assert.equal(await context.updateImageModelOptions(select, 'juggernaut-xl'), 'juggernaut-xl');
    assert.equal(select.value, 'juggernaut-xl');

    // A temporarily unavailable or disabled model must never become Qwen via Auto.
    context.fetch = async () => ({ok: true, async json() {
        return {default_model: 'mlxserve-qwen-image-2.1', models: [
            {id: 'mlxserve-qwen-image-2.1', name: 'Qwen', enabled: true,
             available: true, capabilities: ['text_to_image']},
            {id: 'juggernaut-xl', name: 'Ragnarok', enabled: false,
             available: false, capabilities: ['text_to_image']},
        ]};
    }});
    await assert.rejects(context.updateImageModelOptions(select, 'juggernaut-xl'), /unavailable/);
    assert.equal(saved.get('mlx-nobby-image-model'), 'juggernaut-xl');
    context.fetch = async () => {throw new Error('image service offline');};
    await assert.rejects(context.updateImageModelOptions(select, 'juggernaut-xl'), /offline/);
    assert.equal(saved.get('mlx-nobby-image-model'), 'juggernaut-xl');
});


test('leading image command shows Juggernaut for Auto even when registry defaults to Qwen', async () => {
    const modelStart = source.indexOf('async function updateImageModelOptions(');
    const modelEnd = source.indexOf('const IMAGE_OPTION_KEYS', modelStart);
    assert.ok(modelStart >= 0 && modelEnd > modelStart);
    assert.match(source, /LEADING_AUTO_JUGGERNAUT_PATTERN\.test\(prompt\)/);
    assert.match(source, /resolvedTarget === 'image' &&[\s\S]*?LEADING_AUTO_JUGGERNAUT_PATTERN\.test\(prompt\)/);

    const context = vm.createContext({
        window: {MLXI18n: {t(_key, fallback) {return fallback;}}},
        document: {createElement() {return {value: '', textContent: ''};}},
        storedImageModel: () => 'auto',
        fetch: async () => ({ok: true, async json() {
            return {default_model: 'mlxserve-qwen-image-2.1', models: [
                {id: 'juggernaut-xl', name: 'Juggernaut XL Ragnarok', enabled: true,
                 available: true, capabilities: ['text_to_image']},
                {id: 'mlxserve-qwen-image-2.1', name: 'Qwen Image', enabled: true,
                 available: true, capabilities: ['text_to_image']},
            ]};
        }})
    });
    vm.runInContext(source.slice(modelStart, modelEnd), context);
    const select = {
        disabled: false, children: [],
        replaceChildren(...options) {this.children = options;},
        appendChild(option) {this.children.push(option);}
    };
    assert.equal(await context.updateImageModelOptions(
        select, 'auto', 'text_to_image', 'juggernaut-xl'
    ), 'auto');
    assert.equal(select.value, 'auto');
    assert.equal(select.children[0].textContent, 'Automatic (Juggernaut XL Ragnarok)');

    assert.equal(await context.updateImageModelOptions(
        select, 'mlxserve-qwen-image-2.1', 'text_to_image', 'juggernaut-xl'
    ), 'mlxserve-qwen-image-2.1');
    assert.equal(select.value, 'mlxserve-qwen-image-2.1');
});
