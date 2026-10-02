import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url),
    'utf8',
);
const chatSource = fs.readFileSync(
    new URL('../frontend/assets/chat.js', import.meta.url),
    'utf8',
);
const requests = [];
const warnings = [];
const timeouts = new Map();
let nextTimeoutId = 1;
let fetchImpl;
let activeSession = null;
let saves = 0;
let renders = 0;

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
    console: {
        ...console,
        warn(...values) {
            warnings.push(values);
        },
    },
    crypto: { randomUUID: () => 'trace-id' },
    document: {
        addEventListener() {},
        getElementById: () => ({}),
    },
    fetch(url, options) {
        requests.push({ url, options });
        return fetchImpl(url, options);
    },
    setTimeout(callback, delay) {
        const id = nextTimeoutId++;
        timeouts.set(id, { callback, delay });
        return id;
    },
    clearTimeout(id) {
        timeouts.delete(id);
    },
    window,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/generation.js',
});

context.MLXChatSessions = {
    currentSession: () => activeSession,
    saveSessions() {
        saves += 1;
    },
};
context.MLXChatRendering = {
    renderMessages() {
        renders += 1;
    },
    syncImageJobUiTimer() {},
};

const recovery = window.MLXChatGeneration.__test;
const settle = () => new Promise(resolve => setImmediate(resolve));
const imageArtifact = {
    artifact_id: 'image-1234567890-abcdef123456',
    image_id: '1234567890-abcdef123456',
    mime_type: 'image/png',
};

function response(toolResult) {
    return {
        ok: true,
        status: 200,
        async json() {
            return structuredClone(toolResult);
        },
    };
}

function toolResult(status, jobId, options = {}) {
    const artifact = options.artifact || null;
    return {
        type: 'tool_result',
        tool: options.tool || 'image_edit',
        status,
        data: {
            job: {
                id: jobId,
                operation: options.tool === 'image_generate'
                    ? 'generate'
                    : options.tool === 'image_upscale'
                        ? 'upscale'
                        : 'edit',
                status,
                current_step: options.currentStep ?? null,
                total_steps: options.totalSteps ?? 8,
                created_at: options.createdAt ?? 900,
                started_at: options.startedAt ?? 910,
                finished_at: options.finishedAt ?? null,
                result: artifact,
                error: options.error || null,
            },
            ...(artifact ? { image: artifact } : {}),
        },
        artifacts: artifact ? [artifact] : [],
        error: options.error || null,
    };
}

function storedMessage(status, jobId, options = {}) {
    return {
        role: 'assistant',
        content: '',
        image_job: {
            id: jobId,
            operation: options.tool === 'image_generate'
                ? 'generate'
                : options.tool === 'image_upscale'
                    ? 'upscale'
                    : 'edit',
            status,
            current_step: options.currentStep ?? null,
            total_steps: options.totalSteps ?? 8,
            created_at: 900,
            started_at: 910,
            ...(options.progressUpdatedAt
                ? { progress_updated_at: options.progressUpdatedAt }
                : {}),
        },
        tool_result: {
            tool: options.tool || 'image_edit',
            status,
            data: { job: { id: jobId, status } },
            artifacts: options.artifact ? [options.artifact] : [],
            error: null,
        },
    };
}

function session(id, messages, artifactId = 'image-old') {
    return {
        id,
        messages,
        workspace: { active_artifact_id: artifactId },
    };
}

function stopAllWatchers() {
    activeSession = null;
    recovery.resumeImageJobsForSession(null);
    timeouts.clear();
}

async function runNextTimeout(expectedDelay = 1000) {
    const entry = timeouts.entries().next().value;
    assert.ok(entry, 'expected a scheduled image-job poll');
    const [id, timer] = entry;
    timeouts.delete(id);
    assert.equal(timer.delay, expectedDelay);
    timer.callback();
    await settle();
}

for (const [status, digit, restoredTool] of [
    ['queued', '0', 'image_generate'],
    ['loading', '1', 'image_edit'],
    ['running', '2', 'image_edit'],
    ['saving', '3', 'image_edit'],
    ['queued', 'd', 'image_upscale'],
]) {
    const jobId = digit.repeat(24);
    const tool = restoredTool;
    const message = storedMessage(status, jobId, {
        tool,
        currentStep: status === 'running' ? 1 : null,
        progressUpdatedAt: status === 'running' ? 800 : null,
    });
    const restored = session(`session-${status}`, [message]);
    activeSession = restored;
    requests.length = 0;
    fetchImpl = async () => response(toolResult(status, jobId, {
        tool,
        currentStep: status === 'running' ? 1 : null,
    }));

    assert.equal(recovery.resumeImageJobsForSession(restored), 1);
    assert.equal(recovery.resumeImageJobsForSession(restored), 0);
    await settle();

    assert.equal(requests.length, 1, status);
    assert.equal(
        requests[0].url,
        `/api/mlx/image-jobs/${jobId}`,
        status,
    );
    assert.equal(requests[0].options, undefined);
    assert.equal(message.image_job.status, status);
    assert.equal(message.tool_result.tool, tool);
    assert.equal(recovery.isWatchingImageJob(message), true);
    if (status === 'running') {
        assert.equal(message.image_job.current_step, 1);
        assert.equal(message.image_job.progress_updated_at, 800);
    }
    assert.equal(timeouts.size, 1);
    stopAllWatchers();
    assert.equal(recovery.isWatchingImageJob(message), false);
}

const completedJobId = 'a'.repeat(24);
const completedMessage = storedMessage('running', completedJobId);
const completedSession = session('completed-session', [completedMessage]);
const completedResult = toolResult('completed', completedJobId, {
    artifact: imageArtifact,
    currentStep: 8,
    finishedAt: 1000,
});
activeSession = completedSession;
requests.length = 0;
fetchImpl = async () => response(completedResult);

assert.equal(recovery.resumeImageJobsForSession(completedSession), 1);
await settle();
assert.equal(completedMessage.image_job.status, 'completed');
assert.equal(completedMessage.tool_result.artifacts.length, 1);
assert.equal(
    completedMessage.tool_result.artifacts[0].artifact_id,
    imageArtifact.artifact_id,
);
assert.equal(completedSession.messages.length, 1);
assert.equal(
    completedSession.workspace.active_artifact_id,
    imageArtifact.artifact_id,
);
assert.equal(recovery.isWatchingImageJob(completedMessage), false);
assert.equal(timeouts.size, 0);
assert.equal(recovery.resumeImageJobsForSession(completedSession), 0);
assert.equal(requests.length, 1);

recovery.updateImageJobMessage(
    completedSession,
    completedMessage,
    completedResult,
);
assert.equal(completedSession.messages.length, 1);
assert.equal(completedMessage.tool_result.artifacts.length, 1);
assert.equal(
    recovery.activeSessionImageArtifact(completedSession).artifact_id,
    imageArtifact.artifact_id,
);

for (const status of ['failed', 'cancelled']) {
    const jobId = status[0].repeat(24);
    const message = storedMessage('running', jobId);
    const restored = session(`${status}-session`, [message]);
    activeSession = restored;
    fetchImpl = async () => response(toolResult(status, jobId, {
        error: status === 'failed' ? 'provider failed' : null,
    }));

    assert.equal(recovery.resumeImageJobsForSession(restored), 1);
    await settle();
    assert.equal(message.image_job.status, status);
    assert.equal(message.tool_result.artifacts.length, 0);
    assert.equal(restored.workspace.active_artifact_id, 'image-old');
    assert.equal(recovery.isWatchingImageJob(message), false);
    assert.equal(timeouts.size, 0);
}

const missingJobId = '4'.repeat(24);
const missingMessage = storedMessage('running', missingJobId);
const missingSession = session('missing-session', [missingMessage]);
activeSession = missingSession;
fetchImpl = async () => ({
    ok: false,
    status: 404,
    async text() {
        return 'not found';
    },
});

assert.equal(recovery.resumeImageJobsForSession(missingSession), 1);
await settle();
assert.equal(missingMessage.image_job.status, 'failed');
assert.equal(missingMessage.image_job.recovery_status, 'not_found');
assert.match(missingMessage.content, /no longer available/);
assert.equal(missingMessage.tool_result.artifacts.length, 0);
assert.equal(missingSession.workspace.active_artifact_id, 'image-old');
assert.equal(recovery.isWatchingImageJob(missingMessage), false);
assert.equal(timeouts.size, 0);

const transientJobId = '5'.repeat(24);
const transientMessage = storedMessage('running', transientJobId);
const transientSession = session('transient-session', [transientMessage]);
let transientCalls = 0;
activeSession = transientSession;
fetchImpl = async () => {
    transientCalls += 1;

    // Simulate an image-service restart that lasts longer than the old
    // three-failure retry budget.
    if (transientCalls <= 4) {
        throw new Error('temporary connection failure');
    }

    return response(toolResult('running', transientJobId, {
        currentStep: 1,
    }));
};

assert.equal(recovery.resumeImageJobsForSession(transientSession), 1);
await settle();

assert.equal(transientCalls, 1);
assert.equal(recovery.isWatchingImageJob(transientMessage), true);
assert.equal(timeouts.size, 1);

await runNextTimeout(1000);
assert.equal(transientCalls, 2);
assert.equal(recovery.isWatchingImageJob(transientMessage), true);

await runNextTimeout(2000);
assert.equal(transientCalls, 3);
assert.equal(recovery.isWatchingImageJob(transientMessage), true);

await runNextTimeout(4000);
assert.equal(transientCalls, 4);
assert.equal(recovery.isWatchingImageJob(transientMessage), true);

await runNextTimeout(8000);
assert.equal(transientCalls, 5);
assert.equal(transientMessage.image_job.status, 'running');
assert.equal(recovery.isWatchingImageJob(transientMessage), true);

// A successful status response resets failure recovery and returns to
// the normal one-second polling cadence.
assert.equal(timeouts.size, 1);

const normalPoll = timeouts.values().next().value;
assert.equal(normalPoll.delay, 1000);

stopAllWatchers();

const unavailableJobId = 'a'.repeat(24);
const unavailableMessage = storedMessage(
    'running',
    unavailableJobId,
);
const unavailableSession = session(
    'unavailable-session',
    [unavailableMessage],
);

let unavailableCalls = 0;

activeSession = unavailableSession;

fetchImpl = async () => {
    unavailableCalls += 1;
    throw new Error('image service unavailable');
};

assert.equal(
    recovery.resumeImageJobsForSession(
        unavailableSession
    ),
    1,
);

await settle();

// Initial failure schedules the first retry.
assert.equal(unavailableCalls, 1);
assert.equal(
    recovery.isWatchingImageJob(unavailableMessage),
    true,
);

for (const [index, delay] of [
    1000,
    2000,
    4000,
    8000,
    10000,
    10000,
    10000,
    10000,
].entries()) {
    await runNextTimeout(delay);

    if (index < 7) {
        assert.equal(
            recovery.isWatchingImageJob(
                unavailableMessage
            ),
            true,
        );
    }
}

// 1 initial request + 8 scheduled retries.
assert.equal(unavailableCalls, 9);

assert.equal(
    unavailableMessage.image_job.status,
    'failed',
);

assert.equal(
    unavailableMessage.image_job.recovery_status,
    'service_unavailable',
);

assert.match(
    unavailableMessage.content,
    /could not be reached after several retries/,
);

assert.equal(
    recovery.isWatchingImageJob(unavailableMessage),
    false,
);

assert.equal(timeouts.size, 0);

const cancelJobId = '6'.repeat(24);
const cancelMessage = storedMessage('running', cancelJobId);
const cancelSession = session('cancel-session', [cancelMessage]);
let cancelPoll = 0;
activeSession = cancelSession;
fetchImpl = async () => {
    cancelPoll += 1;
    return response(toolResult(
        cancelPoll === 1 ? 'running' : 'cancelled',
        cancelJobId,
        { currentStep: cancelPoll === 1 ? 1 : null },
    ));
};

assert.equal(recovery.resumeImageJobsForSession(cancelSession), 1);
await settle();
await runNextTimeout();
assert.equal(cancelMessage.image_job.status, 'cancelled');
assert.equal(cancelMessage.tool_result.artifacts.length, 0);
assert.equal(cancelSession.workspace.active_artifact_id, 'image-old');
assert.equal(recovery.isWatchingImageJob(cancelMessage), false);
assert.equal(timeouts.size, 0);

const delayedJobId = '7'.repeat(24);
const delayedMessage = storedMessage('running', delayedJobId);
const sessionA = session('session-a', [delayedMessage]);
const sessionB = session('session-b', []);
let resolveDelayed;
fetchImpl = () => new Promise(resolve => {
    resolveDelayed = resolve;
});
activeSession = sessionA;
assert.equal(recovery.resumeImageJobsForSession(sessionA), 1);

activeSession = sessionB;
assert.equal(recovery.resumeImageJobsForSession(sessionB), 0);
assert.equal(recovery.isWatchingImageJob(delayedMessage), false);
resolveDelayed(response(toolResult('completed', delayedJobId, {
    artifact: imageArtifact,
    currentStep: 8,
})));
await settle();
assert.equal(delayedMessage.image_job.status, 'running');
assert.equal(sessionA.workspace.active_artifact_id, 'image-old');
assert.equal(sessionB.messages.length, 0);

fetchImpl = async () => response(toolResult('running', delayedJobId, {
    currentStep: 1,
}));
activeSession = sessionA;
assert.equal(recovery.resumeImageJobsForSession(sessionA), 1);
await settle();
assert.equal(recovery.isWatchingImageJob(delayedMessage), true);
stopAllWatchers();

const ignoredSession = session('ignored-session', [
    storedMessage('completed', '8'.repeat(24), {artifact: imageArtifact}),
    storedMessage('running', 'invalid-job-id'),
    storedMessage('running', '9'.repeat(24), { tool: 'normal_chat' }),
    { role: 'assistant', content: 'Text only' },
]);
activeSession = ignoredSession;
requests.length = 0;
fetchImpl = async () => {
    throw new Error('ignored jobs must not be polled');
};
assert.equal(recovery.resumeImageJobsForSession(ignoredSession), 0);
await settle();
assert.equal(requests.length, 0);
assert.equal(timeouts.size, 0);

const loadSessionsIndex = chatSource.indexOf(
    'MLXChatSessions.loadSessions();',
);
const initialResumeIndex = chatSource.indexOf(
    'MLXChatGeneration.resumeImageJobsForSession(',
    loadSessionsIndex,
);
const syncWithServerIndex = chatSource.indexOf(
    'MLXChatSessions.syncWithServer();',
    loadSessionsIndex,
);
assert.ok(loadSessionsIndex >= 0);
assert.ok(initialResumeIndex > loadSessionsIndex);
assert.ok(syncWithServerIndex > initialResumeIndex);
assert.match(
    chatSource,
    /onSessionSelected:\s*\(\)\s*=>\s*{[\s\S]*?resumeImageJobsForSession\([\s\S]*?currentSession\(\)/,
);

assert.ok(saves > 0);
assert.ok(renders > 0);
assert.equal(warnings.length, 13);

// The start API may report completion before it attaches a public artifact.
const earlyMessage = {role: 'assistant', content: '', image_generation_pending: true};
const earlySession = session('early-image-completion', [earlyMessage]);
activeSession = earlySession;
assert.equal(recovery.updateImageJobMessage(earlySession, earlyMessage,
    toolResult('completed', 'a'.repeat(24))), false);
assert.equal(earlyMessage.image_job.status, 'saving');
fetchImpl = async () => response(toolResult('completed', 'a'.repeat(24)));
assert.equal(recovery.resumeImageJobsForSession(earlySession), 1);
await settle();
assert.equal(earlyMessage.image_generation_pending, true);
assert.equal(timeouts.size, 1, 'completed without an artifact continues polling');
fetchImpl = async () => response(toolResult('completed', 'a'.repeat(24), {artifact: imageArtifact}));
const [earlyTimerId, earlyTimer] = timeouts.entries().next().value;
timeouts.delete(earlyTimerId); earlyTimer.callback();
await settle();
assert.equal(earlyMessage.image_job.status, 'completed');
assert.equal(earlyMessage.image_generation_pending, false);
assert.equal(earlyMessage.tool_result.artifacts[0].image_id, imageArtifact.image_id);
assert.equal(timeouts.size, 0);

const unboundMessage = storedMessage('running', 'b'.repeat(24));
delete unboundMessage.image_job;
const unboundSession = session('unbound-image-job', [unboundMessage]);
activeSession = unboundSession;
fetchImpl = async () => response(toolResult('failed', 'b'.repeat(24), {error: 'fixture failed'}));
assert.equal(recovery.resumeImageJobsForSession(unboundSession), 1);
await settle();
assert.equal(unboundMessage.image_job.status, 'failed');
assert.match(unboundMessage.content, /fixture failed/);
assert.equal(timeouts.size, 0);

console.log(
    'Image job resume: restore, source of truth, retries, idempotency, ' +
    'session isolation, completion, failure, cancellation, and 404 passed.',
);

const publicationMessage = storedMessage('running', 'c'.repeat(24), {tool: 'image_generate'});
const publicationSession = session('publication-deadline', [publicationMessage]);
const incomplete = toolResult('completed', 'c'.repeat(24), {tool: 'image_generate'});
assert.equal(recovery.updateImageJobMessage(publicationSession, publicationMessage, incomplete, 100), false);
assert.equal(publicationMessage.image_job.status, 'saving');
const reloadedPublication = JSON.parse(JSON.stringify(publicationMessage));
assert.equal(reloadedPublication.image_artifact_wait_started_at, 100);
assert.equal(recovery.updateImageJobMessage(publicationSession, reloadedPublication, incomplete, 159), false);
assert.equal(recovery.updateImageJobMessage(publicationSession, reloadedPublication, incomplete, 160), true);
assert.equal(reloadedPublication.image_job.status, 'failed');
assert.match(reloadedPublication.content, /could not be published/);
assert.equal(reloadedPublication.image_generation_pending, false);
assert.equal(recovery.updateImageJobMessage(publicationSession, publicationMessage,
    toolResult('completed', 'c'.repeat(24), {tool: 'image_generate', artifact: imageArtifact}), 159), true);
assert.equal(publicationMessage.image_artifact_wait_started_at, undefined);
assert.equal(publicationMessage.tool_result.artifacts[0].image_id, imageArtifact.image_id);

const completedWithoutArtifact = storedMessage('completed', 'd'.repeat(24), {tool: 'image_generate'});
const completedWithoutArtifactSession = session('incomplete-reload', [completedWithoutArtifact]);
activeSession = completedWithoutArtifactSession;
fetchImpl = async () => response(toolResult('failed', 'd'.repeat(24), {error: 'Publication failed'}));
assert.equal(recovery.resumeImageJobsForSession(completedWithoutArtifactSession), 1);
await settle();
assert.match(completedWithoutArtifact.content, /Publication failed/);
assert.equal(timeouts.size, 0);

// Server synchronization replaces recovered message objects in the same
// session. Retire their old watchers before starting the replacement messages.
const replacedMessage = storedMessage('queued', 'e'.repeat(24), {tool: 'image_generate'});
const replacedSession = session('variant-reload-server-sync', [replacedMessage]);
activeSession = replacedSession;
fetchImpl = async () => response(toolResult('queued', 'e'.repeat(24), {tool: 'image_generate'}));
assert.equal(recovery.resumeImageJobsForSession(replacedSession), 1);
await settle();
assert.equal(timeouts.size, 1);
const replacementMessage = JSON.parse(JSON.stringify(replacedMessage));
replacedSession.messages = [replacementMessage];
fetchImpl = async () => response(toolResult('completed', 'e'.repeat(24), {tool: 'image_generate', artifact: imageArtifact}));
assert.equal(recovery.resumeImageJobsForSession(replacedSession), 1);
await settle();
assert.equal(replacementMessage.image_job.status, 'completed');
assert.equal(replacementMessage.tool_result.artifacts[0].image_id, imageArtifact.image_id);
assert.equal(timeouts.size, 0);
