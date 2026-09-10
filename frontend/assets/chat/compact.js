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
                'Kontext wird komprimiert…';
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
                        session.messages
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
            'Kontext komprimiert:',
            before,
            '→',
            after
        );

        return true;

    } catch (error) {
        console.error(
            'Komprimierung fehlgeschlagen:',
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
