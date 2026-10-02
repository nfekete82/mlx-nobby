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
assert.equal(groups.length, 2);
assert.equal(groups[1].id, 'group-b');
assert.equal(groups[0].id, 'group-a');
assert.equal(groups[0].count, 3);
assert.equal(groups[0].firstIndex, 1);
assert.deepEqual(
    JSON.parse(JSON.stringify(
        groups[0].items.map(item => item.message.image_variant_index),
    )),
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

assert.equal(helpers.statusText({image_job: {status: 'running', semantic_operation: 'reference_generate'}}),
    'Creating an image using the reference …');
assert.equal(helpers.artifactForMessage({tool_result: {tool: 'image_edit', artifacts: [{
    image_id: 'reference-output', semantic_operation: 'reference_generate', reference_used: true
}]}}).reference_used, true);

class Element {
    constructor(tag) {this.tagName = tag; this.children = []; this.dataset = {}; this.style = {};
        this.listeners = {}; this.isConnected = true; this.classList = {add() {}, contains() {return false;}};}
    appendChild(child) {this.children.push(child); return child;}
    append(...children) {this.children.push(...children);}
    addEventListener(name, callback) {this.listeners[name] = callback;}
    setAttribute() {}
}
context.document.createElement = tag => new Element(tag);
const actions = [];
window.MLXImageRegenerate = {
    variantSourceAvailable: artifact => /^[a-f0-9]{24}$/.test(artifact.generation_job_id || ''),
    retryImageVariants: async id => actions.push(['retry', id]),
    cancelImageVariants: async id => actions.push(['cancel', id]),
    generateImageVariants: async () => true,
};
function buttons(element) {
    return [...(element.tagName === 'button' ? [element] : []), ...element.children.flatMap(buttons)];
}
const groupId = '1'.repeat(24);
const completed = {role: 'assistant', image_variant_group_id: groupId, image_variant_index: 1, image_variant_count: 3,
    image_variant_base_job_id: 'a'.repeat(24), image_job: {status: 'completed'},
    tool_result: {tool: 'image_edit', status: 'completed', artifacts: [{image_id: 'ref', artifact_id: 'ref',
        generation_job_id: 'a'.repeat(24), semantic_operation: 'reference_generate', reference_used: true}]}};
const failed = {...completed, image_variant_index: 2, tool_result: null, image_job: {status: 'failed'}};
const gallerySession = {workspace: {}, messages: [completed, failed]};
const group = helpers.groupVariantMessages(gallerySession)[0];
let controls = buttons(helpers.buildGalleryArticle(group, gallerySession));
const retry = controls.find(button => button.textContent === 'Retry missing variants');
assert.ok(retry && !retry.disabled);
await retry.listeners.click();
assert.deepEqual(actions.at(-1), ['retry', groupId]);
failed.image_job.status = 'running';
controls = buttons(helpers.buildGalleryArticle(group, gallerySession));
const cancel = controls.find(button => button.textContent === 'Cancel variants');
assert.ok(cancel);
assert.equal(controls.some(button => button.textContent === 'Retry missing variants'), false);
assert.equal(controls.find(button => button.textContent === 'Create 3 more').disabled, true);
await cancel.listeners.click();
assert.deepEqual(actions.at(-1), ['cancel', groupId]);
failed.image_job.status = 'cancelled';
delete completed.tool_result.artifacts[0].generation_job_id;
controls = buttons(helpers.buildGalleryArticle(group, gallerySession));
const more = controls.find(button => button.textContent === 'Create 3 more');
assert.equal(more.disabled, true);
assert.match(more.title, /Variants are unavailable/);
for (const language of ['de', 'en']) {
    const dictionary = JSON.parse(fs.readFileSync(new URL('../frontend/i18n/image-variant-gallery.' + language + '.json', import.meta.url), 'utf8'));
    assert.ok(dictionary.cancel && dictionary.retry && dictionary.unavailable);
}
