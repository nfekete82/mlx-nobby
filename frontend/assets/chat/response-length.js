/* Optional, per-chat response-length steering. No message contents are stored. */
(function () {
    'use strict';

    const SHORT_TOKEN_LIMIT = 70;
    const REQUIRED_SHORT_REPLIES = 3;
    const MAX_SHORT_USER_CHARS = 320;
    const GUIDANCE = (
        '\n\nFor this reply only: The recent dialogue has settled into ' +
        'unintentionally short roleplay responses. Continue the scene ' +
        'naturally in approximately three to five substantive sentences, ' +
        'using fitting action or dialogue instead of a single reaction. ' +
        'Stay in character, avoid padding or repetition, and never write ' +
        'dialogue, decisions, or actions for the user character. ' +
        'Follow any explicit length or style instruction from the user.'
    );

    function lastChatCall(message) {
        const calls = message?.model_metrics?.calls;
        if (!Array.isArray(calls)) return null;
        for (let i = calls.length - 1; i >= 0; i--) {
            if (calls[i]?.purpose === 'chat.stream') return calls[i];
        }
        return null;
    }

    function isShortModelReply(message) {
        if (!message || message.role !== 'assistant' ||
            message.response_pending || message.agent_run || message.tool_result ||
            message.image_job || message.video_job || message.batch_job ||
            typeof message.content !== 'string' ||
            !message.content.trim() || message.content.length > 420) {
            return false;
        }
        const call = lastChatCall(message);
        const tokens = call?.usage?.output_tokens;
        return call?.status === 'completed' &&
            call?.finish_reason === 'stop' &&
            Number.isInteger(tokens) &&
            tokens > 0 && tokens <= SHORT_TOKEN_LIMIT;
    }

    function explicitlyShortRequest(text) {
        return /(?:antworte|antwort|schreibe|beschreibe|sag|sage|reply|respond|write)\s+(?:bitte\s+)?(?:sehr\s+)?(?:kurz|knapp|einsilbig|briefly|short|concisely)|(?:nur|only)\s+(?:ein(?:en|e|em)?\s+)?(?:satz|wort|sentence|word)|(?:in|mit)\s+(?:einem|1)\s+(?:satz|wort)/i.test(text);
    }

    function instructionForTurn(session, messages) {
        if (session?.settings?.adaptive_response_length !== true ||
            !Array.isArray(messages) || messages.length < 7) {
            return '';
        }

        const current = messages[messages.length - 1];
        if (current?.role !== 'user' || typeof current.content !== 'string' ||
            !current.content.trim() ||
            current.content.length > MAX_SHORT_USER_CHARS ||
            explicitlyShortRequest(current.content)) {
            return '';
        }

        const replies = [];
        for (let i = messages.length - 2; i >= 0 && replies.length < REQUIRED_SHORT_REPLIES; i--) {
            if (messages[i]?.role === 'assistant') replies.push(messages[i]);
        }

        return replies.length === REQUIRED_SHORT_REPLIES &&
            replies.every(isShortModelReply) ? GUIDANCE : '';
    }

    window.MLXChatResponseLength = Object.freeze({
        instructionForTurn
    });
})();
