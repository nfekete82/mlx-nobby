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
    assert.match(source, /savedImageCreation\?\.quality/);
    assert.match(source, /savedImageCreation\?\.format/);
    assert.match(source, /savedImageCreation\?\.negative_prompt/);
    const onCancel = source.slice(
        source.indexOf('const onCancel = () => {', startConfirm - 6000),
        startConfirm
    );
    assert.doesNotMatch(onCancel, /storeImageCreationPreferences/);
    assert.match(negativeEditor, /imageCreationRestored === 'true'/);
});
