import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/image-count-picker.js', import.meta.url),
    'utf8',
);
const commonSource = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8',
);

const window = {
    addEventListener() {},
};
window.window = window;

const document = {
    readyState: 'complete',
    documentElement: { lang: 'en' },
};

const context = {
    console,
    window,
    document,
    fetch: async () => ({ ok: false }),
    MutationObserver: undefined,
    setTimeout,
    clearTimeout,
    Date,
    Math,
    Map,
    Array,
    Number,
    String,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/image-count-picker.js',
});

const helpers = window.MLXImageCountPicker.__test;

assert.equal(helpers.normalizeImageCount(1), 1);
assert.equal(helpers.normalizeImageCount('3'), 3);
assert.equal(helpers.normalizeImageCount(2), 1);
assert.equal(helpers.normalizeImageCount('invalid'), 1);

const first = {
    role: 'assistant',
    tool_result: {
        tool: 'image_generate',
        status: 'completed',
        artifacts: [{
            image_id: 'image-one',
            artifact_id: 'artifact-one',
        }],
    },
};
const extras = [
    {
        role: 'assistant',
        image_variant_group_id: 'variant-group',
        image_variant_index: 1,
        image_variant_count: 2,
        image_job: { status: 'queued' },
    },
    {
        role: 'assistant',
        image_variant_group_id: 'variant-group',
        image_variant_index: 2,
        image_variant_count: 2,
        image_job: { status: 'queued' },
    },
];

assert.equal(helpers.isInitialImageMessage(first), true);
assert.equal(helpers.artifactForMessage(first).image_id, 'image-one');
assert.equal(
    helpers.mergeInitialImageWithGeneratedVariants(first, extras, 3),
    'variant-group',
);
assert.equal(first.image_variant_group_id, 'variant-group');
assert.equal(first.image_variant_index, 1);
assert.equal(first.image_variant_count, 3);
assert.deepEqual(
    JSON.parse(JSON.stringify(extras.map(message => ({
        group: message.image_variant_group_id,
        index: message.image_variant_index,
        count: message.image_variant_count,
    })))),
    [
        { group: 'variant-group', index: 2, count: 3 },
        { group: 'variant-group', index: 3, count: 3 },
    ],
);

const session = {
    messages: [
        { role: 'user', content: 'create an image' },
        first,
    ],
};
assert.strictEqual(helpers.firstImageMessageAfter(session, 1), first);
assert.equal(helpers.terminalStatus(first), 'completed');

const grouped = {
    ...first,
    image_variant_group_id: 'already-grouped',
};
assert.equal(helpers.isInitialImageMessage(grouped), false);

assert.match(commonSource, /image-count-picker\.js\?v=20260929-image-count-v1/);
assert.match(commonSource, /loadImageCountPicker\(\);/);

console.log('Image count picker and initial three-variant grouping passed.');
