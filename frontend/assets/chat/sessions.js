function sessionT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [varName, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${varName}}`,
            String(replacement ?? '')
        );
    }

    return value;
}

(function () {
    const STORAGE_KEY = 'mlx-web-chats-v1';

    let state;
    let renderAll;
    let renderSidebar;
    let isGenerating;
    let createSessionSettings;
    let onSessionSelected;
    let serverReady = false;
    let serverSyncing = false;

    function configure(options) {
        state = options.state;
        renderAll = options.renderAll;
        renderSidebar = options.renderSidebar;
        isGenerating = options.isGenerating;
        createSessionSettings = options.createSessionSettings;
        onSessionSelected = options.onSessionSelected;
    }

    function uid() {
        return crypto.randomUUID();
    }

    function withoutStreamingFields(value) {
        if (Array.isArray(value)) {
            return value.map(withoutStreamingFields);
        }

        if (value && typeof value === 'object') {
            const clean = {};

            Object.entries(value).forEach(([key, item]) => {
                if (key !== '_thinkingStarted') {
                    clean[key] = withoutStreamingFields(item);
                }
            });

            return clean;
        }

        return value;
    }

    function validSession(session) {
        return (
            session &&
            typeof session.id === 'string' &&
            typeof session.title === 'string' &&
            Number.isFinite(session.created) &&
            Number.isFinite(session.updated) &&
            Array.isArray(session.messages)
        );
    }

    function withoutHeavyCacheFields(value) {

        if (Array.isArray(value)) {

            return value.map(withoutHeavyCacheFields);

        }

        if (value && typeof value === 'object') {

            const clean = {};

            Object.entries(value).forEach(([key, item]) => {

                if (
                    key === '_thinkingStarted' ||
                    key === 'data_url' ||
                    key === 'file' ||
                    key === 'blob' ||
                    key === 'raw_content' ||
                    key === 'binary' ||
                    key === 'bytes'
                ) {
                    return;
                }

                clean[key] = withoutHeavyCacheFields(item);

            });

            return clean;

        }

        return value;

    }


    function cacheSessions() {

        try {

            const lightweightSessions = state.sessions.map(
                withoutHeavyCacheFields
            );

            localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify(lightweightSessions)
            );

        } catch (error) {

            if (
                error &&
                (
                    error.name === 'QuotaExceededError' ||
                    error.name === 'NS_ERROR_DOM_QUOTA_REACHED'
                )
            ) {

                console.warn(
                    '[MLX nobby] Local chat cache full. ' +
                    'Server persistence remains active.',
                    error
                );

                try {
                    localStorage.removeItem(STORAGE_KEY);
                } catch {}

                return;

            }

            console.error(
                '[MLX nobby] Failed to cache sessions:',
                error
            );

        }

    }

    function updateFromServer(session, serverSession, keepMessages) {
        const messages = session.messages;
        const { _runtime_revision, ...serverFields } = serverSession;

        Object.assign(session, serverFields);

        if (keepMessages) {
            session.messages = messages;
        }
    }


    async function persistSession(session) {
        if (!serverReady || !validSession(session)) {
            return;
        }

        try {
            const sentSession = withoutStreamingFields(session);
            const sentMessages = JSON.stringify(sentSession.messages);
            const {
                response,
                data
            } = await MLXCommon.fetchJson(
                '/api/mlx/chats/' + encodeURIComponent(session.id),
                MLXCommon.jsonRequest(
                    'PUT',
                    sentSession
                )
            );

            if (!response.ok || !validSession(data.chat)) {
                return;
            }

            if (data.chat.updated > session.updated) {
                const current = state.sessions.find(
                    item => item.id === session.id
                );

                if (current === session) {
                    updateFromServer(
                        session,
                        data.chat,
                        (isGenerating() && state.activeId === session.id) ||
                            JSON.stringify(
                                withoutStreamingFields(session.messages)
                            ) !== sentMessages
                    );
                    cacheSessions();
                    renderAll();
                }
            }

        } catch {}
    }

    async function deleteServerSession(id) {
        if (!serverReady) {
            return;
        }

        try {
            await fetch(
                '/api/mlx/chats/' + encodeURIComponent(id),
                { method: 'DELETE' }
            );
        } catch {}
    }

    function loadSessions() {
        try {
            const cached = JSON.parse(
                localStorage.getItem(STORAGE_KEY)
            ) || [];

            state.sessions = cached.filter(validSession);
        } catch {
            state.sessions = [];
        }

        if (state.sessions.length) {
            state.activeId = state.sessions[0].id;
        }
    }

    function saveSessions() {
        cacheSessions();

        if (serverReady) {
            state.sessions.forEach(persistSession);
        }
    }

    async function syncWithServer() {
        if (serverSyncing) {
            return;
        }

        serverSyncing = true;

        try {
            const {
                response,
                data
            } = await MLXCommon.fetchJson('/api/mlx/chats');

            if (!response.ok || !Array.isArray(data.chats)) {
                return;
            }

            const localById = new Map(
                state.sessions
                    .filter(validSession)
                    .map(session => [session.id, session])
            );

            const serverById = new Map(
                data.chats
                    .filter(validSession)
                    .map(session => [session.id, session])
            );

            const merged = new Map();
            const localWinners = [];

            new Set([
                ...localById.keys(),
                ...serverById.keys()
            ]).forEach(id => {
                const local = localById.get(id);
                const server = serverById.get(id);

                if (!server || (local && local.updated > server.updated)) {
                    merged.set(id, local);
                    localWinners.push(local);
                    return;
                }

                if (local) {
                    updateFromServer(
                        local,
                        server,
                        isGenerating() && state.activeId === id
                    );
                }
                merged.set(id, local || server);
            });

            state.sessions = Array.from(merged.values())
                .sort((left, right) => right.updated - left.updated);

            if (
                !state.sessions.some(
                    session => session.id === state.activeId
                )
            ) {
                state.activeId = state.sessions[0]?.id || null;
            }

            serverReady = true;

            if (!state.sessions.length) {
                createSession();
                return;
            }

            cacheSessions();
            localWinners.forEach(persistSession);
            onSessionSelected();
            renderAll();

        } catch {
            // Keep localStorage as the fallback when the agent is unavailable.
            if (!state.sessions.length) {
                createSession();
            }
        } finally {
            serverSyncing = false;
        }
    }

    function currentSession() {
        return state.sessions.find(
            item => item.id === state.activeId
        );
    }

    function runtimeRevision(session) {
        const value = Number(session?._runtime_revision);
        return Number.isSafeInteger(value) && value >= 0
            ? value
            : 0;
    }

    function bumpRuntimeRevision(session) {
        if (!session) {
            return 0;
        }

        const next = runtimeRevision(session) + 1;

        Object.defineProperty(
            session,
            '_runtime_revision',
            {
                value: next,
                writable: true,
                configurable: true,
                enumerable: false
            }
        );

        return next;
    }

    function runtimeRevisionIsCurrent(session, revision) {
        return (
            Boolean(session) &&
            currentSession() === session &&
            runtimeRevision(session) === revision
        );
    }

    function createSession() {
        const session = {
            id: uid(),
            title: sessionT('sessions.new_chat', 'New chat'),
            created: Date.now(),
            updated: Date.now(),
            revision: 0,
            messages: [],
            settings: createSessionSettings()
        };

        state.sessions.unshift(session);
        state.activeId = session.id;

        onSessionSelected();
        saveSessions();
        renderAll();
    }

    function renameSession(id) {
        const session = state.sessions.find(
            item => item.id === id
        );

        if (!session) return;

        const name = prompt(
            sessionT('sessions.rename', 'Rename chat:'),
            session.title || sessionT('sessions.new_chat', 'New chat')
        );

        if (name === null) return;

        const title = name.trim();

        if (!title) return;

        session.title = title;
        session.updated = Date.now();

        saveSessions();
        renderSidebar();
    }

    function deleteSession(id) {
        if (isGenerating()) return;

        const session = state.sessions.find(
            item => item.id === id
        );

        if (!session) return;

        if (!confirm(
            sessionT(
            'sessions.delete_confirm',
            'Really delete chat "{name}"?',
            {
                name:
                    session.title ||
                    sessionT('sessions.new_chat', 'New chat')
            }
        )
        )) {
            return;
        }

        state.sessions = state.sessions.filter(
            item => item.id !== id
        );

        deleteServerSession(id);

        if (!state.sessions.length) {
            createSession();
            return;
        }

        if (state.activeId === id) {
            state.activeId = state.sessions[0].id;
        }

        saveSessions();
        renderAll();
    }

    async function deleteMessages() {
        const session = currentSession();

        if (!session) {
            return;
        }

        if (session.messages.length) {
            const confirmFn = window.MLXConfirm;

            if (typeof confirmFn !== 'function') {
                console.error(
                    'MLX confirmation modal is unavailable'
                );
                return;
            }

            const confirmed = await confirmFn({
                title: sessionT(
                    'ui.clear_chat',
                    'Chat leeren'
                ),
                message: sessionT(
                    'ui.clear_chat_confirm',
                    'Diesen Chat wirklich leeren?'
                ),
                confirmLabel: sessionT(
                    'ui.clear_chat',
                    'Leeren'
                ),
                cancelLabel: sessionT(
                    'ui.cancel',
                    'Cancel'
                ),
            });

            if (!confirmed) {
                return;
            }
        }

        // Invalidate every async operation that started before this reset.
        // The revision is runtime-only and intentionally not persisted.
        bumpRuntimeRevision(session);

        // Stop active runtime work before removing message/job state.
        await window.MLXChatGeneration?.resetSessionRuntime?.(session);

        // Reset the persisted chat on the backend. This also removes
        // locally generated images referenced by this chat.
        if (serverReady) {
            try {
                const response = await fetch(
                    '/api/mlx/chats/' +
                        encodeURIComponent(session.id) +
                        '/reset',
                    { method: 'POST' }
                );

                if (!response.ok) {
                    console.warn(
                        'Chat backend reset failed:',
                        response.status
                    );
                } else {
                    const resetResult = await response.json();
                    const revision = resetResult?.chat?.revision;

                    if (
                        Number.isSafeInteger(revision) &&
                        revision >= 0
                    ) {
                        session.revision = revision;
                    }
                }
            } catch (error) {
                console.warn(
                    'Chat backend reset failed:',
                    error
                );
            }
        }

        session.messages = [];

        // Clearing a chat must also detach generated-image context.
        if (session.workspace) {
            delete session.workspace.active_artifact_id;

            if (!Object.keys(session.workspace).length) {
                delete session.workspace;
            }
        }

        // A cleared chat starts without an active code workspace.
        // The workspace remains registered and can be selected again.
        try {
            await window.MLXChatWorkspace?.deactivate?.();
        } catch (error) {
            console.warn(
                'Workspace deactivation during chat reset failed:',
                error
            );
        }

        // Clear transient frontend files/images.
        window.MLXChatAttachments?.clearAttachments?.();

        session.title = sessionT(
            'sessions.new_chat',
            'New chat'
        );
        session.updated = Date.now();

        saveSessions();
        renderAll();
    }

    function updateTitle(session) {
        if (session.title !== sessionT('sessions.new_chat', 'New chat')) {
            return;
        }

        const first = session.messages.find(
            message => message.role === 'user'
        );

        if (!first) return;

        let title = first.content
            .replace(/\s+/g, ' ')
            .trim();

        if (title.length > 42) {
            title = title.slice(0, 42) + '…';
        }

        session.title = title || sessionT('sessions.new_chat', 'New chat');
    }

    function selectSession(id) {
        if (isGenerating()) return;

        state.activeId = id;
        onSessionSelected();
        renderAll();
    }

    function safeFileName(value) {
        return (value || 'chat')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 60) || 'chat';
    }

    function exportDate() {
        return new Date().toISOString().slice(0, 10);
    }

    function download(text, type, name) {
        const url = URL.createObjectURL(new Blob([text], { type }));
        const link = document.createElement('a');

        link.href = url;
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 0);
    }

    function exportCurrentJson() {
        const session = currentSession();

        if (!session) return;

        download(
            JSON.stringify(withoutStreamingFields(session), null, 2),
            'application/json',
            'mlx-chat-' + safeFileName(session.title) + '-' + exportDate() + '.json'
        );
    }

    function exportCurrentMarkdown() {
        const session = currentSession();

        if (!session) return;

        const lines = [
            '# ' + (session.title || sessionT('sessions.new_chat', 'New chat')),
            '',
            '_' +
            sessionT('sessions.created', 'Created') +
            ': ' +
            new Date(session.created).toLocaleString(
                window.MLXI18n?.getLocale?.() || 'en-US'
            ) +
            '_',
            ''
        ];

        if (session.settings) {
            lines.push(
                '_Preset: ' + (session.settings.preset_id || 'custom') +
                ' · Temperature: ' + session.settings.temperature +
                ' · Max Tokens: ' + session.settings.max_tokens + '_',
                ''
            );
        }

        session.messages.forEach(message => {
            lines.push('## ' + (message.role === 'assistant' ? 'Assistant' : 'User'), '', message.display_content ?? message.content ?? '', '');
            if (message.reasoning) lines.push('### Thinking', '', message.reasoning, '');
            if (message.attachments?.length) lines.push('_' +
                sessionT('sessions.attachments', 'Attachments') +
                ': ' +
                message.attachments
                    .map(file => file.name + ' (' + file.size + ' Bytes)')
                    .join(', ') +
                '_', '');
            if (message.metrics) lines.push('_' + sessionT('sessions.metrics', 'Metrics') + ': ' + [message.metrics.estimated_tokens + ' Tokens', message.metrics.tokens_per_second != null ? message.metrics.tokens_per_second + ' tok/s' : null, message.metrics.total_ms != null ? (message.metrics.total_ms / 1000).toFixed(1) + ' s' : null].filter(Boolean).join(' · ') + '_', '');
        });

        download(lines.join('\n'), 'text/markdown;charset=utf-8', 'mlx-chat-' + safeFileName(session.title) + '-' + exportDate() + '.md');
    }

    function exportAllChats() {
        download(
            JSON.stringify({ version: 1, exported_at: new Date().toISOString(), chats: state.sessions.map(withoutStreamingFields) }, null, 2),
            'application/json',
            'mlx-chats-backup-' + exportDate() + '.json'
        );
    }

    function importBackup(text) {
        if (text.length > 20 * 1024 * 1024) {
            throw new Error(sessionT('sessions.backup_too_large', 'The backup file is larger than 20 MB'));
        }

        const data = JSON.parse(text);
        const chats = Array.isArray(data?.chats)
            ? data.chats
            : validSession(data) ? [data] : null;

        if (!chats) throw new Error(sessionT('sessions.invalid_backup', 'Invalid chat backup'));

        let imported = 0;

        chats.filter(validSession).forEach(chat => {
            const existing = state.sessions.find(item => item.id === chat.id);

            if (!existing || chat.updated > existing.updated) {
                if (existing) {
                    state.sessions[state.sessions.indexOf(existing)] = withoutStreamingFields(chat);
                } else {
                    state.sessions.push(withoutStreamingFields(chat));
                }
                imported++;
            }
        });

        state.sessions.sort((left, right) => right.updated - left.updated);
        if (!state.activeId && state.sessions.length) state.activeId = state.sessions[0].id;
        saveSessions();
        renderAll();

        return imported;
    }

    window.MLXChatSessions = {
        configure: configure,
        loadSessions: loadSessions,
        syncWithServer: syncWithServer,
        saveSessions: saveSessions,
        persistSession: persistSession,
        currentSession: currentSession,
        runtimeRevision: runtimeRevision,
        bumpRuntimeRevision: bumpRuntimeRevision,
        runtimeRevisionIsCurrent: runtimeRevisionIsCurrent,
        createSession: createSession,
        renameSession: renameSession,
        deleteSession: deleteSession,
        deleteMessages: deleteMessages,
        selectSession: selectSession,
        updateTitle: updateTitle,
        exportCurrentJson: exportCurrentJson,
        exportCurrentMarkdown: exportCurrentMarkdown,
        exportAllChats: exportAllChats,
        importBackup: importBackup
    };
})();
