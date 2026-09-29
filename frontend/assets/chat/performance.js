(function () {
    'use strict';

    const SAVE_THROTTLE_MS = 500;
    const MOUNT_RETRY_MS = 25;
    const MOUNT_RETRY_LIMIT = 200;

    let mountAttempts = 0;
    let mounted = false;
    let saveTimer = null;
    let lastSaveAt = 0;
    let savePending = false;
    let renderScheduled = false;
    let pendingRenderOptions = null;

    function nowMs() {
        return Date.now();
    }

    function mergeRenderOptions(current, next) {
        const left = current && typeof current === 'object' ? current : {};
        const right = next && typeof next === 'object' ? next : {};

        return {
            ...left,
            ...right,
            contentUpdated:
                Boolean(left.contentUpdated) ||
                Boolean(right.contentUpdated)
        };
    }

    function shouldCoalesceRender(options) {
        return Boolean(options?.contentUpdated);
    }

    function installPersistenceCoalescing(sessions) {
        const originalSaveSessions =
            sessions.saveSessions.bind(sessions);

        function runSave() {
            if (saveTimer != null) {
                clearTimeout(saveTimer);
                saveTimer = null;
            }

            if (!savePending) {
                return;
            }

            savePending = false;
            lastSaveAt = nowMs();
            originalSaveSessions();
        }

        function scheduleSave() {
            savePending = true;

            const elapsed = nowMs() - lastSaveAt;
            if (lastSaveAt === 0 || elapsed >= SAVE_THROTTLE_MS) {
                runSave();
                return;
            }

            if (saveTimer != null) {
                return;
            }

            saveTimer = setTimeout(
                runSave,
                Math.max(0, SAVE_THROTTLE_MS - elapsed)
            );
        }

        sessions.saveSessions = scheduleSave;
        sessions.flushSessions = function () {
            savePending = true;
            runSave();
        };

        return {
            flush: sessions.flushSessions,
            original: originalSaveSessions
        };
    }

    function installRenderCoalescing(rendering) {
        const originalRenderMessages =
            rendering.renderMessages.bind(rendering);

        function flushRender() {
            if (!renderScheduled) {
                return;
            }

            renderScheduled = false;
            const options = pendingRenderOptions || {};
            pendingRenderOptions = null;
            originalRenderMessages(options);
        }

        rendering.renderMessages = function (options = {}) {
            if (!shouldCoalesceRender(options)) {
                return originalRenderMessages(options);
            }

            pendingRenderOptions = mergeRenderOptions(
                pendingRenderOptions,
                options
            );

            if (renderScheduled) {
                return;
            }

            renderScheduled = true;

            if (typeof requestAnimationFrame === 'function') {
                requestAnimationFrame(flushRender);
            } else {
                setTimeout(flushRender, 0);
            }
        };

        rendering.flushMessages = flushRender;

        return {
            flush: flushRender,
            original: originalRenderMessages
        };
    }

    function mount() {
        if (mounted) {
            return true;
        }

        const sessions = window.MLXChatSessions;
        const rendering = window.MLXChatRendering;

        if (!sessions?.saveSessions || !rendering?.renderMessages) {
            mountAttempts += 1;
            if (mountAttempts < MOUNT_RETRY_LIMIT) {
                setTimeout(mount, MOUNT_RETRY_MS);
            } else {
                console.warn(
                    '[performance] Chat performance layer could not mount.'
                );
            }
            return false;
        }

        const persistence = installPersistenceCoalescing(sessions);
        const renderingLayer = installRenderCoalescing(rendering);

        const flushAll = () => {
            persistence.flush();
            renderingLayer.flush();
        };

        window.addEventListener?.('pagehide', flushAll);
        document.addEventListener?.('visibilitychange', () => {
            if (document.hidden) {
                persistence.flush();
            }
        });

        window.MLXChatPerformance = {
            mounted: true,
            flush: flushAll,
            saveThrottleMs: SAVE_THROTTLE_MS,
            __test: {
                mergeRenderOptions,
                shouldCoalesceRender,
                installPersistenceCoalescing,
                installRenderCoalescing
            }
        };

        mounted = true;
        return true;
    }

    window.MLXChatPerformance = {
        mounted: false,
        __test: {
            mergeRenderOptions,
            shouldCoalesceRender,
            installPersistenceCoalescing,
            installRenderCoalescing
        }
    };

    mount();
})();
