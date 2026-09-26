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

    window.MLXTTSCache = {
        clear: () => cache.clear(),
        size: () => cache.size,
        has: (text) => [...cache.keys()].some(key => key.includes(String(text || '')))
    };
})();
