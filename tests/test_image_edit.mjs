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
const requests = [];
const input = { value: '' };

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

    assert.equal(url, '/api/mlx/chat/actions');
    return {
        ok: true,
        async json() {
            return {
                tool: 'image_edit',
                status: 'completed',
                data: { image: imageArtifact },
                artifacts: [imageArtifact],
                error: null,
            };
        },
    };
};
input.value = 'ändere das klein in die farbe rot';

await window.MLXChatGeneration.sendMessage();

assert.equal(visionChecks, 0);
assert.deepEqual(
    requests.map(request => request.url),
    ['/api/mlx/batch/upload', '/api/mlx/chat/actions'],
);
const actionPayload = JSON.parse(requests[1].options.body);
assert.equal(actionPayload.file_context.kind, 'image');
assert.equal(actionPayload.file_context.stored_path, '/uploads/stored.png');
assert.equal(actionPayload.image_options, null);
assert.equal(session.messages.at(-1).tool_result.tool, 'image_edit');
assert.equal(
    session.workspace.active_artifact_id,
    imageArtifact.artifact_id,
);

console.log(
    'Image edit upload, routing, artifact, and provider error presentation passed.',
);
