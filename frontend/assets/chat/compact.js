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

    function getContextLimits() {
        return {
            maxContextChars: MAX_CONTEXT_CHARS,
            compactAtChars: COMPACT_AT_CHARS
        };
    }

function messageChars(messages) {
    return (messages || []).reduce(
        (sum, message) =>
            sum + (message.content || '').length,
        0
    );
}


async function compactSession(session, automatic = false) {

    if (!session) return false;

    if (
        session.messages.length <=
        KEEP_LAST_MESSAGES
    ) {
        return false;
    }

    const before =
        messageChars(session.messages);

    try {
        if (automatic) {
            document.getElementById(
                'contextText'
            ).textContent =
                compactT('compact.running', 'Compressing context…');
        }

        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/chat/compact',
            MLXCommon.jsonRequest(
                'POST',
                {
                    messages:
                        session.messages,
                    trace_id:
                        session.messages
                            .slice()
                            .reverse()
                            .find(message => message?.role === 'user')
                            ?.trace_id || null
                }
            )
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        if (!data.compacted) {
            return false;
        }

        session.messages =
            data.messages;

        session.updated =
            Date.now();

        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll();

        const after =
            messageChars(
                session.messages
            );

        console.log(
            'Context compressed:',
            before,
            '→',
            after
        );

        return true;

    } catch (error) {
        console.error(
            'Compression failed:',
            error
        );

        return false;
    }
}


async function autoCompactIfNeeded(session) {
    if (!MLXChatRuntime.isAutoCompactEnabled()) {
        return;
    }

    const chars =
        messageChars(
            session?.messages || []
        );

    if (
        chars <
        COMPACT_AT_CHARS
    ) {
        return;
    }

    await compactSession(
        session,
        true
    );
}



    window.MLXChatCompact = {
        messageChars: messageChars,
        compactSession: compactSession,
        autoCompactIfNeeded: autoCompactIfNeeded,
        getContextLimits: getContextLimits
    };
})();
