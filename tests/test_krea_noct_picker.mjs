import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');
const start = source.indexOf('async function updateImageModelOptions(');
const end = source.indexOf('const IMAGE_OPTION_KEYS', start);
assert.ok(start >= 0 && end > start);

test('blocked Noct never appears in Generate or Edit; existing supported choices remain', async () => {
    const models = [
        {id: 'juggernaut-xl', name: 'Juggernaut XL Ragnarok', enabled: true, available: true,
            capabilities: ['text_to_image', 'image_edit']},
        {id: 'mflux-osaurus-qwen-image-2.1-edit', name: 'Osaurus Qwen Image 2.1', enabled: true,
            available: true, capabilities: ['image_edit']},
        {id: 'mflux-qwen-image-edit-2511', name: 'Qwen Image Edit', enabled: true,
            available: true, capabilities: ['image_edit']},
        {id: 'krea-noct-v4', name: 'Krea Noct (blocked fixture)', enabled: false,
            available: false, capabilities: ['text_to_image']},
    ];
    const context = vm.createContext({
        HIDDEN_IMAGE_MODEL_ID: 'cyberrealistic-pony-v18',
        storedImageModel: () => 'auto',
        window: {MLXI18n: {t: (_key, fallback) => fallback}},
        generationText: (_key, fallback) => fallback,
        document: {createElement: () => ({})},
        fetch: async url => {
            assert.equal(url, '/api/image/models');
            return {ok: true, json: async () => ({models, default_model: 'juggernaut-xl'})};
        },
    });
    vm.runInContext(source.slice(start, end), context);
    const select = {children: [], replaceChildren(...items) {this.children = items;},
        appendChild(item) {this.children.push(item);}};
    await context.updateImageModelOptions(select, 'juggernaut-xl');
    assert.deepEqual(select.children.map(item => item.value), ['auto', 'juggernaut-xl']);
    await assert.rejects(context.updateImageModelOptions(select, 'krea-noct-v4'), /unavailable/);
    await context.updateImageModelOptions(select, 'mflux-osaurus-qwen-image-2.1-edit', 'image_edit');
    assert.deepEqual(select.children.map(item => item.value), ['auto', 'juggernaut-xl',
        'mflux-osaurus-qwen-image-2.1-edit', 'mflux-qwen-image-edit-2511']);
    assert.equal(select.value, 'mflux-osaurus-qwen-image-2.1-edit');
    await context.updateImageModelOptions(select, 'mflux-qwen-image-edit-2511', 'image_edit');
    assert.equal(select.value, 'mflux-qwen-image-edit-2511');
});
