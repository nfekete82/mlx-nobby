/* Automatic, per-chat response-style recovery. No prompts or chat text are logged. */
(function () {
    'use strict';

    const SHORT_TOKEN_LIMIT = 70;
    const REQUIRED_SHORT_REPLIES = 3;
    const MAX_SHORT_USER_CHARS = 320;

    const SCENE_GUIDANCE = (
        '\n\nFor this reply only: The ongoing scene has fallen into a pattern ' +
        'of unusually short reactions. Continue naturally with a few ' +
        'substantive sentences, fitting actions and dialogue. Stay in ' +
        'character; do not pad or repeat, and never decide or speak ' +
        'for the user character. Respect the user\'s explicit style and ' +
        'length requests.'
    );

    const GENERAL_GUIDANCE = (
        '\n\nFor this reply only: Recent replies have been unusually short. ' +
        'Match the actual conversation and the user\'s latest request: ' +
        'give an open-ended question, personal exchange or explanation ' +
        'enough substance to be useful rather than just a terse reaction. ' +
        'Keep genuinely simple factual questions concise. Never add filler, ' +
        'repetition or invented details, and respect explicit brevity.'
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
        return /(?:antworte|antwort|schreibe|beschreibe|sag|sage|reply|respond|write)\s+(?:bitte\s+)?(?:sehr\s+|ganz\s+)?(?:kurz|knapp|einsilbig|briefly|short|concisely)|(?:nur|only)\s+(?:ein(?:en|e|em)?\s+)?(?:satz|wort|sentence|word)|(?:in|mit)\s+(?:einem|1)\s+(?:satz|wort)/i.test(text);
    }

    function simpleFactQuestion(text) {
        return /^(?:wer|wann|wo|wieviel|wie viel|wie spät|what time|who|when|where|how much)\b/i.test(text.trim());
    }

    function isScene(session, messages) {
        if (session?.settings?.preset_id === 'roleplay') return true;
        const prompt = String(session?.settings?.system_prompt || '');
        if (/\b(?:roleplay|role-play|rollenspiel|stay in character|spiele eine figur|du bist eine figur|character role|szenenbeschreibung)\b/i.test(prompt)) {
            return true;
        }

        const recent = messages.slice(-10).filter(m =>
            m?.role === 'assistant' && typeof m.content === 'string'
        );

        return recent.some(message => {
            const text = message.content.slice(0, 600);
            return /\*[^*\n]{4,120}\*/.test(text) ||
                /(?:^|\n)\s*[A-ZÄÖÜ][a-zäöüß]{2,24}\s+(?:blinzelt|lächelt|grinst|schaut|blickt|atmet|schweigt|dreht|nimmt|setzt|steht|nickt|flüstert|starrt|zögert|smiles|looks|blinks|whispers|nods)\b/m.test(text);
        });
    }

    function instructionForTurn(session, messages) {
        // A new setting enables this on existing as well as new chats.
        // Legacy adaptive_response_length remains accepted by persistence.
        if (session?.settings?.adaptive_response_auto === false ||
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

        if (replies.length !== REQUIRED_SHORT_REPLIES ||
            !replies.every(isShortModelReply)) {
            return '';
        }

        const narrative = isScene(session, messages);
        if (!narrative && simpleFactQuestion(current.content)) return '';

        return narrative ? SCENE_GUIDANCE : GENERAL_GUIDANCE;
    }

    window.MLXChatResponseLength = Object.freeze({
        instructionForTurn
    });
})();
