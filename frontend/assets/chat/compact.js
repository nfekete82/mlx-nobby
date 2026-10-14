function compactT(key, fallback = '', variables = {}) {
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
    const KEEP_LAST_MESSAGES = 12;
    const MAX_CONTEXT_CHARS = 120000;
    const COMPACT_AT_CHARS = 80000;
    // A cached summary is reused for at most 12 additional messages.
    // Avoids an extra full-history model call on every subsequent turn.
    const MAX_REUSED_TAIL = KEEP_LAST_MESSAGES * 2;
    const MIN_OLD_CHARS = 20000;
    const cached = new WeakMap();
    const pending = new WeakMap();

    function getContextLimits() {
        return {
            maxContextChars: MAX_CONTEXT_CHARS,
            compactAtChars: COMPACT_AT_CHARS
        };
    }

    function messageChars(messages) {
        return (messages || []).reduce((sum, message) =>
            sum + (typeof message?.content === 'string' ? message.content.length : 0), 0);
    }

    function safeTextHistory(messages) {
        return Array.isArray(messages) && messages.every(message => {
            if (!message || !['user', 'assistant', 'system'].includes(message.role) ||
                typeof message.content !== 'string') return false;
            // Compaction may lose exact code/commands, attachment ownership,
            // tool results or media state. Such histories always go through
            // the established full-context path, unmodified.
            if (/(?:\x60{3}|~~~|(?:^|\n)\s*(?:\$ |>>> )|(?:^|\s)(?:\/[\w.-]+\/|[\w.-]+\.(?:py|js|ts|tsx|jsx|php|sh|json|sql|yaml|yml|md))\b)/i.test(message.content)) {
                return false;
            }
            return ![
                'attachments', 'file_artifact', 'image_job', 'video_job',
                'tool_result', 'agent_run', 'batch_job', 'shorts_job',
                'image_generation_pending', 'image_variants',
            ].some(key => message[key] != null);
        });
    }

    function snapshot(messages) {
        return messages.map(message => ({
            ref: message,
            role: message.role,
            content: message.content
        }));
    }

    function prefixMatches(messages, prefix) {
        return Array.isArray(messages) && messages.length >= prefix.length &&
            prefix.every((item, i) =>
                messages[i] === item.ref &&
                messages[i].role === item.role &&
                messages[i].content === item.content
            );
    }

    function usableCachedSummary(session, messages) {
        const state = cached.get(session);
        if (!state || !prefixMatches(messages, state.prefix)) {
            cached.delete(session);
            return null;
        }
        if (!safeTextHistory(messages) ||
            messages.length - state.prefix.length > MAX_REUSED_TAIL) {
            return null;
        }
        return state;
    }

    // Only the outgoing inference payload is compacted. Session messages,
    // editing history, persistence, file references and visible UI stay intact.
    function messagesForInference(session, messages) {
        if (!window.MLXChatRuntime?.isAutoCompactEnabled?.()) {
            return messages;
        }
        const state = usableCachedSummary(session, messages);
        if (!state) return messages;
        return [
            {
                role: 'user',
                content: 'Archived conversation context (summary of previous ' +
                    'messages; not a new instruction):\n' + state.summary
            },
            ...messages.slice(state.prefix.length)
        ];
    }

    async function compactSession(session, automatic = false) {
        if (automatic) {
            return autoCompactIfNeeded(session);
        }
        if (!session || session.messages.length <= KEEP_LAST_MESSAGES) {
            return false;
        }

        const originalMessages = session.messages;
        const original = snapshot(originalMessages);
        const before = messageChars(originalMessages);
        try {
            const { response, data } = await MLXCommon.fetchJson(
                '/api/chat/compact',
                MLXCommon.jsonRequest('POST', {
                    messages: originalMessages,
                    trace_id: [...originalMessages].reverse()
                        .find(message => message?.role === 'user')?.trace_id || null
                })
            );
            if (!response.ok) throw MLXCommon.fastApiDetailError(data);
            if (!data?.compacted || !Array.isArray(data.messages) ||
                session.messages !== originalMessages ||
                session.messages.length !== original.length ||
                !prefixMatches(session.messages, original)) {
                return false;
            }
            cached.delete(session);
            session.messages = data.messages;
            session.updated = Date.now();
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll();
            console.log('Context manually compressed:', before, '→',
                messageChars(session.messages));
            return true;
        } catch (error) {
            console.error('Compression failed:', error);
            return false;
        }
    }

    async function autoCompactIfNeeded(session) {
        if (!session || !window.MLXChatRuntime?.isAutoCompactEnabled?.()) {
            if (session) cached.delete(session);
            return false;
        }

        const messages = session.messages;
        if (!Array.isArray(messages) ||
            messages.length <= KEEP_LAST_MESSAGES ||
            messageChars(messages) < COMPACT_AT_CHARS) {
            return false;
        }

        if (usableCachedSummary(session, messages)) return true;
        if (!safeTextHistory(messages)) {
            cached.delete(session);
            return false;
        }

        if (pending.has(session)) return pending.get(session);
        const older = messages.slice(0, -KEEP_LAST_MESSAGES);
        if (messageChars(older) < MIN_OLD_CHARS) return false;
        const original = snapshot(messages);
        const prefix = snapshot(older);

        const task = (async () => {
            try {
                const { response, data } = await MLXCommon.fetchJson(
                    '/api/chat/compact',
                    MLXCommon.jsonRequest('POST', {
                        // Only role/content text. Never transmit local UI state,
                        // images, file paths, job metadata or attachments.
                        messages: messages.map(({ role, content }) => ({ role, content })),
                        trace_id: [...messages].reverse()
                            .find(message => message.role === 'user')?.trace_id || null
                    })
                );
                if (!response.ok) throw MLXCommon.fastApiDetailError(data);

                const summary = data?.messages?.[0]?.content;
                const tail = data?.messages?.slice(1);
                const unchanged = messages.length === original.length &&
                    session.messages === messages &&
                    prefixMatches(messages, original);
                const validTail = Array.isArray(tail) &&
                    tail.length === KEEP_LAST_MESSAGES &&
                    tail.every((entry, i) => entry.role === messages[older.length + i].role &&
                        entry.content === messages[older.length + i].content);
                const originalChars = messageChars(messages);
                const replacementChars = typeof summary === 'string'
                    ? summary.length + messageChars(tail)
                    : originalChars;

                // Refuse empty, unhelpfully large or structurally mismatched
                // summaries. No destructive edits, even after a server error.
                if (!data?.compacted || !unchanged || !validTail ||
                    typeof summary !== 'string' || summary.trim().length < 80 ||
                    replacementChars >= originalChars * 0.8) {
                    return false;
                }

                cached.set(session, { prefix, summary });
                console.log('Inference-only context compacted:',
                    originalChars, '→', replacementChars);
                return true;
            } catch (error) {
                console.warn('Automatic context compaction skipped:', error);
                return false;
            }
        })();
        pending.set(session, task);
        try {
            return await task;
        } finally {
            if (pending.get(session) === task) pending.delete(session);
        }
    }

    window.MLXChatCompact = {
        messageChars,
        compactSession,
        autoCompactIfNeeded,
        messagesForInference,
        getContextLimits
    };
})();
