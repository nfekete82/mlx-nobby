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
            artifacts: [],
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

async function runNextTimeout() {
    const entry = timeouts.entries().next().value;
    assert.ok(entry, 'expected a scheduled image-job poll');
    const [id, timer] = entry;
    timeouts.delete(id);
    assert.equal(timer.delay, 1000);
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
    if (transientCalls === 1) {
        throw new Error('temporary connection failure');
    }
    return response(toolResult('running', transientJobId, {
        currentStep: 1,
    }));
};

assert.equal(recovery.resumeImageJobsForSession(transientSession), 1);
await settle();
assert.equal(transientMessage.image_job.status, 'running');
assert.equal(recovery.isWatchingImageJob(transientMessage), true);
assert.equal(timeouts.size, 1);
await runNextTimeout();
assert.equal(transientCalls, 2);
assert.equal(transientMessage.image_job.status, 'running');
assert.equal(recovery.isWatchingImageJob(transientMessage), true);
stopAllWatchers();

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
    storedMessage('completed', '8'.repeat(24)),
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
assert.equal(warnings.length, 1);

console.log(
    'Image job resume: restore, source of truth, retries, idempotency, ' +
    'session isolation, completion, failure, cancellation, and 404 passed.',
);
