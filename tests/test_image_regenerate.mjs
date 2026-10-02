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
assert.equal(requests.length, 4);
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

for (const request of requests.slice(1)) {
    const variantPayload = JSON.parse(request.options.body);
    assert.equal(variantPayload.prompt, artifact.prompt);
    assert.equal(variantPayload.action, 'image_generate');
    assert.equal(variantPayload.resolved_target, 'image');
    assert.equal(variantPayload.quality, 'quality');
    assert.equal(variantPayload.chat_id, session.id);
    assert.equal(variantPayload.chat_revision, 12);
    assert.deepEqual(
        JSON.parse(JSON.stringify(variantPayload.image_options)),
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
    assert.equal(Object.hasOwn(variantPayload.image_options, 'seed'), false);
}

assert.equal(resumeCalls, 2);
assert.ok(saveCalls >= 4);
assert.ok(renderCalls >= 4);

console.log('Image regenerate and three-variant actions passed.');


const referenceArtifact = {
    ...artifact,
    semantic_operation: 'reference_generate', reference_used: true,
    reference_mode: 'same_identity', reference_artifact_id: 'uploaded-reference',
    source_path: '/local/uploads/reference.png', original_prompt: 'Create the same person in an office.'
};
const referencePrepared = window.MLXImageRegenerate.regenerationOptions(referenceArtifact);
assert.equal(referencePrepared.referenceMode, 'same_identity');
assert.equal(referencePrepared.referenceContext.stored_path, referenceArtifact.source_path);
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
    assert.equal(body.file_context.stored_path, referenceArtifact.source_path);
    assert.equal(body.resolved_target, 'image_edit');
    assert.equal(Object.hasOwn(body.image_options, 'seed'), false);
    return {ok: true, async json() {return {tool: 'image_edit', status: 'queued',
        data: {job: {id: 'a'.repeat(24), operation: 'edit', status: 'queued', semantic_operation: 'reference_generate'}}};}};
};
assert.equal(await window.MLXImageRegenerate.regenerateImageArtifact(referenceArtifact), true);
assert.equal(requests.length, priorRequestCount + 1);
const referenceControls = window.MLXChatGeneration.createImageUpscaleMenu(referenceArtifact);
assert.equal(referenceControls.children[0].textContent, 'Neu generieren');
