(function () {
    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();

        return {
            response: response,
            data: data
        };
    }

    function fastApiDetailError(data) {
        return new Error(
            typeof data.detail === 'string'
                ? data.detail
                : JSON.stringify(data.detail)
        );
    }

    function jsonRequest(method, data) {
        return {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        };
    }

    function loadScript(src, datasetKey) {
        return new Promise((resolve, reject) => {
            const selector = `script[data-${datasetKey}]`;
            const existing = document.querySelector(selector);
            if (existing) {
                if (existing.dataset.loaded === '1') {
                    resolve();
                } else {
                    existing.addEventListener('load', resolve, { once: true });
                    existing.addEventListener('error', reject, { once: true });
                }
                return;
            }

            const script = document.createElement('script');
            script.src = src;
            script.setAttribute(`data-${datasetKey}`, '1');
            script.addEventListener('load', () => {
                script.dataset.loaded = '1';
                resolve();
            }, { once: true });
            script.addEventListener('error', reject, { once: true });
            document.head.appendChild(script);
        });
    }

    async function loadChatVoiceControls() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/voice.js?v=20260926-voice-popover-2',
                'mlx-voice-controls'
            );
            await loadScript(
                '/assets/chat/tts-cache.js?v=20260926-tts-cache',
                'mlx-tts-cache'
            );
            await loadScript(
                '/assets/chat/user-voice.js?v=20260926-user-voice-2',
                'mlx-user-voice-controls'
            );
        } catch (error) {
            console.error('[voice] Failed to load voice controls:', error);
        }
    }

    window.MLXCommon = {
        fetchJson: fetchJson,
        fastApiDetailError: fastApiDetailError,
        jsonRequest: jsonRequest
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadChatVoiceControls, { once: true });
    } else {
        loadChatVoiceControls();
    }
})();
