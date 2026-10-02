import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/image-settings.js', import.meta.url),
    'utf8',
);

class TestElement {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.listeners = new Map();
        this.textContent = '';
        this.title = '';
        this.className = '';
        this.disabled = false;
        this.isConnected = true;
        this.type = '';
    }

    append(...children) {
        this.children.push(...children);
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    addEventListener(type, listener) {
        this.listeners.set(type, listener);
    }

    async click() {
        return await this.listeners.get('click')?.({ currentTarget: this });
    }
}

const requests = [];
let resumeCalls = 0;
let saveCalls = 0;
let renderCalls = 0;

const session = {
    id: 'image-regenerate-chat',
    revision: 12,
    updated: 0,
    messages: [],
    workspace: {},
};

const window = {
    MLXI18n: {
        t(key, fallback, variables = {}) {
            let value = key === 'ui.regenerate'
                ? 'Neu generieren'
                : fallback;
            for (const [name, replacement] of Object.entries(variables)) {
                value = value.replaceAll(`{${name}}`, String(replacement));
            }
            return value;
        },
    },
    MLXChatGeneration: {
        createImageUpscaleMenu(sourceArtifact) {
            const menu = new TestElement('details');
            menu.className = 'image-upscale-menu';
            menu.sourceArtifact = sourceArtifact;
            return menu;
        },
        updateImageJobMessage(_session, message, result) {
            message.image_job = result.data.job;
            message.tool_result = result;
            message.image_generation_pending = false;
        },
        resumeImageJobsForSession(targetSession) {
            assert.strictEqual(targetSession, session);
            resumeCalls += 1;
            return 1;
        },
    },
    MLXChatSessions: {
        currentSession: () => session,
        saveSessions() {
            saveCalls += 1;
        },
    },
    MLXChatRendering: {
        renderAll() {
            renderCalls += 1;
        },
    },
};
window.window = window;

const document = {
    getElementById() {
        // The settings-manager IIFE exits immediately; this test focuses on
        // the independent artifact regeneration extension below it.
        return null;
    },
    createElement(tag) {
        return new TestElement(tag);
    },
    createDocumentFragment() {
        return new TestElement('#fragment');
    },
};

const context = {
    console,
    document,
    window,
    globalThis: {
        crypto: {
            randomUUID: () => 'regenerate-trace-id',
        },
    },
    crypto: {
        randomUUID: () => 'regenerate-trace-id',
    },
    Math,
    Date,
    encodeURIComponent,
    fetch: async (url, options = {}) => {
        requests.push({ url, options });

        if (url === '/api/mlx/image-jobs/variants') {
            const payload = JSON.parse(options.body);
            const includeBase = payload.include_base;
            return { ok: true, async json() {
                return {
                    variant_group_id: payload.variant_group_id || (includeBase ? 'gallery-group' : 'server-group'),
                    variant_count: payload.count,
                    base: { tool: 'image_generate', status: 'completed', data: { job: { id: artifact.generation_job_id, status: 'completed' } }, artifacts: [artifact] },
                    jobs: Array.from({ length: payload.count - (includeBase ? 1 : 0) }, (_, index) => ({
                        tool: 'image_generate', status: 'queued', artifacts: [],
                        data: { job: { id: String.fromCharCode(98 + index).repeat(24), operation: 'generate', status: 'queued',
                            variant_group_id: payload.variant_group_id || (includeBase ? 'gallery-group' : 'server-group'),
                            variant_index: index + (includeBase ? 2 : 1), variant_count: payload.count } }
                    }))
                };
            } };
        }
        assert.equal(url, '/api/mlx/chat/actions');
        assert.equal(options.method, 'POST');

        const jobCharacter = ['a', 'b', 'c', 'd', 'e', 'f'][
            requests.length - 1
        ] || 'f';

        return {
            ok: true,
            async json() {
                return {
                    type: 'tool_result',
                    tool: 'image_generate',
                    status: 'queued',
                    data: {
                        job: {
                            id: jobCharacter.repeat(24),
                            operation: 'generate',
                            status: 'queued',
                            phase: 'queued',
                            progress: 0,
                        },
                    },
                    artifacts: [],
                    error: null,
                };
            },
        };
    },
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/image-settings.js',
});

const artifact = {
    artifact_id: 'image-1234567890-abcdef123456',
    image_id: '1234567890-abcdef123456',
    generation_job_id: 'e'.repeat(24),
    prompt: 'Photorealistic portrait of a woman',
    model: 'juggernaut-xl',
    provider: 'sdxl',
    width: 1216,
    height: 1216,
    quality: 'quality',
    steps: 35,
    guidance: 5.5,
    seed: 1852130570,
};

const prepared = window.MLXImageRegenerate.regenerationOptions(artifact);
assert.equal(prepared.prompt, artifact.prompt);
assert.equal(prepared.quality, 'quality');
assert.equal(prepared.imageOptions.prompt, artifact.prompt);
assert.equal(prepared.imageOptions.model, 'juggernaut-xl');
assert.equal(prepared.imageOptions.width, 1216);
assert.equal(prepared.imageOptions.height, 1216);
assert.equal(prepared.imageOptions.steps, 35);
assert.equal(prepared.imageOptions.guidance, 5.5);
assert.equal(prepared.imageOptions.auto_size, false);
assert.equal(Object.hasOwn(prepared.imageOptions, 'seed'), false);

const controls = window.MLXChatGeneration.createImageUpscaleMenu(artifact);
assert.equal(controls.children.length, 3);
assert.equal(controls.children[0].tagName, 'BUTTON');
assert.equal(controls.children[0].textContent, 'Neu generieren');
assert.equal(controls.children[0].className, 'message-action-btn');
assert.equal(controls.children[1].tagName, 'BUTTON');
assert.equal(controls.children[1].textContent, '3× Neu generieren');
assert.equal(controls.children[1].className, 'message-action-btn');
assert.equal(controls.children[2].className, 'image-upscale-menu');

const editControls = window.MLXChatGeneration.createImageUpscaleMenu({
    ...artifact,
    source_path: '/tmp/source.png',
});
assert.equal(editControls.className, 'image-upscale-menu');
assert.equal(editControls.children.length, 0);

const started = await window.MLXImageRegenerate.regenerateImageArtifact(artifact);
assert.equal(started, true);
assert.equal(requests.length, 1);

const payload = JSON.parse(requests[0].options.body);
assert.equal(payload.prompt, artifact.prompt);
assert.equal(payload.action, 'image_generate');
assert.equal(payload.resolved_target, 'image');
assert.equal(payload.quality, 'quality');
assert.equal(payload.chat_id, session.id);
assert.equal(payload.chat_revision, 12);
assert.equal(payload.trace_id, 'regenerate-trace-id');
assert.deepEqual(
    JSON.parse(JSON.stringify(payload.image_options)),
    {
        prompt: artifact.prompt,
        model: 'juggernaut-xl',
        auto_size: false,
        width: 1216,
        height: 1216,
        steps: 35,
        guidance: 5.5,
    },
);
assert.equal(Object.hasOwn(payload.image_options, 'seed'), false);
assert.equal(session.messages.length, 1);
assert.equal(session.messages[0].image_job.status, 'queued');
assert.equal(session.messages[0].tool_result.tool, 'image_generate');

const variantsStarted = await window.MLXImageRegenerate.generateImageVariants(
    artifact,
    3,
);
assert.equal(variantsStarted, true);
assert.equal(requests.length, 2);
assert.equal(session.messages.length, 4);

const variantMessages = session.messages.slice(1);
assert.deepEqual(
    variantMessages.map(message => message.image_variant_index),
    [1, 2, 3],
);
assert.deepEqual(
    variantMessages.map(message => message.image_variant_count),
    [3, 3, 3],
);
assert.equal(
    new Set(variantMessages.map(message => message.image_variant_group_id)).size,
    1,
);
assert.ok(variantMessages.every(message => message.image_job.status === 'queued'));
assert.deepEqual(
    variantMessages.map(message => message.image_job.id),
    ['b'.repeat(24), 'c'.repeat(24), 'd'.repeat(24)],
);

const variantRequest = requests[1];
assert.equal(variantRequest.url, '/api/mlx/image-jobs/variants');
assert.deepEqual(JSON.parse(variantRequest.options.body), {
    base_job_id: artifact.generation_job_id,
    count: 3,
    include_base: false,
    chat_id: session.id,
    chat_revision: 12,
    variant_group_id: null,
});
assert.ok(variantMessages.every(message => !message.image_regenerated_from_artifact_id));
assert.equal(await window.MLXImageRegenerate.retryImageVariants('server-group'), true);
assert.equal(session.messages.length, 4, 'Retry updates existing slots');
assert.equal(JSON.parse(requests[2].options.body).variant_group_id, 'server-group');

const galleryFirst = { role: 'assistant', tool_result: { artifacts: [artifact] } };
session.messages.push(galleryFirst);
const additional = await window.MLXImageRegenerate.submitVariantBatch(artifact, 6, {
    includeBase: true, firstMessage: galleryFirst
});
assert.equal(additional.length, 5);
assert.equal(galleryFirst.image_variant_index, 1);
assert.equal(galleryFirst.image_variant_count, 6);
assert.equal(galleryFirst.image_variant_group_id, 'gallery-group');
assert.deepEqual(additional.map(message => message.image_variant_index), [2, 3, 4, 5, 6]);
assert.equal(JSON.parse(requests[3].options.body).include_base, true);
assert.equal(Object.hasOwn(JSON.parse(requests[3].options.body), 'image_options'), false);
assert.equal(resumeCalls, 4);
assert.ok(saveCalls >= 4);
assert.ok(renderCalls >= 4);

console.log('Image regenerate and three-variant actions passed.');


const referenceArtifact = {
    ...artifact,
    semantic_operation: 'reference_generate', reference_used: true,
    reference_mode: 'same_identity', reference_artifact_id: 'uploaded-reference',
    reference_source_job_id: 'f'.repeat(24), original_prompt: 'Create the same person in an office.'
};
const referencePrepared = window.MLXImageRegenerate.regenerationOptions(referenceArtifact);
assert.equal(referencePrepared.referenceMode, 'same_identity');
assert.equal(Object.hasOwn(referencePrepared.referenceContext, 'stored_path'), false);
assert.equal(window.MLXImageRegenerate.regenerationOptions({...referenceArtifact,
    reference_source_job_id: undefined}).referenceContext.reference_source_job_id, artifact.generation_job_id);
assert.equal(window.MLXImageRegenerate.regenerationOptions({...referenceArtifact,
    reference_source_job_id: undefined, generation_job_id: undefined, source_path: '/private/reference.png'}), null);
assert.equal(referencePrepared.referenceContext.reference_source_job_id, referenceArtifact.reference_source_job_id);
assert.equal(referencePrepared.referenceContext.reference_artifact_id, 'uploaded-reference');
assert.equal(referencePrepared.imageOptions.model, artifact.model);
assert.equal(Object.hasOwn(referencePrepared.imageOptions, 'seed'), false);
const priorRequestCount = requests.length;
context.fetch = async (url, options) => {
    requests.push({url, options});
    assert.equal(url, '/api/mlx/chat/actions');
    const body = JSON.parse(options.body);
    assert.equal(body.action, 'image_reference_generate');
    assert.equal(body.reference_mode, 'same_identity');
    assert.equal(Object.hasOwn(body.file_context, 'stored_path'), false);
    assert.equal(body.file_context.reference_source_job_id, referenceArtifact.reference_source_job_id);
    assert.equal(body.resolved_target, 'image_edit');
    assert.equal(Object.hasOwn(body.image_options, 'seed'), false);
    return {ok: true, async json() {return {tool: 'image_edit', status: 'queued',
        data: {job: {id: 'a'.repeat(24), operation: 'edit', status: 'queued', semantic_operation: 'reference_generate'}}};}};
};
assert.equal(await window.MLXImageRegenerate.regenerateImageArtifact(referenceArtifact), true);
assert.equal(requests.length, priorRequestCount + 1);
const referenceControls = window.MLXChatGeneration.createImageUpscaleMenu(referenceArtifact);
assert.equal(referenceControls.children[0].textContent, 'Neu generieren');

// Legacy artifacts fail visibly and never invent a native job identifier.
const api = window.MLXImageRegenerate;
const legacy = {...artifact};
delete legacy.generation_job_id;
assert.equal(window.MLXChatGeneration.createImageUpscaleMenu(legacy).children[1].disabled, true);
assert.equal(api.variantSourceAvailable({...artifact, generation_job_id: 'not-a-job'}), false);
const legacyBefore = requests.length;
assert.equal(await api.generateImageVariants(legacy), false);
assert.equal(requests.length, legacyBefore);
assert.match(session.messages.at(-1).content, /Variants are unavailable/);

const groupId = '1'.repeat(24);
function batch(group = groupId, status = 'queued', reference = false) {
    return {variant_group_id: group, variant_count: 3,
        base: {tool: 'image_generate', status: 'completed', artifacts: [artifact],
            data: {job: {id: artifact.generation_job_id, status: 'completed'}}},
        jobs: [1, 2, 3].map((index) => ({tool: reference ? 'image_edit' : 'image_generate',
            status, artifacts: [], data: {job: {id: String(index).repeat(24), status,
                operation: reference ? 'edit' : 'generate', semantic_operation: reference ? 'reference_generate' : undefined,
                reference_mode: reference ? 'same_identity' : undefined,
                variant_group_id: group, variant_index: index, variant_count: 3}}}))};
}
function ok(value) { return {ok: true, json: async () => value}; }
let outgoing = [];
context.fetch = async (url, options) => {outgoing.push({url, options}); return ok(batch(groupId, 'queued', true));};
assert.equal(await api.generateImageVariants(referenceArtifact), true);
assert.equal(outgoing.length, 1);
assert.equal(outgoing[0].url, '/api/mlx/image-jobs/variants');
assert.equal(JSON.parse(outgoing[0].options.body).base_job_id, artifact.generation_job_id);
assert.equal(Object.hasOwn(JSON.parse(outgoing[0].options.body), 'image_options'), false);
const slots = session.messages.filter(m => m.image_variant_group_id === groupId);
assert.ok(slots.every(m => m.image_job.operation === 'edit' && m.image_job.reference_mode === 'same_identity'));

// Retry and cancellation update existing slots and preserve completed outputs.
const completedResult = {...batch().jobs[0], status: 'completed', artifacts: [referenceArtifact],
    data: {job: {...batch().jobs[0].data.job, status: 'completed'}}};
window.MLXChatGeneration.updateImageJobMessage(session, slots[0], completedResult);
const beforeRetry = session.messages.length;
let completeBatch = batch(groupId, 'queued', true);
completeBatch.jobs[0] = completedResult;
context.fetch = async () => ok(completeBatch);
assert.equal(await api.retryImageVariants(groupId), true);
assert.equal(session.messages.length, beforeRetry);
assert.strictEqual(slots[0].tool_result.artifacts[0], referenceArtifact);
assert.equal(await api.cancelImageVariants(groupId), true);
assert.equal(slots[0].image_job.status, 'completed');
assert.ok(slots.slice(1).every(m => m.image_job.status === 'cancelled'));

// A cancellation supersedes a pending retry response.
let resolveRetry;
context.fetch = (url) => url.endsWith('variants')
    ? new Promise(resolve => {resolveRetry = resolve;}) : Promise.resolve(ok(completeBatch));
const staleRetry = api.retryImageVariants(groupId);
assert.equal(await api.cancelImageVariants(groupId), true);
resolveRetry(ok(batch(groupId, 'running')));
assert.equal(await staleRetry, false);
assert.ok(slots.slice(1).every(m => m.image_job.status === 'cancelled'));

// A newer request wins; stale new groups are cancelled through the group endpoint.
const delayed = [];
const cancelled = [];
context.fetch = (url, options) => {
    if (url.endsWith('variants')) return new Promise(resolve => delayed.push(resolve));
    cancelled.push(url); return Promise.resolve(ok({}));
};
const old = api.submitVariantBatch(artifact, 3);
const newer = api.submitVariantBatch(artifact, 3);
session.workspace.active_artifact_id = 'explicit-new-selection';
delayed[1](ok(batch('3'.repeat(24))));
assert.ok(await newer);
delayed[0](ok(batch('2'.repeat(24))));
assert.equal(await old, null);
assert.equal(session.workspace.active_artifact_id, 'explicit-new-selection');
assert.equal(session.messages.some(m => m.image_variant_group_id === '2'.repeat(24)), false);
assert.ok(cancelled[0].includes('/' + '2'.repeat(24) + '/cancel?'));

// Chat/revision changes and obsolete count-picker requests cannot apply responses.
for (const change of ['chat', 'revision', 'count']) {
    let resolve;
    context.fetch = (url) => url.endsWith('variants') ? new Promise(r => {resolve = r;}) : Promise.resolve(ok({}));
    let current = true;
    const pending = api.submitVariantBatch(artifact, 6, {isCurrent: () => current});
    if (change === 'chat') window.MLXChatSessions.currentSession = () => ({id: 'different-chat'});
    if (change === 'revision') session.revision += 1;
    if (change === 'count') current = false;
    const before = session.messages.length;
    resolve(ok(batch('4'.repeat(24))));
    assert.equal(await pending, null);
    assert.equal(session.messages.length, before);
    window.MLXChatSessions.currentSession = () => session;
}
for (const language of ['de', 'en']) {
    const translations = JSON.parse(fs.readFileSync(new URL('../frontend/i18n/' + language + '.json', import.meta.url), 'utf8'));
    assert.ok(translations.generation.image_variants_unavailable);
    assert.ok(translations.generation.image_variants_failed);
}

// Restore server-side validity before offering selective retry for missing PNGs.
const invalidBatch = batch(groupId, 'failed', true);
invalidBatch.jobs[0] = completedResult;
let refreshUrl;
context.fetch = async url => {refreshUrl = url; return ok(invalidBatch);};
assert.equal(await api.refreshImageVariants(groupId), true);
assert.ok(refreshUrl.includes('/image-variant-groups/' + groupId + '?chat_id='));
assert.strictEqual(slots[0].tool_result.artifacts[0], referenceArtifact);
assert.equal(slots[1].image_job.status, 'failed');

// An old group status cannot undo a later cancellation.
let resolveRefresh;
context.fetch = url => url.includes('/cancel?') ? Promise.resolve(ok(completeBatch))
    : new Promise(resolve => {resolveRefresh = resolve;});
const refresh = api.refreshImageVariants(groupId);
assert.equal(await api.cancelImageVariants(groupId), true);
resolveRefresh(ok(batch(groupId, 'running')));
assert.equal(await refresh, false);
assert.ok(slots.slice(1).every(m => m.image_job.status === 'cancelled'));
