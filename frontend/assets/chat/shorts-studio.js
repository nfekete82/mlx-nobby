(function () {
    'use strict';

    const SHORTS_PATTERN = /\b(?:shorts?|short[\s-]*videos?|youtube[\s-]+shorts?|tiktoks?(?:[\s-]+videos?)?|reels?|kurzvideos?)\b/iu;
    const CREATE_PATTERN = /\b(?:erstelle|erstellen|generiere|generieren|erzeuge|erzeugen|mach(?:e)?|create|generate|make)\b/iu;
    const EXPLICIT_VOICE_PATTERN = /\b(?:stimme|voice|sprecher(?:in)?|speaker|sprechgeschwindigkeit|geschwindigkeit|voice[_ -]?speed|speed)\b/iu;

    const previousFetch = window.fetch.bind(window);

    function requestPath(input) {
        const raw = typeof input === 'string' ? input : input?.url;
        if (!raw) return '';
        try {
            return new URL(raw, window.location.origin).pathname;
        } catch (_) {
            return '';
        }
    }

    function isShortsPrompt(prompt) {
        const value = String(prompt || '');
        return SHORTS_PATTERN.test(value) && CREATE_PATTERN.test(value);
    }

    function studioVoiceInstruction(prompt) {
        if (!isShortsPrompt(prompt) || EXPLICIT_VOICE_PATTERN.test(String(prompt || ''))) {
            return '';
        }

        const settings = window.MLXVoice?.getSettings?.();
        const voice = String(settings?.voice || '').trim();
        const speed = Number(settings?.speed);

        if (!voice || !Number.isFinite(speed) || speed < 0.5 || speed > 2.0) {
            return '';
        }

        return `\n\nShorts Studio settings (apply exactly, do not mention in the title or narration): voice=${voice}; voice_speed=${speed}.`;
    }

    window.fetch = function mlxShortsStudioFetch(input, init) {
        if (requestPath(input) !== '/api/mlx/chat/actions' || !init?.body) {
            return previousFetch(input, init);
        }

        try {
            const body = JSON.parse(init.body);
            const instruction = studioVoiceInstruction(body?.prompt);

            if (!instruction) {
                return previousFetch(input, init);
            }

            return previousFetch(input, {
                ...init,
                body: JSON.stringify({
                    ...body,
                    prompt: String(body.prompt || '') + instruction
                })
            });
        } catch (_) {
            return previousFetch(input, init);
        }
    };

    window.MLXShortsStudio = {
        isShortsPrompt,
        studioVoiceInstruction
    };
})();
