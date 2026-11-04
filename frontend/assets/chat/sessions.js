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
    let serverSyncCompleted = null;
    let finishServerSync = null;
    let clearingHistory = false;
    let confirmingHistory = false;
    let historyEpoch = 0;
    let persistEpoch = 0;
    const pendingPersists = new Set();
    // Track the server's acknowledged state separately from browser cache.
    // Saving one chat must not rewrite every other chat in a session list.
    const acknowledgedSnapshots = new Map();
    const acknowledgedUpdated = new Map();
    const activePersists = new Map();
    const CONFLICT_KEY = 'mlx-web-chats-pending-conflicts-v1';
    // Keep a durable marker when a concurrent edit cannot be reconciled while
    // a generation is active. No stale write may be retried under a fresh CAS.
    const pendingConflicts = new Map();
    const pendingCopyIds = new Map();
    const journalCopies = new Set();
    const journalSources = new Map();
    const journalKeys = new Map();
    const JOURNAL_PREFIX = CONFLICT_KEY + ':';

    async function reserveConflictId(session) {
        if (pendingCopyIds.has(session.id)) return;
        // The same rejected conversation from two tabs must converge on one
        // new record. Include the source ID so unrelated chats stay separate.
        const content = contentSnapshot({
            source: session.id, title: session.title,
            messages: session.messages, workspace: session.workspace ?? null,
        });
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
        const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
        pendingCopyIds.set(session.id, 'conflict-' + hash);
    }

    function journalKey(id) {
        if (!journalKeys.has(id)) journalKeys.set(id, new Set([JOURNAL_PREFIX + uid()]));
        return [...journalKeys.get(id)][0];
    }

    function journalConflict(session) {
        const copy = conflictCopy(session);
        copy.id = pendingCopyIds.get(session.id) || copy.id;
        pendingCopyIds.set(session.id, copy.id);
        journalCopies.add(copy.id);
        journalSources.set(copy.id, session.id);
        try {
            // One key per draft: another tab's whole-list cache cannot erase it.
            localStorage.setItem(journalKey(copy.id), JSON.stringify({
                sourceId: session.id,
                source: withoutHeavyCacheFields(session),
                copy: withoutHeavyCacheFields(copy),
            }));
        } catch (error) {
            console.warn('[MLX nobby] Could not journal conflict draft:', error);
        }
        return copy;
    }

    function forgetJournal(id) {
        journalCopies.delete(id);
        journalSources.delete(id);
        for (const key of journalKeys.get(id) || []) {
            try { localStorage.removeItem(key); } catch {}
        }
        journalKeys.delete(id);
    }

    function saveConflictMarkers() {
        try {
            for (const id of pendingConflicts.keys()) {
                const draft = state.sessions.find(item => item.id === id);
                if (draft) journalConflict(draft);
            }
            if (pendingConflicts.size) {
                localStorage.setItem(CONFLICT_KEY, JSON.stringify([...pendingConflicts.keys()]));
            } else {
                localStorage.removeItem(CONFLICT_KEY);
            }
        } catch (error) {
            console.warn('[MLX nobby] Could not persist chat conflict marker:', error);
        }
    }

    function clearConflictMarker(id) {
        for (const [copyId, sourceId] of journalSources) {
            if (copyId === id || sourceId === id) forgetJournal(copyId);
        }
        pendingCopyIds.delete(id);
        pendingConflicts.delete(id);
        saveConflictMarkers();
    }

    function conflictCopy(session) {
        const copy = withoutStreamingFields(session);
        copy.id = uid();
        copy.title = copy.title + ' (' +
            sessionT('sessions.concurrent_copy', 'Conflict copy') + ')';
        copy.created = Date.now();
        copy.updated = Date.now();
        return copy;
    }

    function recoverConflictedChats(copies = []) {
        if (isGenerating() || !pendingConflicts.size) return false;
        let changed = false;
        let activeChanged = false;
        for (const [id, serverChat] of [...pendingConflicts]) {
            const original = state.sessions.find(item => item.id === id);
            const needsCopy = original && (!serverChat || !sameConversationContent(original, serverChat));
            if (needsCopy) {
                // Never discard an in-flight local draft or overwrite the
                // version another tab saved. Preserve ours under a fresh ID.
                const copy = journalConflict(original);
                state.sessions.unshift(copy);
                copies.push(copy);
                if (state.activeId === id) {
                    state.activeId = copy.id;
                    activeChanged = true;
                }
                if (serverChat) {
                    updateFromServer(original, serverChat, false);
                } else {
                    // On reload the authoritative version comes from sync.
                    state.sessions = state.sessions.filter(item => item !== original);
                }
                changed = true;
            }
            if (original && serverChat && sameConversationContent(original, serverChat)) {
                const copyId = pendingCopyIds.get(id);
                if (!needsCopy && copyId) forgetJournal(copyId);
            }
            pendingCopyIds.delete(id);
            pendingConflicts.delete(id);
        }
        saveConflictMarkers();
        if (activeChanged) onSessionSelected();
        if (changed) renderSidebar();
        return changed;
    }

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

    function normalizeRecoveredMediaState(session) {
        if (!validSession(session)) {
            return session;
        }

        session.messages.forEach(message => {
            const imageJob = message?.image_job;
            if (imageJob?.status === 'dispatching') {
                imageJob.status = 'queued';
                imageJob.phase = 'queued';
            }

            const toolResult = message?.tool_result;
            if (toolResult?.status === 'dispatching') {
                toolResult.status = 'queued';
            }

            const resultJob = toolResult?.data?.job;
            if (resultJob?.status === 'dispatching') {
                resultJob.status = 'queued';
                resultJob.phase = 'queued';
            }
        });

        return session;
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

        normalizeRecoveredMediaState(session);
    }


    function persistedSnapshot(session) {
        return JSON.stringify(withoutStreamingFields(session));
    }

    function contentSnapshot(value) {
        return JSON.stringify(value, (_key, item) => {
            if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
            return Object.fromEntries(Object.keys(item).sort()
                .filter(key => key !== '_thinkingStarted').map(key => [key, item[key]]));
        });
    }

    function comparableSessionSettings(settings) {
        // Normalize only defaults introduced when an old chat is opened by a
        // newer frontend. Real per-chat settings edits (e.g. system prompts)
        // must not disappear merely because the messages are unchanged.
        const normalized = { ...(settings || {}) };
        const defaults = {
            system_prompt: '',
            preset_id: 'general',
            adaptive_response_auto: true,
            adaptive_response_length: false,
            media_quality: 'standard',
            negative_prompt: '',
        };
        for (const [key, value] of Object.entries(defaults)) {
            if (normalized[key] === undefined || normalized[key] === null) {
                normalized[key] = value;
            }
        }
        return normalized;
    }

    function sameConversationContent(local, server) {
        // Timestamps and known startup settings defaults do not change chat
        // content; deliberate changes to a prompt, preset or other settings do.
        return local.title === server.title &&
            contentSnapshot(local.messages) === contentSnapshot(server.messages) &&
            contentSnapshot(local.workspace ?? null) === contentSnapshot(server.workspace ?? null) &&
            contentSnapshot(comparableSessionSettings(local.settings)) ===
                contentSnapshot(comparableSessionSettings(server.settings));
    }

    async function persistSession(session) {
        if (clearingHistory || !serverReady || !validSession(session) ||
                !state.sessions.includes(session) ||
                pendingConflicts.has(session.id) ||
                (!acknowledgedUpdated.has(session.id) &&
                    !session.messages.some(message => message?.role === 'user'))) {
            return;
        }

        // One in-flight write per chat. A mutation during the request is
        // picked up in the next loop iteration, in the original order.
        const id = session.id;
        if (activePersists.has(id)) {
            return activePersists.get(id);
        }
        const epoch = historyEpoch;
        persistEpoch++;
        const operation = (async () => {
            while (!clearingHistory && epoch === historyEpoch &&
                    state.sessions.includes(session) &&
                    !pendingConflicts.has(id)) {
                const sentSession = withoutStreamingFields(session);
                const sentSnapshot = JSON.stringify(sentSession);
                if (acknowledgedSnapshots.get(id) === sentSnapshot) {
                    forgetJournal(id);
                    return;
                }

                if (journalCopies.has(id)) {
                    try {
                        localStorage.setItem(journalKey(id), JSON.stringify({
                            sourceId: journalSources.get(id),
                            copy: withoutHeavyCacheFields(session),
                        }));
                    } catch {}
                }
                // -1 means this tab has never observed the chat on the
                // server. Existing chat records must not be overwritten
                // by a stale browser cache posing as a new session.
                sentSession.expected_updated = acknowledgedUpdated.has(id)
                    ? acknowledgedUpdated.get(id) : -1;

                const request = MLXCommon.fetchJson(
                    '/api/mlx/chats/' + encodeURIComponent(id),
                    MLXCommon.jsonRequest('PUT', sentSession)
                );
                pendingPersists.add(request);
                let result;
                try {
                    result = await request;
                } catch {
                    return;
                } finally {
                    pendingPersists.delete(request);
                }

                if (clearingHistory || epoch !== historyEpoch ||
                        !state.sessions.includes(session) ||
                        !result.response.ok || !validSession(result.data?.chat)) {
                    return;
                }

                const serverChat = result.data.chat;
                const changedDuringRequest =
                    persistedSnapshot(session) !== sentSnapshot;
                acknowledgedUpdated.set(id, serverChat.updated);

                if (result.data.conflict === true) {
                    // A different tab won. Keep its saved data and never
                    // blindly retry with our stale original timestamp.
                    acknowledgedSnapshots.set(id, persistedSnapshot(serverChat));
                    if (sameConversationContent(session, serverChat)) {
                        // Timestamps/default settings alone do not warrant a copy.
                        updateFromServer(session, serverChat, isGenerating() && state.activeId === id);
                    } else {
                        // The rejected payload is itself an unsaved edit, even
                        // when nothing changed while the request was in flight.
                        await reserveConflictId(session);
                        if (clearingHistory || epoch !== historyEpoch || !state.sessions.includes(session)) return;
                        pendingConflicts.set(id, serverChat);
                        saveConflictMarkers();
                        cacheSessions();
                        const copies = [];
                        recoverConflictedChats(copies);
                        cacheSessions();
                        // Finish the fork now; no later click/save is required.
                        await Promise.all(copies.map(persistSession));
                    }
                    if (!pendingConflicts.has(id)) forgetJournal(id);
                    cacheSessions();
                    renderAll();
                    return;
                }

                acknowledgedSnapshots.set(id, sentSnapshot);
                if (serverChat.updated > session.updated) {
                    if (changedDuringRequest) {
                        // The server may advance the CAS timestamp even for a
                        // same-millisecond write. Never replace title,
                        // workspace, settings or messages edited in flight.
                        session.updated = Math.max(session.updated, serverChat.updated);
                        session.revision = serverChat.revision;
                    } else {
                        updateFromServer(
                            session,
                            serverChat,
                            isGenerating() && state.activeId === id
                        );
                    }
                    cacheSessions();
                    renderAll();
                    if (changedDuringRequest) continue;
                    acknowledgedSnapshots.set(id, persistedSnapshot(session));
                    forgetJournal(id);
                    return;
                }
                if (!changedDuringRequest) {
                    forgetJournal(id);
                    return;
                }
            }
        })();
        activePersists.set(id, operation);
        try {
            await operation;
        } finally {
            if (activePersists.get(id) === operation) {
                activePersists.delete(id);
            }
        }
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
        acknowledgedSnapshots.clear();
        acknowledgedUpdated.clear();
        pendingConflicts.clear();
        try {
            const ids = JSON.parse(localStorage.getItem(CONFLICT_KEY) || '[]');
            if (Array.isArray(ids)) {
                ids.filter(id => typeof id === 'string').forEach(id =>
                    pendingConflicts.set(id, null)
                );
            }
        } catch {
            // Invalid recovery metadata must not delete cached chat data.
        }
        try {
            const cached = JSON.parse(
                localStorage.getItem(STORAGE_KEY)
            ) || [];

            state.sessions = cached
                .filter(validSession)
                .map(normalizeRecoveredMediaState);
        } catch {
            state.sessions = [];
        }

        try {
            for (let index = 0; index < localStorage.length; index++) {
                const key = localStorage.key(index);
                if (!key?.startsWith(JOURNAL_PREFIX)) continue;
                let entry;
                try { entry = JSON.parse(localStorage.getItem(key)); } catch { continue; }
                if (!entry || !validSession(entry.copy)) continue;
                const existing = state.sessions.find(item => item.id === entry.copy.id);
                if (existing && !sameConversationContent(existing, entry.copy)) entry.copy.id = uid();
                if (!journalKeys.has(entry.copy.id)) journalKeys.set(entry.copy.id, new Set());
                journalKeys.get(entry.copy.id).add(key);
                if (validSession(entry.source)) {
                    state.sessions = state.sessions.filter(item =>
                        item.id !== entry.source.id || !sameConversationContent(item, entry.source));
                    pendingConflicts.delete(entry.source.id);
                }
                state.sessions = state.sessions.filter(item => item.id !== entry.copy.id);
                state.sessions.unshift(normalizeRecoveredMediaState(entry.copy));
                journalCopies.add(entry.copy.id);
                journalSources.set(entry.copy.id, entry.sourceId || entry.source?.id);
            }
        } catch (error) {
            console.warn('[MLX nobby] Could not recover conflict journal:', error);
        }
        if (state.sessions.length) {
            state.activeId = state.sessions[0].id;
        }
        if (recoverConflictedChats()) {
            cacheSessions();
        }
    }

    function saveSessions() {
        if (clearingHistory) return;
        saveConflictMarkers();
        recoverConflictedChats();
        cacheSessions();

        if (serverReady) {
            state.sessions.forEach(persistSession);
        }
    }

    async function syncWithServer() {
        if (clearingHistory) return;
        if (serverSyncing) {
            // A concurrent caller requested a real refresh, not a no-op.
            // Retry after the current sync settles, even if its GET became
            // obsolete because another PUT started in the meantime.
            if (serverSyncCompleted) await serverSyncCompleted;
            return clearingHistory ? undefined : syncWithServer();
        }

        // Never drop a requested UI refresh just because a chat write is
        // running. Wait until the write has acknowledged, then fetch the
        // authoritative history. The existing persistEpoch guard below still
        // discards GET responses overtaken by subsequent writes.
        if (activePersists.size) {
            await Promise.allSettled([...activePersists.values()]);
            if (serverSyncing || clearingHistory) return;
        }

        serverSyncing = true;
        serverSyncCompleted = new Promise(resolve => { finishServerSync = resolve; });
        const epoch = historyEpoch;
        const writesAtStart = persistEpoch;

        try {
            const {
                response,
                data
            } = await MLXCommon.fetchJson('/api/mlx/chats');

            if (clearingHistory || epoch !== historyEpoch || writesAtStart !== persistEpoch || !response.ok || !Array.isArray(data.chats)) {
                return;
            }

            const deletedIds = new Set(data.deleted_ids || []);
            for (const [copyId, sourceId] of journalSources) {
                if (deletedIds.has(copyId) || deletedIds.has(sourceId)) {
                    deletedIds.add(copyId);
                    forgetJournal(copyId);
                }
            }
            const localById = new Map(
                state.sessions
                    .filter(session => validSession(session) && !deletedIds.has(session.id))
                    .map(normalizeRecoveredMediaState)
                    .map(session => [session.id, session])
            );

            const serverById = new Map(
                data.chats
                    .filter(validSession)
                    .map(normalizeRecoveredMediaState)
                    .map(session => [session.id, session])
            );

            const merged = new Map();
            const localWinners = [];

            for (const id of new Set([
                ...localById.keys(),
                ...serverById.keys()
            ])) {
                const local = localById.get(id);
                const server = serverById.get(id);

                if (pendingConflicts.has(id) && local) {
                    // A pending live edit remains local until it can be
                    // forked safely; never push it as the winning version.
                    pendingConflicts.set(id, server);
                    merged.set(id, local);
                    continue;
                }
                if (server && local &&
                        acknowledgedUpdated.get(id) !== server.updated &&
                        (!acknowledgedSnapshots.has(id) ||
                            persistedSnapshot(local) !== acknowledgedSnapshots.get(id))) {
                    // A browser cache timestamp does not prove the user has
                    // seen the server's current state. This may be an old
                    // offline tab; keep both histories instead of forcing
                    // the local copy over another tab's saved work.
                    if (sameConversationContent(local, server)) {
                        // Runtime settings normalization is not an independent
                        // chat edit; retain local settings, but do not eagerly
                        // write them back over another tab's server version.
                        if (journalCopies.has(id)) forgetJournal(id);
                        merged.set(id, local);
                        continue;
                    }
                    await reserveConflictId(local);
                    if (clearingHistory || epoch !== historyEpoch || writesAtStart !== persistEpoch) return;
                    if (isGenerating()) {
                        pendingConflicts.set(id, server);
                        saveConflictMarkers();
                        merged.set(id, local);
                    } else {
                        const copy = journalConflict(local);
                        pendingCopyIds.delete(id);
                        updateFromServer(local, server, false);
                        merged.set(id, local);
                        merged.set(copy.id, copy);
                        localWinners.push(copy);
                        if (state.activeId === id) {
                            state.activeId = copy.id;
                        }
                    }
                    continue;
                }
                if (!server || (local && (local.updated > server.updated ||
                        (acknowledgedUpdated.get(id) === server.updated &&
                            persistedSnapshot(local) !== acknowledgedSnapshots.get(id))))) {
                    merged.set(id, local);
                    localWinners.push(local);
                    continue;
                }

                if (local) {
                    updateFromServer(
                        local,
                        server,
                        isGenerating() && state.activeId === id
                    );
                }
                merged.set(id, normalizeRecoveredMediaState(local || server));
            }

            state.sessions = Array.from(merged.values())
                .sort((left, right) => right.updated - left.updated);

            if (
                !state.sessions.some(
                    session => session.id === state.activeId
                )
            ) {
                state.activeId = state.sessions[0]?.id || null;
            }

            // Acknowledged snapshots are based on what the server actually
            // returned, never the possibly newer local browser copy.
            const activeIds = new Set(state.sessions.map(session => session.id));
            for (const id of acknowledgedSnapshots.keys()) {
                if (!activeIds.has(id)) {
                    acknowledgedSnapshots.delete(id);
                    acknowledgedUpdated.delete(id);
                }
            }
            for (const [id, server] of serverById) {
                acknowledgedSnapshots.set(id, persistedSnapshot(server));
                acknowledgedUpdated.set(id, server.updated);
            }

            serverReady = true;
            const memorySource = (window.location?.search && typeof URLSearchParams !== 'undefined') ? new URLSearchParams(window.location.search).get('memory_chat') : null;
            if (memorySource && state.sessions.some(item => item.id === memorySource)) {
                state.activeId = memorySource;
            }

            if (!state.sessions.length) {
                createSession();
                return;
            }

            cacheSessions();
            await Promise.all(localWinners.map(persistSession));
            onSessionSelected();
            renderAll();

        } catch {
            // Keep localStorage as the fallback when the agent is unavailable.
            if (!clearingHistory && epoch === historyEpoch && !state.sessions.length) {
                createSession();
            }
        } finally {
            serverSyncing = false;
            const finish = finishServerSync;
            finishServerSync = null;
            serverSyncCompleted = null;
            if (finish) finish();
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
        if (clearingHistory) return;
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

    async function deleteAllSessions() {
        if (clearingHistory || confirmingHistory) return false;
        confirmingHistory = true;
        try {
            const confirmed = await window.MLXConfirm?.({
                title: sessionT('ui.delete_all_chats_title', 'Delete all chats?'),
                message: sessionT('ui.delete_all_chats_message', 'This removes the entire chat history and cannot be undone.'),
                confirmLabel: sessionT('ui.delete_all_chats', 'Delete all chats'),
                cancelLabel: sessionT('ui.cancel', 'Cancel'),
            });
            if (!confirmed) return false;

            clearingHistory = true;
            historyEpoch++;
            const oldSessions = [...state.sessions];
            oldSessions.forEach(bumpRuntimeRevision);
            await Promise.all(oldSessions.map(session =>
                window.MLXChatGeneration?.resetSessionRuntime?.(session)
            ));
            // Finish writes already sent before committing the bulk deletion.
            await Promise.allSettled([...pendingPersists]);
            const { response, data } = await MLXCommon.fetchJson(
                '/api/mlx/chats',
                MLXCommon.jsonRequest('DELETE', { ids: oldSessions.map(session => session.id) })
            );
            if (!response.ok || data.ok !== true) {
                throw new Error('Chat history deletion failed');
            }

            state.sessions = [];
            state.activeId = null;
            acknowledgedSnapshots.clear();
            acknowledgedUpdated.clear();
            pendingConflicts.clear();
            pendingCopyIds.clear();
            for (const id of [...journalCopies]) forgetJournal(id);
            saveConflictMarkers();
            localStorage.removeItem(STORAGE_KEY);
            window.MLXChatAttachments?.clearAttachments?.();
            try {
                await window.MLXChatWorkspace?.deactivate?.();
            } catch (error) {
                console.warn('Chat workspace detach failed:', error);
            }
            serverReady = true;
            clearingHistory = false;
            createSession();
            return true;
        } catch (error) {
            console.warn('Chat history deletion failed:', error);
            await window.MLXConfirm?.({
                title: sessionT('ui.delete_all_chats_failed', 'Chat history could not be deleted'),
                message: sessionT('ui.delete_all_chats_failed_message', 'The server is unavailable or deletion failed. Your chat history has been retained. Please try again.'),
                confirmLabel: sessionT('common.close', 'Close'),
                cancelLabel: sessionT('common.close', 'Close'),
            });
            return false;
        } finally {
            confirmingHistory = false;
            clearingHistory = false;
            cacheSessions();
            renderAll();
        }
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
        acknowledgedSnapshots.delete(id);
        acknowledgedUpdated.delete(id);
        clearConflictMarker(id);

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
        normalizeRecoveredMediaState(currentSession());
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
            const recoveredChat = normalizeRecoveredMediaState(chat);
            const existing = state.sessions.find(item => item.id === recoveredChat.id);

            if (!existing || recoveredChat.updated > existing.updated) {
                if (existing) {
                    state.sessions[state.sessions.indexOf(existing)] = withoutStreamingFields(recoveredChat);
                } else {
                    state.sessions.push(withoutStreamingFields(recoveredChat));
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
        deleteAllSessions: deleteAllSessions,
        deleteMessages: deleteMessages,
        selectSession: selectSession,
        updateTitle: updateTitle,
        exportCurrentJson: exportCurrentJson,
        exportCurrentMarkdown: exportCurrentMarkdown,
        exportAllChats: exportAllChats,
        importBackup: importBackup
    };
})();
