(function () {
    const commonScript = document.currentScript;
    const commonScriptUrl = commonScript?.src
        ? new URL(commonScript.src, window.location.href)
        : null;
    const frontendBuildRevision = commonScriptUrl?.searchParams.get('v') || '';
    const CHAT_STORAGE_KEY = 'mlx-web-chats-v1';

    function chatHasUserMessage(session) {
        return Boolean(
            session &&
            Array.isArray(session.messages) &&
            session.messages.some(message => message?.role === 'user')
        );
    }

    function parseStoredChats() {
        try {
            const chats = JSON.parse(
                window.localStorage?.getItem(CHAT_STORAGE_KEY) || '[]'
            );
            return Array.isArray(chats) ? chats : [];
        } catch (_) {
            return [];
        }
    }

    function sanitizeStoredChats() {
        try {
            const chats = parseStoredChats();
            const visibleChats = chats.filter(chatHasUserMessage);

            if (visibleChats.length !== chats.length) {
                window.localStorage?.setItem(
                    CHAT_STORAGE_KEY,
                    JSON.stringify(visibleChats)
                );
            }
        } catch (_) {
            // localStorage is only a cache; server persistence remains available.
        }
    }

    function chatApiPath(url) {
        try {
            return new URL(url, window.location.href).pathname;
        } catch (_) {
            return String(url || '').split('?')[0];
        }
    }

    function requestJsonBody(options) {
        if (!options?.body || typeof options.body !== 'string') {
            return null;
        }

        try {
            return JSON.parse(options.body);
        } catch (_) {
            return null;
        }
    }

    async function fetchJson(url, options) {
        const path = chatApiPath(url);
        const method = String(options?.method || 'GET').toUpperCase();

        /*
         * A freshly opened chat is only a local draft. Do not persist it
         * until the user has actually sent the first message.
         */
        if (
            method === 'PUT' &&
            /^\/api\/mlx\/chats\/[^/]+$/.test(path)
        ) {
            const chat = requestJsonBody(options);

            if (chat && !chatHasUserMessage(chat)) {
                return {
                    response: {
                        ok: true,
                        status: 200
                    },
                    data: {
                        chat: chat
                    }
                };
            }
        }

        const response = await fetch(url, options);
        const data = await response.json();

        /*
         * Older builds persisted empty "New chat" sessions. Keep them out
         * of the history and remove those stale server records lazily.
         */
        if (
            method === 'GET' &&
            path === '/api/mlx/chats' &&
            Array.isArray(data?.chats)
        ) {
            const emptyChats = data.chats.filter(
                chat => !chatHasUserMessage(chat)
            );

            data.chats = data.chats.filter(chatHasUserMessage);

            emptyChats.forEach(chat => {
                if (!chat?.id) return;

                fetch(
                    '/api/mlx/chats/' + encodeURIComponent(chat.id),
                    { method: 'DELETE' }
                ).catch(() => {});
            });
        }

        return {
            response: response,
            data: data
        };
    }

    function fastApiDetailError(data) {
        return new Error(
            typeof data.detail === 'string'
                ? data.detail
                : JSON.stringify(data.detail)
        );
    }

    function jsonRequest(method, data) {
        return {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        };
    }

    function versionedAssetUrl(src) {
        if (!frontendBuildRevision) return src;

        const url = new URL(src, window.location.href);
        url.searchParams.set('build', frontendBuildRevision);
        return `${url.pathname}${url.search}${url.hash}`;
    }

    function loadScript(src, datasetKey) {
        return new Promise((resolve, reject) => {
            const selector = `script[data-${datasetKey}]`;
            const existing = document.querySelector(selector);
            if (existing) {
                if (existing.dataset.loaded === '1') {
                    resolve();
                } else {
                    existing.addEventListener('load', resolve, { once: true });
                    existing.addEventListener('error', reject, { once: true });
                }
                return;
            }

            const script = document.createElement('script');
            script.src = versionedAssetUrl(src);
            script.setAttribute(`data-${datasetKey}`, '1');
            script.addEventListener('load', () => {
                script.dataset.loaded = '1';
                resolve();
            }, { once: true });
            script.addEventListener('error', reject, { once: true });
            document.head.appendChild(script);
        });
    }

    function ensureHelpVisibilityFix() {
        if (document.getElementById('mlxHelpVisibilityFix')) return;

        const style = document.createElement('style');
        style.id = 'mlxHelpVisibilityFix';
        style.textContent = [
            '.mlx-help-backdrop[hidden],',
            '.mlx-help-panel[hidden]{display:none!important;}'
        ].join('');
        document.head.appendChild(style);
    }

    function ensureTopbarActionCleanup() {
        if (document.getElementById('mlxTopbarActionCleanup')) return;

        const style = document.createElement('style');
        style.id = 'mlxTopbarActionCleanup';
        style.textContent = '#settingsButton,#mlxHelpButton{display:none!important;}';
        document.head.appendChild(style);
    }

    function removeRedundantTopActions() {
        document.getElementById('settingsButton')?.remove();
        document.getElementById('mlxHelpButton')?.remove();
    }

    function ensureChatHistoryPolish() {
        const chatList = document.getElementById('chatList');
        const input = document.getElementById('input');

        if (!chatList || !input) return;

        if (!document.getElementById('mlxChatHistoryPolish')) {
            const style = document.createElement('style');
            style.id = 'mlxChatHistoryPolish';
            style.textContent = [
                '@media (min-width:901px){',
                '.app.sidebar-collapsed .empty{',
                'transform:translateX(112px);',
                '}',
                '}'
            ].join('');
            document.head.appendChild(style);
        }

        const normalizeTitle = value =>
            String(value || '').trim().toLocaleLowerCase();

        const draftTitles = () => new Set([
            normalizeTitle('New chat'),
            normalizeTitle(
                window.MLXI18n?.t?.('ui.new_chat', 'New chat')
            ),
            normalizeTitle(
                window.MLXI18n?.t?.('sessions.new_chat', 'New chat')
            )
        ]);

        const hideDraftEntries = () => {
            sanitizeStoredChats();

            const titles = draftTitles();
            const persistedDraftCounts = new Map();

            parseStoredChats()
                .filter(chatHasUserMessage)
                .forEach(chat => {
                    const title = normalizeTitle(chat?.title);
                    if (!titles.has(title)) return;
                    persistedDraftCounts.set(
                        title,
                        (persistedDraftCounts.get(title) || 0) + 1
                    );
                });

            const candidatesByTitle = new Map();

            chatList
                .querySelectorAll('.chat-entry-wrap')
                .forEach(wrap => {
                    const entry = wrap.querySelector('.chat-entry');
                    const title = normalizeTitle(entry?.textContent);

                    wrap.hidden = false;

                    if (!titles.has(title)) return;

                    const candidates = candidatesByTitle.get(title) || [];
                    candidates.push(wrap);
                    candidatesByTitle.set(title, candidates);
                });

            candidatesByTitle.forEach((candidates, title) => {
                const persistedCount = persistedDraftCounts.get(title) || 0;
                const draftsToHide = Math.max(
                    0,
                    candidates.length - persistedCount
                );

                for (let index = 0; index < draftsToHide; index++) {
                    candidates[index].hidden = true;
                }
            });
        };

        const observer = new MutationObserver(hideDraftEntries);
        observer.observe(chatList, {
            childList: true,
            subtree: true,
            characterData: true
        });

        hideDraftEntries();

        const sessions = window.MLXChatSessions;
        if (
            sessions?.createSession &&
            !sessions.createSession.__mlxDraftGuard
        ) {
            const originalCreateSession = sessions.createSession.bind(sessions);

            const guardedCreateSession = function (...args) {
                const current = sessions.currentSession?.();

                if (current && !chatHasUserMessage(current)) {
                    input.focus();
                    hideDraftEntries();
                    return;
                }

                return originalCreateSession(...args);
            };

            guardedCreateSession.__mlxDraftGuard = true;
            sessions.createSession = guardedCreateSession;
        }
    }

    function experimentalVoiceStreamingEnabled() {
        try {
            return window.localStorage?.getItem('mlx-nobby-voice-streaming') === '1';
        } catch (_) {
            return false;
        }
    }

    async function loadChatPerformance() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/performance.js?v=20260929-perf-v1',
                'mlx-chat-performance'
            );
        } catch (error) {
            console.error('[performance] Failed to load chat performance layer:', error);
        }
    }

    async function loadChatVoiceControls() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/voice.js?v=20260928-voice-defaults-v2',
                'mlx-voice-controls'
            );
            await loadScript(
                '/assets/chat/voice-loading.js?v=20260928-voice-loading-v1',
                'mlx-voice-loading'
            );
            await loadScript(
                '/assets/chat/voice-manager.js?v=20260928-voice-manager-v1',
                'mlx-voice-manager'
            );
            if (experimentalVoiceStreamingEnabled()) {
                await loadScript(
                    '/assets/chat/voice-streaming.js?v=20260928-voice-streaming-v2',
                    'mlx-voice-streaming'
                );
            }
            await loadScript(
                '/assets/chat/tts-cache.js?v=20260926-tts-cache',
                'mlx-tts-cache'
            );
            await loadScript(
                '/assets/chat/user-voice.js?v=20260926-user-voice-2',
                'mlx-user-voice-controls'
            );
        } catch (error) {
            console.error('[voice] Failed to load voice controls:', error);
        }
    }

    async function loadModelConsoleEnhancers() {
        if (!document.getElementById('modelConsoleContent')) return;
        try {
            await loadScript(
                '/assets/chat/model-overview.js?v=20260927-overview-v1',
                'model-overview-enhancer'
            );
            await loadScript(
                '/assets/chat/model-path-validation.js?v=20260927-validation-v2',
                'model-path-validator'
            );
        } catch (error) {
            console.error('[models] Failed to load model console enhancements:', error);
        }
    }

    async function loadHelpCenter() {
        if (!document.getElementById('input')) return;
        try {
            ensureHelpVisibilityFix();
            await loadScript(
                '/assets/chat/help.js?v=20260927-help-v1',
                'mlx-help-center'
            );
            removeRedundantTopActions();
        } catch (error) {
            console.error('[help] Failed to load help center:', error);
        }
    }

    async function loadRuntimeReliability() {
        if (!document.getElementById('runtimeInfoButton')) return;
        try {
            await loadScript(
                '/assets/chat/runtime-reliability.js?v=20260928-runtime-reliability-v1',
                'mlx-runtime-reliability'
            );
        } catch (error) {
            console.error('[runtime-reliability] Failed to load runtime reliability:', error);
        }
    }

    async function loadRuntimeBudget() {
        if (!document.getElementById('runtimeInfoButton')) return;
        try {
            await loadScript(
                '/assets/chat/runtime-budget.js?v=20260927-runtime-budget-v1',
                'mlx-runtime-budget'
            );
        } catch (error) {
            console.error('[runtime-budget] Failed to load runtime budget:', error);
        }
    }

    async function loadJobQueue() {
        if (!document.getElementById('jobsPanel')) return;
        try {
            await loadScript(
                '/assets/chat/job-queue.js?v=20260927-unified-queue-v1',
                'mlx-unified-job-queue'
            );
        } catch (error) {
            console.error('[job-queue] Failed to load unified job queue:', error);
        }
    }

    async function loadShortsHistory() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/shorts-history.js?v=20260928-shorts-history-v1',
                'mlx-shorts-history'
            );
        } catch (error) {
            console.error('[shorts-history] Failed to load Shorts project browser:', error);
        }
    }

    async function loadImageCountPicker() {
        if (!document.getElementById('mediaQualityModal')) return;
        try {
            await loadScript(
                '/assets/chat/image-count-picker.js?v=20260929-image-count-v2',
                'mlx-image-count-picker'
            );
        } catch (error) {
            console.error('[image-count] Failed to load image count picker:', error);
        }
    }

    async function loadGalleryLanguageSync() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/gallery-language-sync.js?v=20260929-gallery-i18n-v1',
                'mlx-gallery-language-sync'
            );
        } catch (error) {
            console.error('[gallery-i18n] Failed to load gallery language sync:', error);
        }
    }

    async function loadAppVersion() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/app-version.js?v=20260929-version-v1',
                'mlx-app-version'
            );
        } catch (error) {
            console.error('[version] Failed to load app version UI:', error);
        }
    }

    function loadChatEnhancements() {
        removeRedundantTopActions();
        ensureChatHistoryPolish();
        loadChatPerformance();
        loadRuntimeReliability();
        loadChatVoiceControls();
        loadModelConsoleEnhancers();
        loadHelpCenter();
        loadRuntimeBudget();
        loadJobQueue();
        loadShortsHistory();
        loadImageCountPicker();
        loadGalleryLanguageSync();
        loadAppVersion();
    }

    window.MLXCommon = {
        fetchJson: fetchJson,
        fastApiDetailError: fastApiDetailError,
        jsonRequest: jsonRequest
    };

    sanitizeStoredChats();
    ensureTopbarActionCleanup();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadChatEnhancements, { once: true });
    } else {
        loadChatEnhancements();
    }
})();
