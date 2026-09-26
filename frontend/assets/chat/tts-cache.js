(function () {
    'use strict';

    const MAX_ENTRIES = 40;
    const cache = new Map();
    const inFlight = new Map();
    const wrappedFetch = window.fetch.bind(window);

    function isSpeechRequest(input) {
        const raw = typeof input === 'string' ? input : input?.url;
        if (!raw) return false;
        try {
            return new URL(raw, window.location.origin).pathname === '/api/mlx/audio/speech';
        } catch (_) {
            return false;
        }
    }

    function requestBody(init) {
        if (!init?.body || typeof init.body !== 'string') return null;
        try {
            return JSON.parse(init.body);
        } catch (_) {
            return null;
        }
    }

    function cacheKey(body) {
        if (!body) return null;
        const voice = window.MLXVoice?.getSettings?.() || {};
        return JSON.stringify({
            input: String(body.input || ''),
            language: String(body.language || 'de'),
            response_format: String(body.response_format || 'mp3'),
            voice: String(voice.voice || body.voice || ''),
            speed: Number(voice.speed ?? body.speed ?? 1),
            instruct: String(body.instruct || '')
        });
    }

    function responseFrom(entry) {
        return new Response(entry.blob, {
            status: entry.status,
            statusText: entry.statusText,
            headers: entry.headers
        });
    }

    function remember(key, entry) {
        if (cache.has(key)) cache.delete(key);
        cache.set(key, entry);
        while (cache.size > MAX_ENTRIES) {
            cache.delete(cache.keys().next().value);
        }
    }

    function invalidateText(text) {
        const normalized = String(text || '').trim();
        if (!normalized) return 0;

        let removed = 0;
        for (const key of [...cache.keys()]) {
            try {
                const parsed = JSON.parse(key);
                if (String(parsed.input || '').trim() === normalized) {
                    cache.delete(key);
                    removed += 1;
                }
            } catch (_) {}
        }
        return removed;
    }

    function messageText(button) {
        const article = button?.closest?.('.message');
        const content = article?.querySelector?.('.message-content');
        if (!content) return '';

        if (article.classList.contains('assistant')) {
            for (const child of content.children) {
                if (child.tagName === 'DIV' && !child.className) {
                    return String(child.innerText || child.textContent || '').trim();
                }
            }
        }

        return String(content.innerText || content.textContent || '').trim();
    }

    async function fetchAndCache(input, init, key) {
        const response = await wrappedFetch(input, init);
        if (!response.ok) return response;

        const clone = response.clone();
        const blob = await clone.blob();
        const headers = {};
        clone.headers.forEach((value, name) => {
            headers[name] = value;
        });
        remember(key, {
            blob,
            status: clone.status,
            statusText: clone.statusText,
            headers
        });
        return response;
    }

    window.fetch = function mlxTtsCachedFetch(input, init) {
        if (!isSpeechRequest(input)) {
            return wrappedFetch(input, init);
        }

        const body = requestBody(init);
        const key = cacheKey(body);
        if (!key) return wrappedFetch(input, init);

        const cached = cache.get(key);
        if (cached) {
            return Promise.resolve(responseFrom(cached));
        }

        if (inFlight.has(key)) {
            return inFlight.get(key).then(response => response.clone());
        }

        const promise = fetchAndCache(input, init, key)
            .finally(() => inFlight.delete(key));
        inFlight.set(key, promise);
        return promise;
    };

    document.addEventListener('click', event => {
        if (!event.shiftKey) return;
        const button = event.target?.closest?.(
            '.mlx-message-speech-button, .mlx-user-speech-button'
        );
        if (!button) return;
        invalidateText(messageText(button));
    }, true);

    window.addEventListener('mlx:voice-settings-changed', () => {
        cache.clear();
        inFlight.clear();
    });

    window.MLXTTSCache = {
        clear: () => cache.clear(),
        size: () => cache.size,
        invalidateText,
        has: (text) => [...cache.keys()].some(key => {
            try {
                return String(JSON.parse(key).input || '') === String(text || '');
            } catch (_) {
                return false;
            }
        })
    };
})();
