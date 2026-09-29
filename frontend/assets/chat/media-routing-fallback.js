(function () {
    'use strict';

    if (window.__mlxNobbyMediaRoutingFallback) return;
    window.__mlxNobbyMediaRoutingFallback = true;

    const modal = document.getElementById('mediaQualityModal');
    const cancelButton = document.getElementById('mediaQualityModalCancel');

    if (!modal || !cancelButton) return;

    let fallbackScheduled = false;

    function scheduleChatFallback() {
        if (modal.hidden || fallbackScheduled) return;

        const session = window.MLXChatSessions?.currentSession?.();
        const userMessage = session?.messages?.at?.(-1);

        if (!session || userMessage?.role !== 'user') return;

        fallbackScheduled = true;

        setTimeout(async () => {
            fallbackScheduled = false;

            if (!modal.hidden) return;
            if (window.MLXChatSessions?.currentSession?.() !== session) return;
            if (!session.messages?.includes?.(userMessage)) return;
            if (session.messages.at(-1) !== userMessage) return;

            const generation = window.MLXChatGeneration;
            if (!generation?.generateAssistant) return;

            try {
                await generation.generateAssistant(session);
            } catch (error) {
                console.error('[MLX Media Routing] Chat fallback failed', error);
            }
        }, 0);
    }

    // The media modal is only a routing confirmation. Cancelling it means
    // "this was not a media request", not "discard my chat message".
    cancelButton.addEventListener('click', scheduleChatFallback);

    modal
        .querySelector('[data-media-quality-dismiss]')
        ?.addEventListener('click', scheduleChatFallback);

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !modal.hidden) {
            scheduleChatFallback();
        }
    });
})();
