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
const de = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/image-count-picker.de.json', import.meta.url),
    'utf8',
));
const en = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/image-count-picker.en.json', import.meta.url),
    'utf8',
));

const window = {
    addEventListener() {},
    localStorage: {
        getItem(key) {
            return key === 'mlx-nobby-language' ? 'de' : null;
        },
    },
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
    Object,
    crypto: {
        randomUUID: () => 'generated-variant-group',
    },
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/image-count-picker.js',
});

const helpers = window.MLXImageCountPicker.__test;

assert.equal(helpers.normalizeImageCount(1), 1);
assert.equal(helpers.normalizeImageCount('2'), 2);
assert.equal(helpers.normalizeImageCount(3), 3);
assert.equal(helpers.normalizeImageCount('4'), 4);
assert.equal(helpers.normalizeImageCount(5), 5);
assert.equal(helpers.normalizeImageCount('6'), 6);
assert.equal(helpers.normalizeImageCount(0), 1);
assert.equal(helpers.normalizeImageCount(7), 6);
assert.equal(helpers.normalizeImageCount('invalid'), 1);
assert.equal(helpers.resolveLanguage(), 'de');
assert.equal(helpers.resolveLanguage('en-US'), 'en');
assert.equal(helpers.resolveLanguage('de-DE'), 'de');

assert.equal(de.count_label, 'Anzahl');
assert.deepEqual(
    [1, 2, 3, 4, 5, 6].map(index => de['count_' + index]),
    ['1 Bild', '2 Bilder', '3 Bilder', '4 Bilder', '5 Bilder', '6 Bilder'],
);
assert.deepEqual(Object.keys(de), Object.keys(en));

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
        image_regenerated_from_artifact_id: 'artifact-one',
        image_variant_group_id: 'variant-group',
        image_variant_index: 1,
        image_variant_count: 5,
        image_job: { status: 'queued' },
    },
    {
        role: 'assistant',
        image_regenerated_from_artifact_id: 'artifact-one',
        image_variant_group_id: 'variant-group',
        image_variant_index: 2,
        image_variant_count: 5,
        image_job: { status: 'queued' },
    },
    {
        role: 'assistant',
        image_regenerated_from_artifact_id: 'artifact-one',
        image_variant_group_id: 'variant-group',
        image_variant_index: 3,
        image_variant_count: 5,
        image_job: { status: 'queued' },
    },
    {
        role: 'assistant',
        image_regenerated_from_artifact_id: 'artifact-one',
        image_variant_group_id: 'variant-group',
        image_variant_index: 4,
        image_variant_count: 5,
        image_job: { status: 'queued' },
    },
    {
        role: 'assistant',
        image_regenerated_from_artifact_id: 'artifact-one',
        image_variant_group_id: 'variant-group',
        image_variant_index: 5,
        image_variant_count: 5,
        image_job: { status: 'queued' },
    },
];

assert.equal(helpers.isInitialImageMessage(first), true);
assert.equal(helpers.artifactForMessage(first).image_id, 'image-one');

const session = {
    messages: [
        { role: 'user', content: 'create an image' },
        first,
    ],
};
assert.strictEqual(helpers.firstImageMessageAfter(session, 1), first);
assert.equal(helpers.terminalStatus(first), 'completed');

assert.equal(
    helpers.mergeInitialImageWithGeneratedVariants(first, extras, 6),
    'variant-group',
);
assert.equal(first.image_variant_group_id, 'variant-group');
assert.equal(first.image_variant_index, 1);
assert.equal(first.image_variant_count, 6);
assert.deepEqual(
    JSON.parse(JSON.stringify(extras.map(message => ({
        group: message.image_variant_group_id,
        index: message.image_variant_index,
        count: message.image_variant_count,
    })))),
    [
        { group: 'variant-group', index: 2, count: 6 },
        { group: 'variant-group', index: 3, count: 6 },
        { group: 'variant-group', index: 4, count: 6 },
        { group: 'variant-group', index: 5, count: 6 },
        { group: 'variant-group', index: 6, count: 6 },
    ],
);

const firstForPair = {
    role: 'assistant',
    tool_result: {
        tool: 'image_generate',
        status: 'completed',
        artifacts: [{ image_id: 'pair-first', artifact_id: 'pair-artifact' }],
    },
};
const pairExtra = {
    role: 'assistant',
    image_regenerated_from_artifact_id: 'pair-artifact',
    image_job: { status: 'queued' },
};
assert.equal(
    helpers.mergeInitialImageWithGeneratedVariants(
        firstForPair,
        [pairExtra],
        2,
    ),
    'generated-variant-group',
);
assert.equal(firstForPair.image_variant_index, 1);
assert.equal(firstForPair.image_variant_count, 2);
assert.equal(pairExtra.image_variant_index, 2);
assert.equal(pairExtra.image_variant_count, 2);
assert.equal(pairExtra.image_variant_group_id, 'generated-variant-group');
assert.strictEqual(
    helpers.regeneratedMessageForArtifact([pairExtra], {
        artifact_id: 'pair-artifact',
    }),
    pairExtra,
);

const grouped = {
    ...first,
    image_variant_group_id: 'already-grouped',
};
assert.equal(helpers.isInitialImageMessage(grouped), false);

const sourceArtifact = {
    artifact_id: 'batch-artifact',
    image_id: 'batch-image',
    prompt: 'A cinematic portrait',
    width: 512,
    height: 512,
    quality: 'standard',
    negative_prompt: 'old negative prompt',
};
const batchArtifact = helpers.applyImageBatchSettings(sourceArtifact, {
    format: 'landscape',
    width: 768,
    height: 432,
    quality: 'quality',
    negativePrompt: 'deformed face, malformed hands, extra fingers',
});
assert.equal(batchArtifact.width, 768);
assert.equal(batchArtifact.height, 432);
assert.equal(batchArtifact.quality, 'quality');
assert.equal(
    batchArtifact.negative_prompt,
    'deformed face, malformed hands, extra fingers',
);
assert.equal(sourceArtifact.width, 512);
assert.equal(sourceArtifact.height, 512);
assert.equal(sourceArtifact.quality, 'standard');
assert.equal(sourceArtifact.negative_prompt, 'old negative prompt');

const clearedNegativePrompt = helpers.applyImageBatchSettings(sourceArtifact, {
    width: 432,
    height: 768,
    quality: 'fast',
    negativePrompt: '',
});
assert.equal(clearedNegativePrompt.width, 432);
assert.equal(clearedNegativePrompt.height, 768);
assert.equal(clearedNegativePrompt.quality, 'fast');
assert.equal(Object.hasOwn(clearedNegativePrompt, 'negative_prompt'), false);

assert.match(commonSource, /image-count-picker\.js\?v=20260929-image-count-v2/);
assert.match(source, /20260930-image-count-v3/);
assert.match(source, /settings: selectedImageBatchSettings\(\)/);
assert.match(source, /applyImageBatchSettings\(artifact, batchSettings\)/);
assert.match(source, /mlx-i18n-ready/);
assert.match(source, /mlx-language-changed/);

console.log('Image count picker, batch settings, localization, and 1-6 grouping passed.');
