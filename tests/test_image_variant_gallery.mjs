import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/image-variant-gallery.js', import.meta.url),
    'utf8',
);

const window = {
    MLXChatRendering: null,
};
window.window = window;

const context = {
    console,
    window,
    document: {},
    globalThis: {},
    MutationObserver: undefined,
    queueMicrotask,
    Date,
    Math,
    Set,
    Map,
    Array,
    Number,
    String,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/image-variant-gallery.js',
});

const helpers = window.MLXImageVariantGallery.__test;

const session = {
    messages: [
        { role: 'user', content: 'make a picture' },
        {
            role: 'assistant',
            image_variant_group_id: 'group-a',
            image_variant_index: 2,
            image_variant_count: 3,
            image_job: { status: 'running', current_step: 5, total_steps: 10 },
        },
        {
            role: 'assistant',
            image_variant_group_id: 'group-a',
            image_variant_index: 1,
            image_variant_count: 3,
            tool_result: {
                tool: 'image_generate',
                status: 'completed',
                artifacts: [{ image_id: 'img-1', artifact_id: 'artifact-1' }],
            },
        },
        {
            role: 'assistant',
            image_variant_group_id: 'group-a',
            image_variant_index: 3,
            image_variant_count: 3,
            image_job: { status: 'queued', progress: 0 },
        },
        {
            role: 'assistant',
            image_variant_group_id: 'group-b',
            image_variant_index: 1,
            image_variant_count: 3,
        },
    ],
};

const groups = helpers.groupVariantMessages(session);
assert.equal(groups.length, 1);
assert.equal(groups[0].id, 'group-a');
assert.equal(groups[0].count, 3);
assert.equal(groups[0].firstIndex, 1);
assert.deepEqual(
    groups[0].items.map(item => item.message.image_variant_index),
    [1, 2, 3],
);

const artifact = helpers.artifactForMessage(session.messages[2]);
assert.equal(artifact.image_id, 'img-1');
assert.equal(artifact.artifact_id, 'artifact-1');
assert.equal(helpers.artifactForMessage(session.messages[1]), null);

assert.equal(
    helpers.imageProgress({ status: 'running', current_step: 5, total_steps: 10 }),
    0.5,
);
assert.equal(
    helpers.imageProgress({ status: 'running', progress: 73 }),
    0.73,
);
assert.equal(
    helpers.imageProgress({ status: 'completed' }),
    1,
);

console.log('Image variant gallery grouping passed.');
