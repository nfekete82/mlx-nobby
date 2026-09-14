import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const attachmentSource = fs.readFileSync(
    new URL('../frontend/assets/chat/attachments.js', import.meta.url),
    'utf8',
);
const generationSource = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url),
    'utf8',
);
const renderingSource = fs.readFileSync(
    new URL('../frontend/assets/chat/rendering.js', import.meta.url),
    'utf8',
);
const requests = [];
const input = { value: '' };
const scheduledCallbacks = [];

class TestFormData {
    constructor() {
        this.values = [];
    }

    append(...values) {
        this.values.push(values);
    }
}

const window = {
    MLXI18n: {
        t(key, fallback, variables = {}) {
            if (key === 'image_edit_action') {
                return 'Bild ändern …';
            }
            let value = fallback;
            for (const [name, replacement] of Object.entries(variables)) {
                value = value.replaceAll(`{${name}}`, replacement);
            }
            return value;
        },
    },
};
window.window = window;

class TestFileReader {
    readAsDataURL(blob) {
        Promise.resolve(
            blob.arrayBuffer()
        ).then(buffer => {
            const base64 =
                Buffer.from(buffer).toString('base64');

            this.result =
                'data:' +
                (blob.type || 'application/octet-stream') +
                ';base64,' +
                base64;

            this.onload?.();
        }).catch(error => {
            this.error = error;
            this.onerror?.();
        });
    }
}

const context = {
    console,
    crypto: { randomUUID: () => 'attachment-id' },
    FileReader: TestFileReader,
    Blob,
    Buffer,
    performance,
    AbortController,
    TextEncoder,
    TextDecoder,
    document: {
        addEventListener() {},
        getElementById(id) {
            return id === 'input' ? input : {};
        },
    },
    fetch: async (url, options) => {
        requests.push({ url, options });
        return {
            ok: true,
            async json() {
                return {
                    path: '/uploads/stored.png',
                    stored_name: 'stored.png',
                };
            },
        };
    },
    FormData: TestFormData,
    setTimeout(callback) {
        scheduledCallbacks.push(callback);
        return scheduledCallbacks.length;
    },
    clearTimeout(timerId) {
        const index = Number(timerId) - 1;
        if (index >= 0 && index < scheduledCallbacks.length) {
            scheduledCallbacks[index] = null;
        }
    },
    window,
};

vm.runInNewContext(attachmentSource, context, {
    filename: 'frontend/assets/chat/attachments.js',
});
vm.runInNewContext(generationSource, context, {
    filename: 'frontend/assets/chat/generation.js',
});

const imageFile = { name: 'portrait.png' };
const imageAttachment = {
    kind: 'image',
    name: 'portrait.png',
    file: imageFile,
};
const ignoredTextAttachment = {
    kind: 'text',
    name: 'notes.txt',
    file: { name: 'notes.txt' },
};
const uploaded = await window.MLXChatAttachments.uploadImageAttachments([
    ignoredTextAttachment,
    imageAttachment,
]);

assert.equal(requests.length, 1);
assert.equal(requests[0].url, '/api/mlx/batch/upload');
assert.equal(requests[0].options.method, 'POST');
assert.deepEqual(
    requests[0].options.body.values[0],
    ['file', imageFile, 'portrait.png'],
);
assert.equal(uploaded[0].attachment, imageAttachment);
assert.equal(uploaded[0].upload.path, '/uploads/stored.png');

const imageEditError = window.MLXChatGeneration.__test.toolFailureSummary({
    tool: 'image_edit',
    status: 'failed',
    error: 'Image-Auftrag hat das Zeitlimit überschritten',
});
assert.match(imageEditError, /Zeitlimit überschritten/);

const imageUpscaleError = window.MLXChatGeneration.__test.toolFailureSummary({
    tool: 'image_upscale',
    status: 'failed',
    error: 'Real-ESRGAN provider failed',
});
assert.match(imageUpscaleError, /Real-ESRGAN provider failed/);
assert.equal(
    window.MLXChatGeneration.__test.toolSummary({
        tool: 'image_upscale',
        status: 'completed',
        artifacts: [],
    }),
    'Image enhanced locally with Real-ESRGAN.',
);
assert.equal(
    window.MLXChatGeneration.__test.isImageJobTool('image_upscale'),
    true,
);
assert.deepEqual(
    Array.from(
        window.MLXChatGeneration.__test.imageUpscalePresets(),
        item => item.preset,
    ),
    ['photo-2x', 'photo-4x', 'anime-4x'],
);

const unrelatedError = window.MLXChatGeneration.__test.toolFailureSummary({
    tool: 'system_status',
    status: 'failed',
    error: 'private detail',
});
assert.equal(unrelatedError, 'The action could not be completed.');

const routing = window.MLXChatGeneration.__test;
for (const prompt of [
    'ändere das Kleid in rot',
    'ändere das klein in rot',
    'mach das Kleid rot',
    'mach das rot',
    'mach den Hintergrund dunkler',
    'entferne die Person links',
    'mach mich etwas jünger',
    'ändere die Haarfarbe zu blond',
    'mach den Hintergrund unscharf',
    'ersetze den Himmel',
    'füge eine Sonnenbrille hinzu',
    'retuschiere das Gesicht',
    'change the dress to red',
    'make it red',
    'remove the person',
    'blur the background',
]) {
    assert.equal(
        routing.isImageEditRequest(prompt, true),
        true,
        prompt,
    );
}

for (const prompt of [
    'Was ist auf dem Bild?',
    'Beschreibe das Bild',
    'Welche Farbe hat das Kleid?',
    'Wie viele Personen sind zu sehen?',
    'Was hält die Person in der Hand?',
    'Ist das Bild scharf?',
]) {
    assert.equal(
        routing.isImageEditRequest(prompt, true),
        false,
        prompt,
    );
}

assert.equal(
    routing.isImageEditRequest('Ändere diese Datei', false),
    false,
);
assert.equal(
    routing.isImageGenerationRequest(
        'Erstelle ein Bild von einem roten Kleid',
    ),
    true,
);
assert.equal(
    routing.isImageGenerationRequest(
        'create an image of a red dress',
    ),
    true,
);

let generating = false;
let visionChecks = 0;
let selectedAttachments = [imageAttachment];
const session = {
    messages: [],
    workspace: {},
};
const imageArtifact = {
    artifact_id: 'image-1234567890-abcdef123456',
    image_id: '1234567890-abcdef123456',
    mime_type: 'image/png',
    model: 'mflux-qwen-image-edit-2511',
};

context.MLXChatAttachments = {
    ...window.MLXChatAttachments,
    getAttachments: () => selectedAttachments,
    buildAttachmentContext: () => '',
    clearAttachments() {},
};
context.MLXChatRuntime = {
    isSwitching: () => false,
    async ensureVisionSupport() {
        visionChecks += 1;
        return false;
    },
    getSessionGenerationSettings() {
        return {
            temperature: 0.7,
            max_tokens: 512,
        };
    },
    getSessionSystemPrompt() {
        return '';
    },
    updateSendButton() {},
    autoResize() {},
    beginUserMessage() {},
};
let activeSession = session;
context.MLXChatSessions = {
    currentSession: () => activeSession,

    runtimeRevision(targetSession) {
        const value = Number(
            targetSession?._runtime_revision
        );

        return (
            Number.isSafeInteger(value) &&
            value >= 0
        )
            ? value
            : 0;
    },

    bumpRuntimeRevision(targetSession) {
        if (!targetSession) {
            return 0;
        }

        const next =
            context.MLXChatSessions.runtimeRevision(
                targetSession
            ) + 1;

        Object.defineProperty(
            targetSession,
            '_runtime_revision',
            {
                value: next,
                writable: true,
                configurable: true,
                enumerable: false
            }
        );

        return next;
    },

    runtimeRevisionIsCurrent(
        targetSession,
        revision
    ) {
        return (
            targetSession === activeSession &&
            context.MLXChatSessions.runtimeRevision(
                targetSession
            ) === revision
        );
    },

    updateTitle() {},
    saveSessions() {},
};
context.MLXChatCompact = {
    async autoCompactIfNeeded() {},
};
context.MLXChatRendering = {
    renderAll() {},
    renderMessages() {},
};
context.alert = message => {
    throw new Error(`Unexpected alert: ${message}`);
};
let abortController = null;

window.MLXChatGeneration.configure({
    getGenerating: () => generating,
    setGenerating: value => {
        generating = value;
    },
    getAbortController: () => abortController,
    setAbortController: value => {
        abortController = value;
    },
});

requests.length = 0;
let imageJobPolls = 0;
context.fetch = async (url, options) => {
    requests.push({ url, options });

    if (url === '/api/mlx/batch/upload') {
        return {
            ok: true,
            async json() {
                return {
                    path: '/uploads/stored.png',
                    stored_name: 'stored.png',
                };
            },
        };
    }

    if (url.startsWith('/api/mlx/image-jobs/')) {
        imageJobPolls += 1;
        return {
            ok: true,
            async json() {
                if (imageJobPolls === 1) {
                    return {
                        tool: 'image_edit',
                        status: 'running',
                        data: {
                            job: {
                                id: 'a'.repeat(24),
                                operation: 'edit',
                                status: 'running',
                                current_step: 2,
                                total_steps: 8,
                                progress: 0.25,
                            },
                        },
                        artifacts: [],
                        error: null,
                    };
                }
                return {
                    tool: 'image_edit',
                    status: 'completed',
                    data: {
                        job: {
                            id: 'a'.repeat(24),
                            operation: 'edit',
                            status: 'completed',
                            current_step: 8,
                            total_steps: 8,
                            progress: 1,
                        },
                        image: imageArtifact,
                    },
                    artifacts: [imageArtifact],
                    error: null,
                };
            },
        };
    }

    assert.equal(url, '/api/mlx/chat/actions');
    return {
        ok: true,
        async json() {
            return {
                tool: 'image_edit',
                status: 'queued',
                data: {
                    job: {
                        id: 'a'.repeat(24),
                        operation: 'edit',
                        status: 'queued',
                        current_step: null,
                        total_steps: null,
                        progress: null,
                    },
                },
                artifacts: [],
                error: null,
            };
        },
    };
};
input.value = 'ändere das klein in die farbe rot';

await window.MLXChatGeneration.sendMessage();
await new Promise(resolve => setImmediate(resolve));

assert.equal(visionChecks, 0);
assert.deepEqual(
    requests.slice(0, 3).map(request => request.url),
    [
        '/api/mlx/batch/upload',
        '/api/mlx/chat/actions',
        '/api/mlx/image-jobs/' + 'a'.repeat(24),
    ],
);
const actionPayload = JSON.parse(requests[1].options.body);
assert.equal(actionPayload.file_context.kind, 'image');
assert.equal(actionPayload.file_context.stored_path, '/uploads/stored.png');
assert.equal(actionPayload.active_artifact_id, null);
assert.equal(actionPayload.image_options, null);
assert.equal(session.messages.at(-1).image_job.status, 'running');
assert.equal(session.messages.at(-1).image_job.current_step, 2);
assert.equal(session.messages.at(-1).tool_result.artifacts.length, 0);

assert.equal(scheduledCallbacks.length, 1);
await scheduledCallbacks.shift()();
await new Promise(resolve => setImmediate(resolve));

assert.equal(session.messages.at(-1).tool_result.tool, 'image_edit');
assert.equal(
    session.workspace.active_artifact_id,
    imageArtifact.artifact_id,
);

assert.equal(
    routing.activeSessionImageArtifact(session).artifact_id,
    imageArtifact.artifact_id,
);
assert.equal(
    routing.isImageEditRequest('Mach es noch dunkler.', true),
    true,
);
assert.equal(
    routing.isImageEditRequest('Und jetzt etwas wärmer.', true),
    true,
);
assert.equal(
    routing.isImageEditRequest('Mach es noch dunkler.', false),
    false,
);

for (const prompt of [
    'bitte ganzkörper',
    'ganzkörper',
    'mehr ganzkörper',
    'weiter raus',
    'noch realistischer',
    'full body',
    'zoom out',
]) {
    assert.equal(
        routing.isImageEditRequest(prompt, true),
        true,
        prompt,
    );
}

assert.equal(
    routing.isImageEditRequest('bitte ganzkörper', false),
    false,
);

assert.equal(
    routing.isImageEditRequest(
        'Was ist ein Ganzkörperfoto?',
        true,
    ),
    false,
);

// ----------------------------------------------------------------
// Image comparison intent must only activate when a parent image
// actually exists.
// ----------------------------------------------------------------

for (const prompt of [
    'Was wurde verändert?',
    'Was ist jetzt anders?',
    'Welche Unterschiede gibt es?',
    'Vergleiche vorher und nachher.',
    'What changed?',
    'What is different?',
    'Compare before and after.',
]) {
    assert.equal(
        routing.isImageComparisonRequest(prompt, true),
        true,
        prompt,
    );
}

for (const prompt of [
    'Was wurde verändert?',
    'Was ist jetzt anders?',
    'Vergleiche vorher und nachher.',
]) {
    assert.equal(
        routing.isImageComparisonRequest(prompt, false),
        false,
        `comparison without parent: ${prompt}`,
    );
}

assert.equal(
    routing.isImageComparisonRequest(
        'Was siehst du auf dem Bild?',
        true,
    ),
    false,
);

assert.equal(
    routing.isImageComparisonRequest(
        'Wie ist das Wetter heute?',
        true,
    ),
    false,
);

const imageArtifactB = {
    ...imageArtifact,
    artifact_id: 'image-1234567891-bbbbbbbbbbbb',
    image_id: '1234567891-bbbbbbbbbbbb',
};
const imageArtifactC = {
    ...imageArtifact,
    artifact_id: 'image-1234567892-cccccccccccc',
    image_id: '1234567892-cccccccccccc',
};
const followupJobs = new Map([
    ['d'.repeat(24), imageArtifactB],
    ['e'.repeat(24), imageArtifactC],
]);
let followupActionCount = 0;
selectedAttachments = [];
context.fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.startsWith('/api/mlx/image-jobs/')) {
        const jobId = url.split('/').at(-1);
        const artifact = followupJobs.get(jobId);
        return {
            ok: true,
            async json() {
                return {
                    tool: 'image_edit',
                    status: 'completed',
                    data: {
                        job: {
                            id: jobId,
                            operation: 'edit',
                            status: 'completed',
                            current_step: 8,
                            total_steps: 8,
                        },
                        image: artifact,
                    },
                    artifacts: [artifact],
                    error: null,
                };
            },
        };
    }

    assert.equal(url, '/api/mlx/chat/actions');
    const jobId = followupActionCount === 0
        ? 'd'.repeat(24)
        : 'e'.repeat(24);
    followupActionCount += 1;
    return {
        ok: true,
        async json() {
            return {
                tool: 'image_edit',
                status: 'queued',
                data: {
                    job: {
                        id: jobId,
                        operation: 'edit',
                        status: 'queued',
                    },
                },
                artifacts: [],
                error: null,
            };
        },
    };
};

const followupRequestStart = requests.length;
input.value = 'Mach es noch dunkler.';
await window.MLXChatGeneration.sendMessage();
await new Promise(resolve => setImmediate(resolve));
const secondActionPayload = JSON.parse(
    requests[followupRequestStart].options.body
);
assert.equal(secondActionPayload.file_context, null);
assert.equal(
    secondActionPayload.active_artifact_id,
    imageArtifact.artifact_id,
);
assert.equal(
    session.workspace.active_artifact_id,
    imageArtifactB.artifact_id,
);

assert.equal(
    imageArtifactB.parent_artifact_id,
    imageArtifact.artifact_id,
);

let imageState =
    routing.imageConversationState(session);

assert.equal(
    imageState.active.artifact_id,
    imageArtifactB.artifact_id,
);

assert.equal(
    imageState.parent.artifact_id,
    imageArtifact.artifact_id,
);

assert.equal(imageState.has_active_image, true);
assert.equal(imageState.has_parent_image, true);

const thirdRequestStart = requests.length;
input.value = 'Mach das Bild etwas wärmer.';
await window.MLXChatGeneration.sendMessage();
await new Promise(resolve => setImmediate(resolve));
const thirdActionPayload = JSON.parse(
    requests[thirdRequestStart].options.body
);
assert.equal(thirdActionPayload.file_context, null);
assert.equal(
    thirdActionPayload.active_artifact_id,
    imageArtifactB.artifact_id,
);
assert.equal(
    session.workspace.active_artifact_id,
    imageArtifactC.artifact_id,
);

assert.equal(
    imageArtifactC.parent_artifact_id,
    imageArtifactB.artifact_id,
);

imageState =
    routing.imageConversationState(session);

assert.equal(
    imageState.active.artifact_id,
    imageArtifactC.artifact_id,
);

assert.equal(
    imageState.parent.artifact_id,
    imageArtifactB.artifact_id,
);

assert.equal(imageState.has_active_image, true);
assert.equal(imageState.has_parent_image, true);

// Comparison order is parent first, current result second.
// buildApiMessages() must preserve this order for Vision.
const comparisonMessage =
    routing.buildApiMessages([{
        role: 'user',
        content: 'Was wurde verändert?',
        vision_images: [
            {
                kind: 'image',
                name: 'before.png',
                data_url:
                    'data:image/png;base64,before',
                artifact_id:
                    imageState.parent.artifact_id,
            },
            {
                kind: 'image',
                name: 'after.png',
                data_url:
                    'data:image/png;base64,after',
                artifact_id:
                    imageState.active.artifact_id,
            },
        ],
    }])[0];

assert.deepEqual(
    Array.from(comparisonMessage.content)
        .filter(part => part.type === 'image_url')
        .map(part => part.image_url.url),
    [
        'data:image/png;base64,before',
        'data:image/png;base64,after',
    ],
);

// ----------------------------------------------------------------
// Full sendMessage() integration:
// "Was wurde verändert?" must load parent + active into
// vision_images, in that exact order, without invoking image_edit.
// ----------------------------------------------------------------

const comparisonFetchStart = requests.length;

const comparisonEncoder = new TextEncoder();

function comparisonReader(text) {
    const chunks = [
        comparisonEncoder.encode(text),
    ];

    let index = 0;

    return {
        async read() {
            if (index >= chunks.length) {
                return {
                    value: undefined,
                    done: true,
                };
            }

            return {
                value: chunks[index++],
                done: false,
            };
        },
    };
}

let comparisonChatPayload = null;

context.fetch = async (url, options) => {
    requests.push({ url, options });

    if (url.startsWith('/api/mlx/images/')) {
        const imageId = decodeURIComponent(
            url.split('/').at(-1)
        );

        const payload =
            imageId === imageArtifactB.image_id
                ? 'before'
                : imageId === imageArtifactC.image_id
                    ? 'after'
                    : 'unknown';

        return {
            ok: true,
            async blob() {
                return new Blob([
                    Buffer.from(payload),
                ], {
                    type: 'image/png',
                });
            },
        };
    }

    if (url === '/api/chat/stream') {
        comparisonChatPayload =
            JSON.parse(options.body);

        const stream =
            'data: {"type":"content","text":"Comparison complete."}\n\n' +
            'event: done\ndata: {}\n\n';

        return {
            ok: true,
            body: {
                getReader() {
                    return comparisonReader(stream);
                },
            },
        };
    }

    throw new Error(
        `Unexpected request during comparison test: ${url}`
    );
};

input.value = 'Was wurde verändert?';

await window.MLXChatGeneration.sendMessage();

await new Promise(resolve => setImmediate(resolve));

const comparisonUserMessage =
    session.messages
        .slice()
        .reverse()
        .find(message =>
            message.role === 'user' &&
            message.display_content === 'Was wurde verändert?'
        );

assert.ok(comparisonUserMessage);

assert.deepEqual(
    Array.from(
        comparisonUserMessage.vision_images,
        image => image.artifact_id,
    ),
    [
        imageArtifactB.artifact_id,
        imageArtifactC.artifact_id,
    ],
);

assert.equal(
    comparisonUserMessage.vision_images.length,
    2,
);

assert.ok(comparisonChatPayload);

const comparisonApiUserMessage =
    comparisonChatPayload.messages
        .slice()
        .reverse()
        .find(message =>
            message.role === 'user'
        );

assert.ok(comparisonApiUserMessage);

assert.ok(
    Array.isArray(comparisonApiUserMessage.content)
);

assert.deepEqual(
    Array.from(comparisonApiUserMessage.content)
        .filter(part => part.type === 'image_url')
        .map(part => part.image_url.url),
    [
        'data:image/png;base64,YmVmb3Jl',
        'data:image/png;base64,YWZ0ZXI=',
    ],
);

assert.equal(
    session.messages.at(-1).role,
    'assistant',
);

assert.equal(
    session.messages.at(-1).content,
    'Comparison complete.',
);

assert.equal(
    requests
        .slice(comparisonFetchStart)
        .some(request =>
            request.url === '/api/mlx/chat/actions'
        ),
    false,
);

selectedAttachments = [imageAttachment];
const uploadedPriorityStart = requests.length;
input.value = 'Mach das Bild dunkler.';
await window.MLXChatGeneration.sendMessage();
await new Promise(resolve => setImmediate(resolve));
const uploadedPriorityPayload = JSON.parse(
    requests[uploadedPriorityStart].options.body
);
assert.equal(
    uploadedPriorityPayload.file_context.stored_path,
    '/uploads/stored.png',
);
assert.equal(uploadedPriorityPayload.active_artifact_id, null);
selectedAttachments = [];

const preservedArtifactId = session.workspace.active_artifact_id;
for (const status of ['failed', 'cancelled', 'running']) {
    routing.updateImageJobMessage(session, {}, {
        tool: 'image_edit',
        status,
        data: {
            job: {
                id: 'f'.repeat(24),
                operation: 'edit',
                status,
            },
        },
        artifacts: [],
        error: status === 'failed' ? 'provider failed' : null,
    });
    assert.equal(
        session.workspace.active_artifact_id,
        preservedArtifactId,
    );
}

const progressSession = { messages: [], workspace: {} };
const progressMessage = {};
const imageProgressResult = (currentStep, status = 'running') => ({
    tool: 'image_edit',
    status,
    data: {
        job: {
            id: '1'.repeat(24),
            operation: 'edit',
            status,
            current_step: currentStep,
            total_steps: 8,
            created_at: 900,
            started_at: 910,
        },
    },
    artifacts: [],
    error: null,
});

routing.updateImageJobMessage(
    progressSession,
    progressMessage,
    imageProgressResult(1),
    1000,
);
assert.equal(progressMessage.image_job.progress_updated_at, 1000);

routing.updateImageJobMessage(
    progressSession,
    progressMessage,
    imageProgressResult(1),
    1010,
);
assert.equal(progressMessage.image_job.progress_updated_at, 1000);

routing.updateImageJobMessage(
    progressSession,
    progressMessage,
    imageProgressResult(2),
    1030,
);
assert.equal(progressMessage.image_job.progress_updated_at, 1030);

const emptySession = { messages: [], workspace: {} };
assert.equal(routing.activeSessionImageArtifact(emptySession), null);
assert.equal(
    routing.activeSessionImageArtifact({
        messages: session.messages,
        workspace: {
            active_artifact_id: 'file-1234567892-cccccccccccc',
        },
    }),
    null,
);

class TestElement {
    constructor(tagName = 'div') {
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.className = '';
        this.textContent = '';
        this.style = {};
        this.listeners = {};
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    addEventListener(type, callback) {
        this.listeners[type] = callback;
    }
}

context.document.createElement = tagName => new TestElement(tagName);
const renderingWindow = {
    MLXI18n: window.MLXI18n,
    MLXChatGeneration: {
        isWatchingImageJob() {
            return false;
        },
        updateImageJobMessage(_session, message, result) {
            message.image_job = result.data.job;
            message.tool_result = result;
        },
        createImageUpscaleMenu(source) {
            const menu = new TestElement('details');
            menu.className = 'image-upscale-menu';
            menu.source = source;
            return menu;
        },
    },
};
renderingWindow.window = renderingWindow;
const cancellationRequests = [];
const cancellationSession = { messages: [], workspace: {} };
const renderingIntervals = [];
const clearedRenderingIntervals = [];
const renderingContext = {
    console,
    fetch: async (url, options) => {
        cancellationRequests.push({ url, options });
        return {
            ok: true,
            async json() {
                return {
                    tool: 'image_edit',
                    status: 'cancelled',
                    data: {
                        job: {
                            id: 'b'.repeat(24),
                            operation: 'edit',
                            status: 'cancelled',
                            current_step: 3,
                            total_steps: 8,
                        },
                    },
                    artifacts: [],
                    error: null,
                };
            },
        };
    },
    MLXChatSessions: {
        currentSession: () => cancellationSession,
        saveSessions() {},
    },
    MLXChatRuntime: {
        beforeMessagesRender: () => null,
        afterMessagesRender() {},
    },
    setInterval(callback, delay) {
        renderingIntervals.push({ callback, delay });
        return renderingIntervals.length;
    },
    clearInterval(timerId) {
        clearedRenderingIntervals.push(timerId);
    },
    document: {
        addEventListener() {},
        createElement: tagName => new TestElement(tagName),
        getElementById: () => new TestElement(),
        querySelectorAll: () => [],
    },
    window: renderingWindow,
};
vm.runInNewContext(renderingSource, renderingContext, {
    filename: 'frontend/assets/chat/rendering.js',
});
renderingWindow.MLXChatRendering.configure({
    state: { sessions: [], activeId: null },
    currentSession: () => cancellationSession,
    isGenerating: () => false,
    selectSession() {},
    renameSession() {},
    deleteSession() {},
    updateContext() {},
    startEditMessage() {},
    regenerateLastAnswer() {},
});

const renderImageArtifactCard =
    renderingWindow.MLXChatRendering.__test.renderImageArtifactCard;
const renderImageJobCard =
    renderingWindow.MLXChatRendering.__test.renderImageJobCard;
const imageJobPresentation =
    renderingWindow.MLXChatRendering.__test.imageJobPresentation;
const syncImageJobUiTimer =
    renderingWindow.MLXChatRendering.__test.syncImageJobUiTimer;
const descendants = element => [
    element,
    ...element.children.flatMap(descendants),
];

const freshStep = imageJobPresentation({
    id: '1'.repeat(24),
    operation: 'edit',
    status: 'running',
    current_step: 1,
    total_steps: 8,
    created_at: 900,
    started_at: 910,
    progress_updated_at: 1000,
}, 1024);
assert.equal(freshStep.stale, false);
assert.equal(freshStep.title, 'Editing image …');
assert.match(freshStep.details, /Step 1\/8/);
assert.match(freshStep.details, /Elapsed: 01:54/);

const staleStepJob = {
    id: '1'.repeat(24),
    operation: 'edit',
    status: 'running',
    current_step: 1,
    total_steps: 8,
    created_at: 900,
    started_at: 910,
    progress_updated_at: 1000,
};
const staleStep = imageJobPresentation(staleStepJob, 1025);
assert.equal(staleStep.stale, true);
assert.equal(staleStep.title, 'Image processing continues …');
assert.match(staleStep.details, /Last reported step: 1\/8/);
assert.equal(staleStepJob.status, 'running');
assert.equal(staleStepJob.current_step, 1);

const freshSecondStep = imageJobPresentation(
    progressMessage.image_job,
    1031,
);
assert.equal(freshSecondStep.stale, false);
assert.match(freshSecondStep.details, /Step 2\/8/);

const noStep = imageJobPresentation({
    status: 'running',
    current_step: null,
    total_steps: 8,
    created_at: 1000,
}, 1037);
assert.equal(noStep.hasStepProgress, false);
assert.equal(noStep.title, 'Image is being processed …');
assert.equal(noStep.details, 'Elapsed: 00:37');

const loading = imageJobPresentation({
    status: 'loading',
    created_at: 1000,
}, 1012);
assert.equal(loading.title, 'Loading model …');
assert.equal(loading.details, 'Elapsed: 00:12');

const saving = imageJobPresentation({
    status: 'saving',
    started_at: 1000,
}, 1068);
assert.equal(saving.title, 'Saving image …');
assert.equal(saving.details, 'Elapsed: 01:08');

const completed = imageJobPresentation({
    status: 'completed',
    started_at: 1000,
}, 1068);
assert.equal(completed.active, false);
assert.equal(completed.elapsed, null);

const reloadMessage = {
    image_job: {
        id: '9'.repeat(24),
        status: 'running',
        created_at: 1000,
    },
};
cancellationSession.messages = [reloadMessage];
syncImageJobUiTimer();
syncImageJobUiTimer();
assert.equal(renderingIntervals.length, 1);
assert.equal(renderingIntervals[0].delay, 1000);

cancellationSession.messages = [
    { image_job: { status: 'completed' } },
    { image_job: { status: 'completed' } },
];
syncImageJobUiTimer();
assert.deepEqual(clearedRenderingIntervals, [1]);
syncImageJobUiTimer();
assert.equal(renderingIntervals.length, 1);
cancellationSession.messages = [];

const runningJobMessage = {
    image_job: {
        id: 'b'.repeat(24),
        operation: 'edit',
        status: 'running',
        current_step: 2,
        total_steps: 8,
    },
};
const runningJobCard = renderImageJobCard(runningJobMessage);
const runningJobElements = descendants(runningJobCard);
assert.match(
    runningJobElements.find(
        element => element.className === 'batch-chat-details'
    ).textContent,
    /2\/8/,
);
assert.equal(
    runningJobElements.find(
        element => element.className === 'batch-progress-fill'
    ).style.width,
    '25.00%',
);

const upscaleJobCard = renderImageJobCard({
    image_job: {
        id: '7'.repeat(24),
        operation: 'upscale',
        status: 'running',
        current_step: 250,
        total_steps: 1000,
    },
});
const upscaleJobElements = descendants(upscaleJobCard);
assert.equal(
    upscaleJobElements.find(element => element.tagName === 'STRONG')
        .textContent,
    'Enhancing image …',
);
assert.equal(
    upscaleJobElements.find(
        element => element.className === 'batch-progress-fill'
    ).style.width,
    '25.00%',
);

const staleJobMessage = {
    image_job: {
        id: '8'.repeat(24),
        operation: 'edit',
        status: 'running',
        current_step: 1,
        total_steps: 8,
        created_at: Date.now() / 1000 - 60,
        progress_updated_at: Date.now() / 1000 - 30,
    },
};
const staleJobCard = renderImageJobCard(staleJobMessage);
const staleJobElements = descendants(staleJobCard);
assert.equal(
    staleJobElements.find(element => element.tagName === 'STRONG')
        .textContent,
    'Image processing continues …',
);
assert.match(
    staleJobElements.find(
        element => element.className === 'batch-chat-details'
    ).textContent,
    /Last reported step: 1\/8/,
);
assert.equal(
    staleJobElements.find(
        element => element.className === 'batch-progress-fill'
    ).style.width,
    '12.50%',
);
assert.ok(
    staleJobElements.find(element => element.tagName === 'BUTTON')
);
assert.equal(staleJobMessage.image_job.status, 'running');

const cancelButton = runningJobElements.find(
    element => element.tagName === 'BUTTON'
);
await cancelButton.listeners.click();
assert.equal(
    cancellationRequests[0].url,
    '/api/mlx/image-jobs/' + 'b'.repeat(24) + '/cancel',
);
assert.equal(cancellationRequests[0].options.method, 'POST');
assert.equal(runningJobMessage.image_job.status, 'cancelled');

const noProgressCard = renderImageJobCard({
    image_job: {
        id: 'c'.repeat(24),
        operation: 'generate',
        status: 'loading',
        current_step: null,
        total_steps: null,
    },
});
assert.equal(
    descendants(noProgressCard).some(
        element => element.className === 'batch-progress-wrap'
    ),
    false,
);
assert.equal(
    descendants(noProgressCard).find(
        element => element.className === 'batch-chat-details'
    ).textContent.includes('%'),
    false,
);

const editMessage = session.messages
    .slice()
    .reverse()
    .find(message =>
        message?.tool_result?.artifacts?.some(
            artifact =>
                artifact.artifact_id ===
                imageArtifactC.artifact_id
        )
    );
assert.equal(
    editMessage.tool_result.artifacts[0].artifact_id,
    imageArtifactC.artifact_id,
);
const editCard = renderImageArtifactCard(editMessage);
const editPreview = editCard.children.find(
    child => child.tagName === 'IMG',
);
assert.equal(
    editPreview.src,
    '/api/mlx/images/' + encodeURIComponent(imageArtifactC.image_id),
);
assert.equal(
    descendants(editCard).find(
        element => element.className === 'image-upscale-menu'
    ).source.artifact_id,
    imageArtifactC.artifact_id,
);

const generatedCard = renderImageArtifactCard({
    tool_result: {
        tool: 'image_generate',
        artifacts: [imageArtifact],
    },
});
assert.ok(generatedCard);
assert.equal(
    generatedCard.children.find(child => child.tagName === 'IMG').src,
    '/api/mlx/images/' + encodeURIComponent(imageArtifact.image_id),
);
assert.equal(
    renderImageArtifactCard({
        tool_result: {
            tool: 'image_edit',
            artifacts: [],
        },
    }),
    null,
);

const upscaledArtifact = {
    ...imageArtifact,
    artifact_id: 'image-1234567893-dddddddddddd',
    image_id: '1234567893-dddddddddddd',
    provider: 'realesrgan',
    scale: 2,
    preset: 'photo-2x',
};
const upscaledCard = renderImageArtifactCard({
    tool_result: {
        tool: 'image_upscale',
        status: 'completed',
        artifacts: [upscaledArtifact],
    },
});
assert.ok(upscaledCard);
assert.equal(
    upscaledCard.children.find(child => child.tagName === 'IMG').src,
    '/api/mlx/images/' + encodeURIComponent(upscaledArtifact.image_id),
);
assert.equal(
    descendants(upscaledCard).find(
        element => element.className === 'image-upscale-menu'
    ).source.artifact_id,
    upscaledArtifact.artifact_id,
);
assert.equal(
    renderImageArtifactCard({
        image_job: { status: 'cancelled' },
        tool_result: {
            tool: 'image_edit',
            status: 'cancelled',
            artifacts: [],
        },
    }),
    null,
);

selectedAttachments = [];
const upscaleJobId = '2'.repeat(24);
let upscalePolls = 0;
const upscaleRequestStart = requests.length;
context.fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.startsWith('/api/mlx/image-jobs/')) {
        upscalePolls += 1;
        const status = upscalePolls === 1 ? 'running' : 'completed';
        return {
            ok: true,
            async json() {
                return {
                    tool: 'image_upscale',
                    status,
                    data: {
                        job: {
                            id: upscaleJobId,
                            operation: 'upscale',
                            status,
                            current_step:
                                status === 'running' ? 250 : 1000,
                            total_steps: 1000,
                            ...(status === 'completed'
                                ? { result: upscaledArtifact }
                                : {}),
                        },
                        ...(status === 'completed'
                            ? { image: upscaledArtifact }
                            : {}),
                    },
                    artifacts:
                        status === 'completed' ? [upscaledArtifact] : [],
                    error: null,
                };
            },
        };
    }
    assert.equal(url, '/api/mlx/chat/actions');
    return {
        ok: true,
        async json() {
            return {
                tool: 'image_upscale',
                status: 'queued',
                data: {
                    job: {
                        id: upscaleJobId,
                        operation: 'upscale',
                        status: 'queued',
                    },
                },
                artifacts: [],
                error: null,
            };
        },
    };
};

assert.equal(
    await window.MLXChatGeneration.startImageUpscale(
        imageArtifactC,
        'photo-2x',
    ),
    true,
);
await new Promise(resolve => setImmediate(resolve));
const upscaleActionPayload = JSON.parse(
    requests[upscaleRequestStart].options.body,
);
assert.equal(upscaleActionPayload.action, 'image_upscale');
assert.equal(upscaleActionPayload.active_artifact_id, imageArtifactC.artifact_id);
assert.equal(upscaleActionPayload.file_context, null);
assert.deepEqual(
    Object.fromEntries(Object.entries(upscaleActionPayload.image_options)),
    { preset: 'photo-2x' },
);
assert.equal(
    routing.isWatchingImageJob(session.messages.at(-1)),
    true,
);
assert.equal(session.messages.at(-1).image_job.current_step, 250);
assert.equal(scheduledCallbacks.length, 1);
await scheduledCallbacks.shift()();
await new Promise(resolve => setImmediate(resolve));
assert.equal(session.messages.at(-1).tool_result.tool, 'image_upscale');
assert.equal(
    session.messages.at(-1).content,
    'Image enhanced locally with Real-ESRGAN.',
);
assert.equal(
    session.workspace.active_artifact_id,
    upscaledArtifact.artifact_id,
);
assert.equal(
    routing.activeSessionImageArtifact(session).artifact_id,
    upscaledArtifact.artifact_id,
);
assert.equal(
    routing.isImageEditRequest('Make it darker.', true),
    true,
);

const repeatUpscaleStart = requests.length;
context.fetch = async (url, options) => {
    requests.push({ url, options });
    assert.equal(url, '/api/mlx/chat/actions');
    return {
        ok: true,
        async json() {
            return {
                tool: 'image_upscale',
                status: 'failed',
                data: {},
                artifacts: [],
                error: 'provider failed',
            };
        },
    };
};
assert.equal(
    await window.MLXChatGeneration.startImageUpscale(
        upscaledArtifact,
        'anime-4x',
    ),
    false,
);
const repeatUpscalePayload = JSON.parse(
    requests[repeatUpscaleStart].options.body,
);
assert.equal(
    repeatUpscalePayload.active_artifact_id,
    upscaledArtifact.artifact_id,
);
assert.equal(repeatUpscalePayload.image_options.preset, 'anime-4x');
assert.match(session.messages.at(-1).content, /provider failed/);

const uploadedUpscaleStart = requests.length;
assert.equal(
    await window.MLXChatGeneration.startImageUpscale(
        imageAttachment,
        'photo-4x',
    ),
    false,
);
const uploadedUpscalePayload = JSON.parse(
    requests[uploadedUpscaleStart].options.body,
);
assert.equal(uploadedUpscalePayload.active_artifact_id, null);
assert.equal(
    uploadedUpscalePayload.file_context.stored_path,
    '/uploads/stored.png',
);
assert.equal(uploadedUpscalePayload.image_options.preset, 'photo-4x');

console.log(
    'Image jobs, routing, progress, cancellation, artifacts, and errors passed.',
);
