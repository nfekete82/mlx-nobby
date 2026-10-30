import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');
const rendering = fs.readFileSync(new URL('../frontend/assets/chat/rendering.js', import.meta.url), 'utf8');
const chatHtml = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const timers = [];
let activeSession;
let nextResult;
const requestedUrls = [];
const window = { MLXI18n: { t(_key, fallback) { return fallback; } } };
window.window = window;
const context = {
    window, console, crypto: { randomUUID: () => 'trace' },
    document: { addEventListener() {}, getElementById() { return {}; } },
    setTimeout(callback, delay) { timers.push({ callback, delay }); return timers.length; },
    clearTimeout() {},
    async fetch(url) {
        requestedUrls.push(url);
        assert.match(url, /^\/(?:api\/mlx\/(?:video-jobs|shorts-jobs)|api\/talking-photo\/jobs)\/[a-f0-9]{24}$/);
        return { ok: true, async json() { return structuredClone(nextResult); } };
    },
};
const voiceBridgeSource = fs.readFileSync(new URL('../frontend/assets/chat/voice-video.js', import.meta.url), 'utf8');
vm.runInNewContext(voiceBridgeSource, context, { filename: 'voice-video.js' });
vm.runInNewContext(source, context, { filename: 'generation.js' });
context.MLXChatSessions = { currentSession: () => activeSession, saveSessions() {} };
context.MLXChatRendering = { renderMessages() {} };

const api = window.MLXChatGeneration;
const { mediaPreviewAvailable, normalizeMediaPreviewQuality } = api.__test;
assert.equal(mediaPreviewAvailable('video', null, null), true);
assert.equal(mediaPreviewAvailable('image', null, null), false);
for (const [fileContext, artifactId] of [
    [{ kind: 'image', stored_path: '/managed/current.png' }, null],
    [{ kind: 'image', image_count: 2 }, null],
    [null, 'image-1234567890-abcdef123456'],
]) {
    const available = mediaPreviewAvailable('video', fileContext, artifactId);
    assert.equal(available, false);
    assert.equal(normalizeMediaPreviewQuality('preview', available), 'standard');
    for (const quality of ['fast', 'standard', 'quality']) {
        assert.equal(normalizeMediaPreviewQuality(quality, available), quality);
    }
}
assert.equal(normalizeMediaPreviewQuality('preview', true), 'preview');
assert.equal(api.__test.isVideoRequest('Erstelle ein Video von einem Ball'), true);
assert.equal(api.__test.isVideoRequest('Animiere dieses Bild'), true);
assert.equal(api.__test.isVideoRequest('Wie wird das Wetter?'), false);
assert.equal(api.__test.isImageGenerationRequest('Erstelle ein Bild von einem Ball'), true);
assert.equal(api.__test.isImageGenerationRequest('Wie wird das Wetter?'), false);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('fast')),
    [5, 6, 8, 10, 20, 30, 60]
);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('standard')),
    [5, 6, 8, 10, 20, 30, 60]
);
assert.deepEqual(
    Array.from(api.__test.videoDurationsForQuality('quality')),
    [5, 9, 10, 20, 30, 60]
);
assert.equal(api.__test.videoOptionsForRequest({}, 'video').duration, 5);
assert.equal(api.__test.videoOptionsForRequest({}, 'video', 60, 'quality').duration, 60);
assert.equal(api.__test.videoOptionsForRequest({}, 'video', 9, 'quality').duration, 9);
assert.equal(api.__test.videoOptionsForRequest({}, 'video').profile, 'standard');
const uncensoredOptions = api.__test.videoOptionsForRequest(
    {}, 'video', 5, 'standard', 'landscape', 'uncensored'
);
assert.equal(uncensoredOptions.profile, 'uncensored');
assert.deepEqual(Object.keys(uncensoredOptions).sort(), ['aspect_ratio', 'duration', 'profile']);
assert.match(chatHtml, /id="videoProfile"[\s\S]*?<option value="standard" selected>Standard<\/option>[\s\S]*?<option value="uncensored">Uncensored<\/option>/);
assert.match(source, /selectedVideoProfile = profileSelect.value/);
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
    20
);
assert.equal(
    api.__test.videoOptionsForRequest(
        {},
        'video',
        10,
        'quality'
    ).duration,
    10
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
const voiceJobId = 'f'.repeat(24);
const voiceMessage = {
    role: 'assistant', content: '',
    video_job: {id:voiceJobId, status:'motion', voice_video:true, source:'talking_photo'},
    tool_result: {tool:'video_animate',status:'motion',artifacts:[]}
};
activeSession = {messages:[voiceMessage]};
nextResult = {id:voiceJobId,status:'completed',voice:'pervin',scene_motion:'dance',result:{}};
assert.equal(api.__test.watchVideoJob(activeSession, voiceMessage), true);
await new Promise(resolve => setImmediate(resolve));
assert.equal(voiceMessage.video_job.status, 'completed');
assert.equal(voiceMessage.tool_result.artifacts[0].audio, true);
assert.equal(voiceMessage.tool_result.artifacts[0].url, '/api/talking-photo/videos/'+voiceJobId);
assert.equal(requestedUrls.at(-1), '/api/talking-photo/jobs/'+voiceJobId);


const shortId = 'e'.repeat(24);
const shortsMessage = {
    role: 'assistant', content: 'The action could not be completed.',
    shorts_job: { id: shortId, status: 'running', phase: 'video' },
    tool_result: { tool: 'shorts_generate', status: 'running', artifacts: [] },
};
activeSession = { messages: [shortsMessage] };
const queuedShortsResult = {
    type: 'tool_result', tool: 'shorts_generate', status: 'queued',
    data: { job: { id: shortId, status: 'queued', phase: 'planning', progress_percent: 5 } },
    artifacts: [], error: null,
};
assert.equal(api.__test.updateShortsJobMessage(activeSession, shortsMessage, queuedShortsResult), false);
assert.equal(shortsMessage.content, '');
assert.equal(shortsMessage.shorts_job.progress_percent, 5);
shortsMessage.shorts_job = { id: shortId, status: 'running', phase: 'video' };
nextResult = {
    type: 'tool_result', tool: 'shorts_generate', status: 'completed',
    data: { job: { id: shortId, status: 'completed', phase: 'completed', progress_percent: 100 } },
    artifacts: [{ video_id: shortId, mime_type: 'video/mp4', url: '/api/mlx/shorts/' + shortId }],
    error: null,
};
assert.equal(api.__test.watchShortsJob(activeSession, shortsMessage), true);
await new Promise(resolve => setImmediate(resolve));
assert.equal(shortsMessage.shorts_job.status, 'completed');
assert.equal(shortsMessage.tool_result.artifacts[0].url, '/api/mlx/shorts/' + shortId);
assert.equal(requestedUrls.at(-1), '/api/mlx/shorts-jobs/' + shortId);

const renderingWindow = { MLXI18n: { t(_key, fallback) { return fallback; } } };
renderingWindow.window = renderingWindow;
function testElement(tagName) {
    return {
        tagName, children: [], style: {}, textContent: '', className: '',
        appendChild(child) { this.children.push(child); return child; },
        setAttribute() {}, addEventListener() {}
    };
}
vm.runInNewContext(rendering, {
    window: renderingWindow,
    document: {
        getElementById() { return null; }, addEventListener() {},
        createElement(tagName) { return testElement(tagName); }
    },
    console, setInterval, clearInterval, Date,
}, { filename: 'rendering.js' });
const mediaProgress = renderingWindow.MLXChatRendering.__test.mediaJobPresentation;
const renderToolCard = renderingWindow.MLXChatRendering.__test.renderToolCard;
const renderShortsJobCard = renderingWindow.MLXChatRendering.__test.renderShortsJobCard;
const renderVideoArtifactCard = renderingWindow.MLXChatRendering.__test.renderVideoArtifactCard;
assert.equal(renderToolCard({ tool_result: { tool: 'video_animate', status: 'generating' } }), null);
assert.equal(renderToolCard({ tool_result: { tool: 'image_generate', status: 'running' } }), null);
assert.equal(renderToolCard({ tool_result: { tool: 'shorts_generate', status: 'running' } }), null);
const queuedShortsCard = renderShortsJobCard({
    shorts_job: {
        id: shortId, status: 'queued', phase: 'planning', progress_percent: 5,
        scene_number: 1, scene_count: 2, status_description: 'Plan ready'
    }
});
assert.equal(queuedShortsCard.children[0].textContent, 'Creating short …');
assert.match(queuedShortsCard.children[1].textContent, /Scene: 1 of 2/);
assert.equal(queuedShortsCard.children[2].children[1].textContent, '5%');
const completedShortsCard = renderShortsJobCard({
    shorts_job: { id: shortId, status: 'completed', phase: 'completed' }
});
assert.equal(completedShortsCard.children[2].children[1].textContent, '100%');
const completedShortsArtifact = renderVideoArtifactCard({ tool_result: nextResult });
assert.equal(completedShortsArtifact.children[0].src, '/api/mlx/shorts/' + shortId);
assert.equal(renderShortsJobCard({
    shorts_job: { id: shortId, status: 'failed', phase: 'failed', error: 'boom' }
}).children[0].textContent, 'Short creation failed');
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
assert.match(rendering, /Creating short/);
assert.match(rendering, /artifact\.url/);
assert.equal(rendering.includes('shorts_generatequeued'), false);
assert.match(chatHtml, /chat\/generation\.js\?v=20261030-german-quote-parser/);
assert.match(chatHtml, /chat\/voice-video\.js\?v=20261030-ltx-max-opt-in/);
assert.match(chatHtml, /chat\/rendering\.js\?v=[a-z0-9-]+/);
assert.match(chatHtml, /chat\.js\?v=[a-z0-9-]+/);
console.log('Video routing, polling, completion artifact, player, and download UI passed.');

// Reload/retry options cannot implicitly override the fresh dialog selection.
for (const stored of [{ video: { profile: 'uncensored' } }, {}]) {
    assert.equal(api.__test.videoOptionsForRequest(stored, 'video').profile, 'standard');
    assert.equal(api.__test.videoOptionsForRequest(stored, 'video', 5, 'standard', 'landscape', 'uncensored').profile, 'uncensored');
}
const profileOption = {};
const profileSelect = { querySelector: () => profileOption };
for (const available of [false, true]) {
    context.fetch = async () => ({ ok: true, json: async () => ({ profiles: { uncensored_available: available } }) });
    const checking = api.__test.updateVideoProfileAvailability(profileSelect);
    assert.equal(profileOption.disabled, true);
    await checking;
    assert.equal(profileOption.disabled, !available);
}
context.fetch = async () => { throw Error('offline'); };
await api.__test.updateVideoProfileAvailability(profileSelect);
assert.equal(profileOption.disabled, true);

// Long videos preserve confirmed partial progress across regular chat reload/polling.
assert.equal(api.__test.promptVideoPreferences('Kameraflug, 20 Sekunden, maximale Qualität').duration, 20);
assert.equal(api.__test.promptVideoPreferences('Kameraflug, 20 Sekunden, maximale Qualität').quality, 'quality');
assert.equal(api.__test.promptVideoPreferences('A camera flight, 30 seconds, maximum quality').duration, 30);
assert.equal(api.__test.promptVideoPreferences('Animate my portrait for 9 seconds').duration, 9);
assert.equal(api.__test.promptVideoPreferences('A camera flight').duration, null);
assert.equal(api.__test.videoOptionsForRequest({}, 'video', 20, 'quality').duration, 20);
const longJob = {id: 'e'.repeat(24), status: 'generating', phase: 'generating', automatic_continuation: true,
    stage_number: 3, stage_count: 5, target_duration: 20, confirmed_duration: 9,
    current_step: 2, total_steps: 8, phase_progress: .25, progress: null, started_at: Date.now()/1000-12,
    long_plan: {resolution:'1080p'}, last_activity_at:Date.now()/1000};
const longCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:longJob});
assert.match(longCard.children[1].textContent, /20 s.*1080p.*3\/5/);
assert.match(longCard.children[2].children[0].textContent,
    /Validated duration: 9 \/ 20 s \(45% of video duration, not rendering time\)/);
assert.equal(longCard.children[2].children[1].children[0].style.width, '45.00%');
assert.equal(longCard.children[3].children[0].textContent, 'Current processing step: Generating');
const longProgress = longCard.children[3].children[1];
assert.equal(longProgress.tagName, 'progress');
assert.equal(longProgress.value, .25);
assert.match(longCard.children[3].children[2].textContent, /2\/8 · 25% · only this processing step/);
const unknownCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:{...longJob,phase_progress:null}});
assert.equal(unknownCard.children[3].children[1].value, undefined);
assert.match(unknownCard.children[3].children[2].textContent, /no measurable step count/);
const decodeJob = {...longJob, phase: 'decoding', progress_message: 'LTX dekodiert Videoframes',
    phase_progress: null, current_step: null, total_steps: null};
const decodeCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:decodeJob});
assert.match(decodeCard.children[3].children[0].textContent, /LTX dekodiert Videoframes/);
assert.equal(decodeCard.children[3].children[1].value, undefined);
assert.equal(decodeCard.children[2].children[1].children[0].style.width, '45.00%');
const inactiveJob = {...longJob, last_activity_at: Date.now()/1000-360};
const inactiveCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:inactiveJob});
assert.match(inactiveCard.children[1].textContent, /No new LTX log output/);
const failedCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:{...longJob,status:'failed',resumable:true,native_job_id:'f'.repeat(24)}});
assert.ok(failedCard.children.some(node=>node.textContent==='Resume from validated checkpoint'));
const cancelledCard = renderingWindow.MLXChatRendering.__test.renderVideoJobCard({video_job:{...longJob,status:'cancelled',cancel_requested:true,resumable:true,native_job_id:'f'.repeat(24)}});
assert.ok(!cancelledCard.children.some(node=>node.textContent==='Resume from validated checkpoint'));
const busyLong = {video_job:longJob};
api.updateVideoJobMessage({},busyLong,{status:'generating',data:{job:longJob}});
assert.equal(busyLong.video_job.confirmed_duration,9);
