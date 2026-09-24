import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');
const rendering = fs.readFileSync(new URL('../frontend/assets/chat/rendering.js', import.meta.url), 'utf8');
const timers = [];
let activeSession;
let nextResult;
const window = { MLXI18n: { t(_key, fallback) { return fallback; } } };
window.window = window;
const context = {
    window, console, crypto: { randomUUID: () => 'trace' },
    document: { addEventListener() {}, getElementById() { return {}; } },
    setTimeout(callback, delay) { timers.push({ callback, delay }); return timers.length; },
    clearTimeout() {},
    async fetch(url) {
        assert.match(url, /^\/api\/mlx\/video-jobs\/[a-f0-9]{24}$/);
        return { ok: true, async json() { return structuredClone(nextResult); } };
    },
};
vm.runInNewContext(source, context, { filename: 'generation.js' });
context.MLXChatSessions = { currentSession: () => activeSession, saveSessions() {} };
context.MLXChatRendering = { renderMessages() {} };

const api = window.MLXChatGeneration;
assert.equal(api.__test.isVideoRequest('Erstelle ein Video von einem Ball'), true);
assert.equal(api.__test.isVideoRequest('Animiere dieses Bild'), true);
assert.equal(api.__test.isVideoRequest('Wie wird das Wetter?'), false);
assert.equal(api.__test.isImageGenerationRequest('Erstelle ein Bild von einem Ball'), true);
assert.equal(api.__test.isImageGenerationRequest('Wie wird das Wetter?'), false);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('fast')),
    [5, 6, 8, 10, 20]
);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('standard')),
    [5, 6, 8, 10]
);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('quality')),
    [5]
);
assert.equal(api.__test.videoOptionsForRequest({}, 'video').duration, 5);
assert.equal(
    api.__test.videoOptionsForRequest(
        { video: { seed: 9 } },
        'video',
        20,
        'fast'
    ).duration,
    20
);
assert.equal(
    api.__test.videoOptionsForRequest(
        { video: { seed: 9 } },
        'video',
        20,
        'standard'
    ).duration,
    10
);
assert.equal(
    api.__test.videoOptionsForRequest(
        {},
        'video',
        10,
        'quality'
    ).duration,
    5
);
assert.equal(
    api.__test.videoOptionsForRequest(
        { video: { seed: 9 } },
        'video',
        10
    ).seed,
    9
);
assert.equal(
    api.__test.videoOptionsForRequest(
        {},
        'video',
        7
    ).duration,
    5
);
const activeArtifact = {
    artifact_id: 'image-1234567890-abcdef123456',
    image_id: '1234567890-abcdef123456',
    mime_type: 'image/png',
};
const sourceSession = {
    workspace: { active_artifact_id: activeArtifact.artifact_id },
    messages: [{
        role: 'assistant',
        tool_result: {
            tool: 'image_generate', status: 'completed', artifacts: [activeArtifact],
        },
    }],
};
assert.equal(
    api.__test.preferredVideoImageSource(sourceSession, []).origin,
    'active_artifact',
);
const oldUpload = { kind: 'image', name: 'old.png', stored_path: '/managed/old.png' };
const newUpload = { kind: 'image', name: 'new.png', stored_path: '/managed/new.png' };
assert.equal(
    api.__test.preferredVideoImageSource(sourceSession, [oldUpload, newUpload]).source.name,
    'new.png',
);
const uploadOnlySession = {
    workspace: {},
    messages: [{ role: 'user', attachments: [oldUpload, newUpload] }],
};
assert.equal(
    api.__test.preferredVideoImageSource(uploadOnlySession, []),
    null,
);
const id = 'd'.repeat(24);
const message = {
    role: 'assistant', content: '',
    video_job: { id, operation: 't2v', status: 'generating' },
    tool_result: { tool: 'video_generate', status: 'generating', artifacts: [] },
};
activeSession = { messages: [message] };
nextResult = {
    type: 'tool_result', tool: 'video_generate', status: 'completed',
    data: { job: { id, operation: 't2v', status: 'completed' } },
    artifacts: [{ artifact_id: 'video-' + id, video_id: id, mime_type: 'video/mp4' }],
    error: null,
};
assert.equal(api.__test.watchVideoJob(activeSession, message), true);
await new Promise(resolve => setImmediate(resolve));
assert.equal(message.video_job.status, 'completed');
assert.equal(message.tool_result.artifacts[0].mime_type, 'video/mp4');

const renderingWindow = { MLXI18n: { t(_key, fallback) { return fallback; } } };
renderingWindow.window = renderingWindow;
vm.runInNewContext(rendering, {
    window: renderingWindow,
    document: { getElementById() { return null; }, addEventListener() {} },
    console, setInterval, clearInterval, Date,
}, { filename: 'rendering.js' });
const mediaProgress = renderingWindow.MLXChatRendering.__test.mediaJobPresentation;
const renderToolCard = renderingWindow.MLXChatRendering.__test.renderToolCard;
assert.equal(renderToolCard({ tool_result: { tool: 'video_animate', status: 'generating' } }), null);
assert.equal(renderToolCard({ tool_result: { tool: 'image_generate', status: 'running' } }), null);
const liveVideo = mediaProgress({
    status: 'generating', phase: 'inference', progress: 50,
    current_step: 4, total_steps: 8, started_at: 80,
}, 'video', 100);
assert.equal(liveVideo.percent, 50);
assert.equal(liveVideo.phase, 'Generating');
assert.equal(liveVideo.hasStepProgress, true);
assert.equal(liveVideo.etaSeconds, 20);
const completedVideo = mediaProgress({ status: 'completed', progress: 15 }, 'video', 100);
assert.equal(completedVideo.percent, 100);
assert.equal(
    mediaProgress({ status: 'upscaling', phase: 'upscaling', progress: 85 }, 'video', 100).phase,
    'Upscaling',
);

assert.match(rendering, /document\.createElement\('video'\)/);
assert.match(rendering, /video\.controls = true/);
assert.match(rendering, /\/api\/mlx\/videos\//);
assert.match(rendering, /Source: /);
assert.match(rendering, /Target: /);
assert.match(rendering, /contain \+ padding/);
assert.match(rendering, /batch-progress-text/);
assert.match(rendering, /LTX Fast: 8 Denoising-Schritte/);
console.log('Video routing, polling, completion artifact, player, and download UI passed.');
