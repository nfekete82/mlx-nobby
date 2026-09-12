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
        t(_key, fallback, variables = {}) {
            let value = fallback;
            for (const [name, replacement] of Object.entries(variables)) {
                value = value.replaceAll(`{${name}}`, replacement);
            }
            return value;
        },
    },
};
window.window = window;

const context = {
    console,
    crypto: { randomUUID: () => 'attachment-id' },
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
    getAttachments: () => [imageAttachment],
    buildAttachmentContext: () => '',
    clearAttachments() {},
};
context.MLXChatRuntime = {
    isSwitching: () => false,
    async ensureVisionSupport() {
        visionChecks += 1;
        return false;
    },
    autoResize() {},
    beginUserMessage() {},
};
context.MLXChatSessions = {
    currentSession: () => session,
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
window.MLXChatGeneration.configure({
    getGenerating: () => generating,
    setGenerating: value => {
        generating = value;
    },
    getAbortController: () => null,
    setAbortController() {},
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

const renderingWindow = {
    MLXI18n: window.MLXI18n,
    MLXChatGeneration: {
        updateImageJobMessage(_session, message, result) {
            message.image_job = result.data.job;
            message.tool_result = result;
        },
    },
};
renderingWindow.window = renderingWindow;
const cancellationRequests = [];
const cancellationSession = { messages: [], workspace: {} };
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
const descendants = element => [
    element,
    ...element.children.flatMap(descendants),
];

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

const editMessage = session.messages.at(-1);
assert.equal(
    editMessage.tool_result.artifacts[0].artifact_id,
    imageArtifact.artifact_id,
);
const editCard = renderImageArtifactCard(editMessage);
const editPreview = editCard.children.find(
    child => child.tagName === 'IMG',
);
assert.equal(
    editPreview.src,
    '/api/mlx/images/' + encodeURIComponent(imageArtifact.image_id),
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

console.log(
    'Image jobs, routing, progress, cancellation, artifacts, and errors passed.',
);
